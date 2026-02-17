from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Callable, Literal

from .manifest import cache_key as _cache_key
from .manifest import is_manifest_compatible, read_manifest, runtime_info


class AutoBinError(RuntimeError):
    pass


LoadPolicy = Literal["prefer_prebuilt", "prefer_cache", "build_only", "prebuilt_only"]
Logger = Callable[[str, str], None]


def _default_log(level: str, message: str) -> None:
    print(f"[{level}] {message}")


def _ext_suffix() -> str:
    return sysconfig.get_config_var("EXT_SUFFIX") or ".so"


def _import_module_from_path(engine_name: str, so_path: Path):
    # Pybind module init name must match Python module name (PyInit_<name>).
    # Using random names breaks loading for modules compiled as `PYBIND11_MODULE(cpu, m)`.
    mod_name = engine_name
    spec = importlib.util.spec_from_file_location(mod_name, str(so_path))
    if spec is None or spec.loader is None:
        raise AutoBinError(f"Cannot create import spec for: {so_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _detect_project_root(source_dir: Path) -> Path:
    curr = source_dir.resolve()
    for parent in [curr] + list(curr.parents):
        if (parent / "assets").exists() or (parent / "pyproject.toml").exists():
            return parent
    return curr.parent


def _default_cache_root(source_dir: Path) -> Path:
    project_root = _detect_project_root(source_dir)
    return project_root / ".binman" / "cache"


def _default_prebuilt_root(source_dir: Path) -> Path:
    project_root = _detect_project_root(source_dir)
    return project_root / "assets" / "binaries"


def _pybind11_includes(log: Logger) -> list[str]:
    cmd = [sys.executable or "python3", "-m", "pybind11", "--includes"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AutoBinError(
            f"pybind11 include detection failed: {(result.stderr or '').strip()}"
        )
    includes = result.stdout.strip().split()
    if not includes:
        raise AutoBinError("pybind11 include detection returned empty list")
    log("INFO", f"Using includes from pybind11 ({len(includes)} entries)")
    return includes


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _abi_sidecar_path(so_path: Path) -> Path:
    return so_path.with_name(f"{so_path.name}.abi.json")


def _read_abi_sidecar(so_path: Path) -> dict:
    sidecar = _abi_sidecar_path(so_path)
    if not sidecar.exists():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _is_abi_compatible(
    so_path: Path,
    *,
    expected_signature: dict | None = None,
) -> bool:
    expected = runtime_info()
    got = _read_abi_sidecar(so_path)
    if not got:
        return False
    for key in ("python_version", "python_soabi", "system", "machine"):
        if str(got.get(key, "")) != str(expected.get(key, "")):
            return False
    if expected_signature:
        got_sig = got.get("build_signature")
        if not isinstance(got_sig, dict):
            return False
        if got_sig != expected_signature:
            return False
    return True


def _write_abi_sidecar(
    so_path: Path,
    *,
    build_signature: dict | None = None,
) -> None:
    sidecar = _abi_sidecar_path(so_path)
    data = runtime_info()
    if build_signature:
        data["build_signature"] = build_signature
    sidecar.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


def _build_signature(
    cpp_path: Path,
    *,
    compiler: str,
    cxx_std: str,
    extra_compile_args: list[str] | None,
    extra_link_args: list[str] | None,
) -> dict:
    return {
        "source_sha256": _sha256_file(cpp_path),
        "compiler": str(compiler),
        "cxx_std": str(cxx_std),
        "extra_compile_args": list(extra_compile_args or []),
        "extra_link_args": list(extra_link_args or []),
    }


def _manifest_path(dir_path: Path) -> Path:
    return dir_path / "manifest.json"


def _upsert_prebuilt_manifest(prebuilt_dir: Path, so_path: Path) -> None:
    manifest_path = _manifest_path(prebuilt_dir)
    data = read_manifest(manifest_path)
    rt = runtime_info()
    for key in ("python_version", "python_soabi", "system", "machine"):
        data[key] = rt[key]
    hashes = data.get("hashes")
    if not isinstance(hashes, dict):
        hashes = {}
    hashes[so_path.name] = _sha256_file(so_path)
    data["hashes"] = hashes
    prebuilt_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


def _backup_prebuilt(
    *,
    target_so: Path,
    target_sidecar: Path,
    prebuilt_so: Path,
    log: Logger,
) -> None:
    prebuilt_dir = prebuilt_so.parent
    prebuilt_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target_so, prebuilt_so)
    if target_sidecar.exists():
        shutil.copy2(target_sidecar, _abi_sidecar_path(prebuilt_so))
    _upsert_prebuilt_manifest(prebuilt_dir, prebuilt_so)
    log("INFO", f"Saved prebuilt backup for {target_so.stem} -> {prebuilt_so}")


def _build_module(
    engine_name: str,
    cpp_path: Path,
    out_so: Path,
    *,
    compiler: str,
    cxx_std: str,
    extra_compile_args: list[str] | None,
    extra_link_args: list[str] | None,
    log: Logger,
) -> None:
    includes = _pybind11_includes(log)

    out_so.parent.mkdir(parents=True, exist_ok=True)
    tmp_so = out_so.with_suffix(out_so.suffix + ".tmp")

    cmd = [
        compiler,
        "-O3",
        "-shared",
        f"-std={cxx_std}",
        "-fPIC",
        "-fvisibility=hidden",
        *includes,
    ]
    if extra_compile_args:
        cmd.extend(extra_compile_args)
    cmd.extend([str(cpp_path), "-o", str(tmp_so)])
    if extra_link_args:
        cmd.extend(extra_link_args)

    log("ENGINE", f"Compiling {engine_name} with {compiler}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        if tmp_so.exists():
            tmp_so.unlink(missing_ok=True)
        stderr = (result.stderr or "").strip()
        raise AutoBinError(f"Build failed for '{engine_name}': {stderr}")

    os.replace(tmp_so, out_so)
    log("SUCCESS", f"Built {engine_name} -> {out_so}")


def _copy_if_fresh_verified(
    src: Path,
    dst: Path,
    cpp_path: Path,
    manifest_data: dict,
    log: Logger,
) -> bool:
    if not src.exists():
        return False
    try:
        if src.stat().st_mtime < cpp_path.stat().st_mtime:
            return False
    except Exception:
        return False

    hashes = manifest_data.get("hashes") if isinstance(manifest_data, dict) else None
    if isinstance(hashes, dict):
        expected = str(hashes.get(src.name, "")).strip().lower()
        if expected:
            got = _sha256_file(src).lower()
            if got != expected:
                log("WARN", f"SHA mismatch for prebuilt '{src.name}', skipping")
                return False

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    log("INFO", f"Restored {dst.name} from {src}")
    return True


def _manifest_ok(bin_dir: Path, log: Logger) -> tuple[bool, dict]:
    manifest = read_manifest(bin_dir / "manifest.json")
    if not manifest:
        return True, {}
    ok = is_manifest_compatible(manifest)
    if not ok:
        log("WARN", f"Manifest mismatch in {bin_dir}/manifest.json")
    return ok, manifest


def load(
    engine_name: str,
    *,
    source_dir: str,
    prebuilt_root: str | None = None,
    cache_root: str | None = None,
    output_dir: str | None = None,
    compiler: str = "g++",
    cxx_std: str = "c++17",
    extra_compile_args: list[str] | None = None,
    extra_link_args: list[str] | None = None,
    compile_only: bool = False,
    save_prebuilt: bool = True,
    policy: LoadPolicy = "prefer_prebuilt",
    log: Logger | None = None,
):
    """
    Load engine module by name with strategy controlled by policy.

    Policies:
    - prefer_prebuilt: prebuilt -> cache -> build
    - prefer_cache: cache -> prebuilt -> build
    - build_only: build only
    - prebuilt_only: prebuilt only (no build)
    """
    logger = log or _default_log
    src_dir = Path(source_dir).resolve()
    if not src_dir.exists():
        raise AutoBinError(f"source_dir not found: {src_dir}")

    cpp_path = src_dir / f"{engine_name}.cpp"
    if not cpp_path.exists():
        raise AutoBinError(f"source file not found: {cpp_path}")

    suffix = ".so" if output_dir else _ext_suffix()
    key = _cache_key()

    pre_root = Path(prebuilt_root).resolve() if prebuilt_root else _default_prebuilt_root(src_dir)
    cache_base = Path(cache_root).resolve() if cache_root else _default_cache_root(src_dir)

    cache_dir = cache_base / key
    cache_so = cache_dir / f"{engine_name}{_ext_suffix()}"
    target_dir = Path(output_dir).resolve() if output_dir else cache_dir
    target_so = target_dir / f"{engine_name}{suffix}"

    logger("INFO", f"autobin.load('{engine_name}') key={key} policy={policy}")

    prebuilt_key_dir = pre_root / key
    prebuilt_key_so = prebuilt_key_dir / f"{engine_name}{suffix}"
    prebuilt_plain_so = pre_root / f"{engine_name}{suffix}"
    abi_guard_enabled = bool(output_dir)
    signature = _build_signature(
        cpp_path,
        compiler=compiler,
        cxx_std=cxx_std,
        extra_compile_args=extra_compile_args,
        extra_link_args=extra_link_args,
    )

    def try_prebuilt() -> bool:
        ok_key, manifest_key = _manifest_ok(prebuilt_key_dir, logger)
        if ok_key and _copy_if_fresh_verified(prebuilt_key_so, target_so, cpp_path, manifest_key, logger):
            if abi_guard_enabled:
                _write_abi_sidecar(target_so, build_signature=signature)
            return True

        ok_plain, manifest_plain = _manifest_ok(pre_root, logger)
        if ok_plain and _copy_if_fresh_verified(prebuilt_plain_so, target_so, cpp_path, manifest_plain, logger):
            if abi_guard_enabled:
                _write_abi_sidecar(target_so, build_signature=signature)
            return True

        return False

    def try_cache() -> bool:
        if not target_so.exists():
            return False
        if target_so.stat().st_mtime < cpp_path.stat().st_mtime:
            return False
        if abi_guard_enabled and not _is_abi_compatible(target_so, expected_signature=signature):
            logger("WARN", f"ABI guard: stale local binary for {engine_name}, forcing rebuild")
            return False
        return True

    build_status = "up_to_date"
    if policy == "build_only":
        _build_module(
            engine_name,
            cpp_path,
            target_so,
            compiler=compiler,
            cxx_std=cxx_std,
            extra_compile_args=extra_compile_args,
            extra_link_args=extra_link_args,
            log=logger,
        )
        if abi_guard_enabled:
            _write_abi_sidecar(target_so, build_signature=signature)
            if save_prebuilt:
                _backup_prebuilt(
                    target_so=target_so,
                    target_sidecar=_abi_sidecar_path(target_so),
                    prebuilt_so=prebuilt_key_so,
                    log=logger,
                )
        build_status = "rebuilt"
        if compile_only:
            return {"ok": True, "path": str(target_so), "status": build_status}
        return _import_module_from_path(engine_name, target_so)

    if policy == "prebuilt_only":
        if not try_prebuilt():
            raise AutoBinError(f"prebuilt_only: no compatible prebuilt for '{engine_name}'")
        build_status = "restored"
        if compile_only:
            return {"ok": True, "path": str(target_so), "status": build_status}
        return _import_module_from_path(engine_name, target_so)

    if policy == "prefer_cache":
        if try_cache():
            logger("INFO", f"Using ABI cache for {engine_name}")
            if abi_guard_enabled and save_prebuilt:
                _backup_prebuilt(
                    target_so=target_so,
                    target_sidecar=_abi_sidecar_path(target_so),
                    prebuilt_so=prebuilt_key_so,
                    log=logger,
                )
            if compile_only:
                return {"ok": True, "path": str(target_so), "status": build_status}
            return _import_module_from_path(engine_name, target_so)
        if try_prebuilt():
            build_status = "restored"
            if compile_only:
                return {"ok": True, "path": str(target_so), "status": build_status}
            return _import_module_from_path(engine_name, target_so)
    else:  # prefer_prebuilt
        if try_prebuilt():
            build_status = "restored"
            if compile_only:
                return {"ok": True, "path": str(target_so), "status": build_status}
            return _import_module_from_path(engine_name, target_so)
        if try_cache():
            logger("INFO", f"Using ABI cache for {engine_name}")
            if abi_guard_enabled and save_prebuilt:
                _backup_prebuilt(
                    target_so=target_so,
                    target_sidecar=_abi_sidecar_path(target_so),
                    prebuilt_so=prebuilt_key_so,
                    log=logger,
                )
            if compile_only:
                return {"ok": True, "path": str(target_so), "status": build_status}
            return _import_module_from_path(engine_name, target_so)

    _build_module(
        engine_name,
        cpp_path,
        target_so,
        compiler=compiler,
        cxx_std=cxx_std,
        extra_compile_args=extra_compile_args,
        extra_link_args=extra_link_args,
        log=logger,
    )
    if abi_guard_enabled:
        _write_abi_sidecar(target_so, build_signature=signature)
        if save_prebuilt:
            _backup_prebuilt(
                target_so=target_so,
                target_sidecar=_abi_sidecar_path(target_so),
                prebuilt_so=prebuilt_key_so,
                log=logger,
            )
    build_status = "rebuilt"
    if compile_only:
        return {"ok": True, "path": str(target_so), "status": build_status}
    return _import_module_from_path(engine_name, target_so)


def load_many(
    engine_names: list[str],
    *,
    source_dir: str,
    prebuilt_root: str | None = None,
    cache_root: str | None = None,
    output_dir: str | None = None,
    compiler: str = "g++",
    cxx_std: str = "c++17",
    extra_compile_args: list[str] | None = None,
    extra_link_args: list[str] | None = None,
    compile_only: bool = False,
    save_prebuilt: bool = True,
    policy: LoadPolicy = "prefer_prebuilt",
    log: Logger | None = None,
) -> dict[str, object]:
    out: dict[str, object] = {}
    for name in engine_names:
        out[name] = load(
            name,
            source_dir=source_dir,
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
            log=log,
        )
    return out


def healthcheck(
    *,
    source_dir: str | None = None,
    compiler: str = "g++",
    python_cmd: str | None = None,
    node_cmd: str | None = None,
) -> dict[str, object]:
    info = runtime_info()
    report: dict[str, object] = {
        "runtime": info,
        "checks": {},
    }

    def _which_ok(cmd: str) -> bool:
        return shutil.which(cmd) is not None

    checks = report["checks"]
    checks["compiler"] = {
        "cmd": compiler,
        "ok": _which_ok(compiler),
    }

    py = python_cmd or (sys.executable or "python3")
    checks["python"] = {"cmd": py, "ok": _which_ok(Path(py).name) or Path(py).exists()}

    pybind_ok = False
    pybind_err = ""
    try:
        result = subprocess.run([py, "-m", "pybind11", "--includes"], capture_output=True, text=True)
        pybind_ok = result.returncode == 0
        if not pybind_ok:
            pybind_err = (result.stderr or result.stdout or "").strip()
    except Exception as e:
        pybind_err = str(e)
    checks["pybind11"] = {"ok": pybind_ok, "error": pybind_err}

    js_runtime = node_cmd or shutil.which("node") or shutil.which("bun") or shutil.which("deno")
    checks["js_runtime"] = {"cmd": js_runtime or "", "ok": bool(js_runtime)}

    if source_dir:
        src = Path(source_dir).resolve()
        checks["source_dir"] = {"path": str(src), "ok": src.exists()}
        project_root = _detect_project_root(src)
        cache_root = _default_cache_root(src)
        checks["cache_root"] = {
            "path": str(cache_root),
            "ok": cache_root.exists() or os.access(project_root, os.W_OK),
        }

    report["ok"] = all(bool(v.get("ok")) for v in checks.values() if isinstance(v, dict) and "ok" in v)
    report["platform"] = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
    }
    return report


__all__ = [
    "AutoBinError",
    "LoadPolicy",
    "load",
    "load_many",
    "healthcheck",
    "runtime_info",
]
