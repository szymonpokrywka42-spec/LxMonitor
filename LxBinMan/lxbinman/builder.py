from __future__ import annotations

import json
import platform
from pathlib import Path
import subprocess
import shutil
import sys
import time
from typing import Literal
from typing import Iterable

from . import autobin
from .feedback import FeedbackBus


class BuilderError(RuntimeError):
    pass


EngineConfig = dict[str, dict[str, object]]
CleanMode = Literal["light", "standard", "deep"]
CleanProfile = Literal["dev", "ci", "release"]

CLEAN_PROFILES: dict[str, dict[str, object]] = {
    # Fast local cleanup, keeps heavy caches by default.
    "dev": {
        "mode": "light",
        "remove_cache": False,
        "remove_local_outputs": True,
        "remove_orphans": True,
        "remove_pycache": False,
        "remove_build_artifacts": False,
    },
    # CI-friendly clean between runs.
    "ci": {
        "mode": "standard",
        "remove_cache": True,
        "remove_local_outputs": True,
        "remove_orphans": True,
        "remove_pycache": True,
        "remove_build_artifacts": True,
    },
    # Release-grade cleanup, as deterministic as possible.
    "release": {
        "mode": "deep",
        "remove_cache": True,
        "remove_local_outputs": True,
        "remove_orphans": True,
        "remove_pycache": True,
        "remove_build_artifacts": True,
    },
}


def _detect_project_root(source_dir: Path) -> Path:
    src = source_dir.resolve()
    for parent in [src] + list(src.parents):
        if (parent / "assets").exists() or (parent / "pyproject.toml").exists():
            return parent
    return src.parent


def _event_logger(fb: FeedbackBus):
    def _log(level: str, message: str) -> None:
        code = f"autobin:{level.lower()}"
        fb.emit(level, code, message)

    return _log


def _resolve_feedback(fb: FeedbackBus | None) -> FeedbackBus:
    if fb is not None:
        return fb
    from . import feedback as default_feedback

    return default_feedback


def _toolchain_runtime_key() -> str:
    rt = autobin.runtime_info()
    raw = f"py{rt['python_version']}-{rt['python_soabi'] or 'no-soabi'}-{rt['system']}-{rt['machine']}"
    return "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in raw)


def _toolchain_snapshot_path(source_dir: Path) -> Path:
    project_root = _detect_project_root(source_dir)
    return project_root / ".binman" / "toolchains" / f"{_toolchain_runtime_key()}.json"


def _run_version_cmd(cmd: str, args: list[str]) -> tuple[str, str]:
    path = shutil.which(cmd) or cmd
    try:
        result = subprocess.run(
            [path, *args],
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        raw = (result.stdout or result.stderr or "").strip()
        first = raw.splitlines()[0].strip() if raw else ""
        return str(path), first
    except Exception:
        return str(path), ""


def snapshot_toolchain(
    *,
    source_dir: str | Path,
    feedback: FeedbackBus | None = None,
    compiler: str = "g++",
    python_cmd: str | None = None,
    node_cmd: str | None = None,
    persist: bool = True,
) -> dict[str, object]:
    fb = _resolve_feedback(feedback)
    src = Path(source_dir).resolve()
    rt = autobin.runtime_info()

    py_bin = python_cmd or (sys.executable or "python3")
    py_path, py_ver = _run_version_cmd(py_bin, ["--version"])
    cc_path, cc_ver = _run_version_cmd(compiler, ["--version"])

    node_runner = node_cmd or shutil.which("node") or shutil.which("bun") or shutil.which("deno") or ""
    node_path = ""
    node_ver = ""
    if node_runner:
        node_path, node_ver = _run_version_cmd(node_runner, ["--version"])

    snap = {
        "runtime": rt,
        "platform": {
            "system": platform.system().lower(),
            "release": platform.release(),
            "machine": platform.machine().lower(),
        },
        "python": {"path": py_path, "version": py_ver},
        "compiler": {"path": cc_path, "version": cc_ver},
        "js_runtime": {"path": node_path, "version": node_ver},
    }

    path = _toolchain_snapshot_path(src)
    prev: dict[str, object] = {}
    changed = True
    if path.exists():
        try:
            prev_data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(prev_data, dict):
                prev = prev_data
                changed = prev != snap
        except Exception:
            changed = True

    if persist:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snap, ensure_ascii=True, indent=2), encoding="utf-8")

    fb.info(
        "toolchain:snapshot",
        "Toolchain snapshot ready",
        path=str(path),
        changed=changed,
    )
    return {"path": str(path), "changed": changed, "snapshot": snap, "previous": prev}


def discover_engines(source_dir: str | Path) -> list[str]:
    src = Path(source_dir).resolve()
    if not src.exists():
        raise BuilderError(f"source_dir not found: {src}")
    return sorted(p.stem for p in src.glob("*.cpp") if p.is_file())


def discover_scripts(
    source_dir: str | Path,
    *,
    extensions: tuple[str, ...] = (".py", ".js"),
) -> list[str]:
    src = Path(source_dir).resolve()
    if not src.exists():
        raise BuilderError(f"source_dir not found: {src}")
    normalized = {e.lower() for e in extensions}
    out = [
        str(p)
        for p in sorted(src.iterdir())
        if p.is_file() and p.suffix.lower() in normalized
    ]
    return out


def load_engine_config(
    *,
    source_dir: str | Path,
    config_path: str | Path | None = None,
    feedback: FeedbackBus | None = None,
) -> EngineConfig:
    fb = _resolve_feedback(feedback)
    src = Path(source_dir).resolve()
    cfg = Path(config_path).resolve() if config_path else (src / "engines.json")
    if not cfg.exists():
        return {}
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            fb.warning("config:invalid", "Engine config must be object", path=str(cfg))
            return {}
        out = {k: v for k, v in data.items() if isinstance(v, dict)}
        fb.info("config:loaded", "Engine config loaded", path=str(cfg), entries=len(out))
        return out
    except Exception as e:
        fb.warning("config:error", "Cannot parse engine config", path=str(cfg), error=str(e))
        return {}


def _runner_for_script(script_path: Path, python_cmd: str | None, node_cmd: str | None) -> list[str]:
    suffix = script_path.suffix.lower()
    if suffix == ".py":
        return [python_cmd or (sys.executable or "python3"), str(script_path)]

    if suffix == ".js":
        cmd = node_cmd or shutil.which("node") or shutil.which("bun") or shutil.which("deno")
        if not cmd:
            raise BuilderError("No JS runtime found (node/bun/deno)")
        if cmd.endswith("deno"):
            return [cmd, "run", "--allow-read", str(script_path)]
        return [cmd, str(script_path)]

    raise BuilderError(f"Unsupported script extension: {script_path.suffix}")


def run_script(
    script_path: str | Path,
    *,
    feedback: FeedbackBus | None = None,
    args: list[str] | None = None,
    cwd: str | Path | None = None,
    timeout_s: float | None = None,
    python_cmd: str | None = None,
    node_cmd: str | None = None,
) -> dict[str, object]:
    fb = _resolve_feedback(feedback)
    script = Path(script_path).resolve()
    if not script.exists():
        raise BuilderError(f"script not found: {script}")
    if script.suffix.lower() not in {".py", ".js"}:
        raise BuilderError(f"unsupported script type: {script.suffix}")

    cmd = _runner_for_script(script, python_cmd, node_cmd)
    if args:
        cmd.extend(args)

    fb.info("script:start", "Running script duty", script=str(script), cmd=" ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            cwd=str(Path(cwd).resolve()) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        fb.error("script:timeout", "Script timeout", script=str(script), timeout_s=timeout_s)
        return {"ok": False, "script": str(script), "returncode": None, "stdout": "", "stderr": "timeout"}
    except Exception as e:
        fb.error("script:error", "Script execution error", script=str(script), error=str(e))
        return {"ok": False, "script": str(script), "returncode": None, "stdout": "", "stderr": str(e)}

    ok = result.returncode == 0
    if ok:
        fb.success("script:done", "Script duty done", script=str(script), returncode=result.returncode)
    else:
        fb.warning("script:fail", "Script duty failed", script=str(script), returncode=result.returncode)
    return {
        "ok": ok,
        "script": str(script),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def run_script_all(
    *,
    source_dir: str | Path,
    feedback: FeedbackBus | None = None,
    names: Iterable[str] | None = None,
    extensions: tuple[str, ...] = (".py", ".js"),
    cwd: str | Path | None = None,
    timeout_s: float | None = None,
    python_cmd: str | None = None,
    node_cmd: str | None = None,
) -> dict[str, dict[str, object]]:
    fb = _resolve_feedback(feedback)
    src = Path(source_dir).resolve()
    if not src.exists():
        raise BuilderError(f"source_dir not found: {src}")

    if names is None:
        scripts = discover_scripts(src, extensions=extensions)
    else:
        scripts = [str((src / name).resolve()) for name in names]

    if not scripts:
        fb.info("script:empty", "No script duties found", source_dir=str(src))
        return {}

    fb.info("script:batch-start", "Running script duties", count=len(scripts), source_dir=str(src))
    out: dict[str, dict[str, object]] = {}
    for script in scripts:
        result = run_script(
            script,
            feedback=fb,
            cwd=cwd,
            timeout_s=timeout_s,
            python_cmd=python_cmd,
            node_cmd=node_cmd,
        )
        out[str(script)] = result
    return out


def _engine_opts(
    engine_name: str,
    *,
    config: EngineConfig | None,
    extra_compile_args: list[str] | None,
    extra_link_args: list[str] | None,
) -> tuple[list[str] | None, list[str] | None, str | None, str | None]:
    cfg = (config or {}).get(engine_name, {})
    cargs = list(extra_compile_args or [])
    largs = list(extra_link_args or [])

    v = cfg.get("extra_compile_args")
    if isinstance(v, list):
        cargs.extend(str(x) for x in v)

    v = cfg.get("extra_link_args")
    if isinstance(v, list):
        largs.extend(str(x) for x in v)

    policy = cfg.get("policy")
    policy_s = str(policy) if isinstance(policy, str) else None

    compiler = cfg.get("compiler")
    compiler_s = str(compiler) if isinstance(compiler, str) else None

    return (cargs or None, largs or None, policy_s, compiler_s)


def build_engine(
    engine_name: str,
    *,
    source_dir: str | Path,
    feedback: FeedbackBus | None = None,
    prebuilt_root: str | Path | None = None,
    cache_root: str | Path | None = None,
    output_dir: str | Path | None = None,
    compiler: str = "g++",
    cxx_std: str = "c++17",
    extra_compile_args: list[str] | None = None,
    extra_link_args: list[str] | None = None,
    compile_only: bool = False,
    save_prebuilt: bool = True,
    policy: autobin.LoadPolicy = "prefer_prebuilt",
    engine_config: EngineConfig | None = None,
):
    fb = _resolve_feedback(feedback)
    try:
        cargs, largs, policy_override, compiler_override = _engine_opts(
            engine_name,
            config=engine_config,
            extra_compile_args=extra_compile_args,
            extra_link_args=extra_link_args,
        )
        mod = autobin.load(
            engine_name,
            source_dir=str(source_dir),
            prebuilt_root=str(prebuilt_root) if prebuilt_root else None,
            cache_root=str(cache_root) if cache_root else None,
            output_dir=str(output_dir) if output_dir else None,
            compiler=compiler_override or compiler,
            cxx_std=cxx_std,
            extra_compile_args=cargs,
            extra_link_args=largs,
            compile_only=compile_only,
            save_prebuilt=save_prebuilt,
            policy=policy_override or policy,
            log=_event_logger(fb),
        )
        fb.success("builder:engine", f"Engine ready: {engine_name}")
        return mod
    except Exception as e:
        fb.error("builder:engine", f"Engine failed: {engine_name}", error=str(e))
        raise


def build_all(
    *,
    source_dir: str | Path,
    feedback: FeedbackBus | None = None,
    names: Iterable[str] | None = None,
    prebuilt_root: str | Path | None = None,
    cache_root: str | Path | None = None,
    output_dir: str | Path | None = None,
    compiler: str = "g++",
    cxx_std: str = "c++17",
    extra_compile_args: list[str] | None = None,
    extra_link_args: list[str] | None = None,
    compile_only: bool = False,
    save_prebuilt: bool = True,
    policy: autobin.LoadPolicy = "prefer_prebuilt",
    engine_config: EngineConfig | None = None,
    config_path: str | Path | None = None,
) -> dict[str, object]:
    fb = _resolve_feedback(feedback)
    src = Path(source_dir).resolve()
    engines = list(names) if names is not None else discover_engines(src)
    if not engines:
        fb.warning("builder:empty", "No C++ engines found", source_dir=str(src))
        return {}

    cfg = engine_config if engine_config is not None else load_engine_config(source_dir=src, config_path=config_path, feedback=fb)
    snapshot_toolchain(source_dir=src, feedback=fb, compiler=compiler, persist=True)

    fb.info("builder:start", "Building/loading engines", count=len(engines), source_dir=str(src), policy=policy)
    result: dict[str, object] = {}
    failed: list[str] = []
    for name in engines:
        try:
            result[name] = build_engine(
                name,
                source_dir=src,
                feedback=fb,
                prebuilt_root=prebuilt_root,
                cache_root=cache_root,
                output_dir=output_dir,
                compiler=compiler,
                cxx_std=cxx_std,
                extra_compile_args=extra_compile_args,
                extra_link_args=extra_link_args,
                compile_only=compile_only,
                save_prebuilt=save_prebuilt,
                policy=policy,
                engine_config=cfg,
            )
        except Exception:
            failed.append(name)

    if failed:
        fb.warning("builder:partial", "Some engines failed", failed=",".join(failed))
    else:
        fb.success("builder:done", "All engines ready", count=len(result))
    return result


def fast_boot_build_all(
    *,
    source_dir: str | Path,
    feedback: FeedbackBus | None = None,
    names: Iterable[str] | None = None,
    output_dir: str | Path | None = None,
    compiler: str = "g++",
    cxx_std: str = "c++17",
    engine_config: EngineConfig | None = None,
    config_path: str | Path | None = None,
) -> dict[str, object]:
    """
    Fast boot profile:
    - compile_only=True (does not import modules)
    - prefer_cache policy
    - save_prebuilt=True for warm restore on next run
    """
    return build_all(
        source_dir=source_dir,
        feedback=feedback,
        names=names,
        output_dir=output_dir,
        compiler=compiler,
        cxx_std=cxx_std,
        compile_only=True,
        save_prebuilt=True,
        policy="prefer_cache",
        engine_config=engine_config,
        config_path=config_path,
    )


def clean_binaries(
    *,
    source_dir: str | Path,
    feedback: FeedbackBus | None = None,
    cache_root: str | Path | None = None,
    profile: CleanProfile | None = None,
    remove_local_outputs: bool = True,
    remove_cache: bool | None = None,
    remove_orphans: bool = True,
    remove_pycache: bool | None = None,
    remove_build_artifacts: bool | None = None,
    mode: CleanMode = "standard",
    exclude: Iterable[str] | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    fb = _resolve_feedback(feedback)
    src = Path(source_dir).resolve()
    project_root = _detect_project_root(src)
    cache_base = Path(cache_root).resolve() if cache_root else (project_root / ".binman" / "cache")

    removed: list[str] = []
    missing: list[str] = []
    skipped: list[str] = []
    bytes_freed = 0

    if profile is not None:
        preset = CLEAN_PROFILES.get(str(profile))
        if preset is None:
            raise BuilderError(f"invalid clean profile: {profile}")
        mode = str(preset.get("mode", mode))  # type: ignore[assignment]
        remove_cache = bool(preset.get("remove_cache", remove_cache))
        remove_local_outputs = bool(preset.get("remove_local_outputs", remove_local_outputs))
        remove_orphans = bool(preset.get("remove_orphans", remove_orphans))
        remove_pycache = bool(preset.get("remove_pycache", remove_pycache))
        remove_build_artifacts = bool(preset.get("remove_build_artifacts", remove_build_artifacts))

    if mode not in {"light", "standard", "deep"}:
        raise BuilderError(f"invalid clean mode: {mode}")

    if remove_cache is None:
        remove_cache = mode in {"standard", "deep"}
    if remove_pycache is None:
        remove_pycache = mode == "deep"
    if remove_build_artifacts is None:
        remove_build_artifacts = mode in {"standard", "deep"}

    exclude_resolved: list[Path] = []
    for raw in (exclude or []):
        try:
            exclude_resolved.append(Path(raw).resolve())
        except Exception:
            continue

    def _is_excluded(path: Path) -> bool:
        for ex in exclude_resolved:
            if path == ex or ex in path.parents:
                return True
        return False

    def _path_size(path: Path) -> int:
        try:
            if path.is_file():
                return path.stat().st_size
            total = 0
            for p in path.rglob("*"):
                if p.is_file():
                    total += p.stat().st_size
            return total
        except Exception:
            return 0

    def _engine_base_from_binary(path: Path) -> str:
        name = path.name
        for suffix in (".so", ".pyd", ".dylib"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        # cpu.cpython-313-x86_64-linux-gnu -> cpu
        return name.split(".", 1)[0]

    def _rm_path(path: Path) -> None:
        nonlocal bytes_freed
        if _is_excluded(path):
            skipped.append(str(path))
            return
        if not path.exists():
            missing.append(str(path))
            return
        reclaimed = _path_size(path)
        if dry_run:
            removed.append(str(path))
            bytes_freed += reclaimed
            return
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
        removed.append(str(path))
        bytes_freed += reclaimed

    if remove_cache:
        _rm_path(cache_base)
    _rm_path(src / ".abi_cache")

    if remove_local_outputs:
        for pattern in ("*.so", "*.pyd", "*.dylib"):
            for bin_file in src.glob(pattern):
                _rm_path(bin_file)

    if remove_orphans:
        engine_names = {p.stem for p in src.glob("*.cpp") if p.is_file()}
        for pattern in ("*.so", "*.pyd", "*.dylib"):
            for bin_file in src.glob(pattern):
                base = _engine_base_from_binary(bin_file)
                if base and base not in engine_names:
                    _rm_path(bin_file)

    if remove_build_artifacts:
        for dname in ("build", "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache"):
            _rm_path(project_root / dname)
        for pattern in ("*.egg-info",):
            for d in project_root.glob(pattern):
                _rm_path(d)
        for pattern in ("*.tmp", "*.tmp.*", "*.lock", "*.o", "*.obj", "*.a", "*.la", "*.log"):
            for p in project_root.rglob(pattern):
                _rm_path(p)
        _rm_path(project_root / "CMakeCache.txt")

    if remove_pycache:
        for d in project_root.rglob("__pycache__"):
            _rm_path(d)
        for pattern in ("*.pyc", "*.pyo"):
            for p in project_root.rglob(pattern):
                _rm_path(p)

    fb.info(
        "builder:clean",
        "Binary cleanup finished",
        profile=profile or "",
        mode=mode,
        removed=len(removed),
        missing=len(missing),
        skipped=len(skipped),
        bytes_freed=bytes_freed,
        dry_run=dry_run,
    )
    return {
        "removed": removed,
        "missing": missing,
        "skipped": skipped,
        "bytes_freed": bytes_freed,
        "profile": profile or "",
        "mode": mode,
        "dry_run": dry_run,
    }


def prune_cache(
    *,
    source_dir: str | Path,
    feedback: FeedbackBus | None = None,
    cache_root: str | Path | None = None,
    max_versions: int = 3,
    max_age_days: int | None = 30,
    dry_run: bool = False,
) -> dict[str, list[str]]:
    fb = _resolve_feedback(feedback)
    src = Path(source_dir).resolve()
    project_root = _detect_project_root(src)
    cache_base = Path(cache_root).resolve() if cache_root else (project_root / ".binman" / "cache")

    removed: list[str] = []
    kept: list[str] = []

    if not cache_base.exists():
        fb.info("cache:prune", "Cache root not found", path=str(cache_base))
        return {"removed": removed, "kept": kept}

    dirs = [p for p in cache_base.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    now = time.time()

    for idx, d in enumerate(dirs):
        age_days = (now - d.stat().st_mtime) / 86400.0
        too_many = idx >= max_versions
        too_old = max_age_days is not None and age_days > float(max_age_days)
        if too_many or too_old:
            removed.append(str(d))
            if not dry_run:
                shutil.rmtree(d, ignore_errors=True)
        else:
            kept.append(str(d))

    fb.info("cache:prune", "Cache pruning done", removed=len(removed), kept=len(kept), dry_run=dry_run)
    return {"removed": removed, "kept": kept}


def healthcheck(
    *,
    source_dir: str | Path,
    feedback: FeedbackBus | None = None,
    compiler: str = "g++",
) -> dict[str, object]:
    fb = _resolve_feedback(feedback)
    report = autobin.healthcheck(source_dir=str(source_dir), compiler=compiler)
    fb.info("healthcheck", "Healthcheck complete", ok=bool(report.get("ok")))
    return report


def run_duties(
    *,
    heavy_source_dir: str | Path,
    script_source_dir: str | Path | None = None,
    feedback: FeedbackBus | None = None,
    heavy_names: Iterable[str] | None = None,
    script_names: Iterable[str] | None = None,
    policy: autobin.LoadPolicy = "prefer_prebuilt",
    engine_config: EngineConfig | None = None,
    config_path: str | Path | None = None,
) -> dict[str, object]:
    """
    Unified runner:
    - heavy duties => C++ engines (.cpp -> .so via autobin)
    - script duties => Python/JS scripts
    """
    fb = _resolve_feedback(feedback)
    fb.info("duties:start", "Starting heavy+script duties pipeline")
    heavy = build_all(
        source_dir=heavy_source_dir,
        feedback=fb,
        names=heavy_names,
        policy=policy,
        engine_config=engine_config,
        config_path=config_path,
    )
    scripts: dict[str, dict[str, object]] = {}
    if script_source_dir is not None:
        scripts = run_script_all(
            source_dir=script_source_dir,
            feedback=fb,
            names=script_names,
        )
    fb.success(
        "duties:done",
        "Duties pipeline finished",
        heavy=len(heavy),
        scripts=len(scripts),
    )
    return {"heavy": heavy, "scripts": scripts}
