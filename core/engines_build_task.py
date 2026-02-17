import os
import shlex
import subprocess
import sys
import sysconfig
from pathlib import Path

STATUS_UP_TO_DATE = "UP_TO_DATE"
STATUS_SUCCESS = "SUCCESS"
STATUS_PARTIAL = "PARTIAL"
STATUS_FAILED = "FAILED"


OPTIONAL_ENGINES = {"gpu_nvidia"}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _engines_dir() -> Path:
    return _project_root() / "core" / "engines"


def _cpp_sources() -> list[Path]:
    return sorted(p for p in _engines_dir().glob("*.cpp") if p.is_file())


def _pybind_includes() -> list[str]:
    cmd = [sys.executable, "-m", "pybind11", "--includes"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "pybind11 --includes failed").strip())
    return shlex.split(result.stdout.strip())


def _needs_rebuild(src: Path, so: Path) -> bool:
    if not so.exists():
        return True
    return src.stat().st_mtime > so.stat().st_mtime


def _has_nvml_headers() -> bool:
    candidates = [
        "/usr/include/nvml.h",
        "/usr/local/include/nvml.h",
        "/opt/cuda/include/nvml.h",
        "/usr/include/nvidia/gdk/nvml.h",
    ]
    if any(os.path.exists(p) for p in candidates):
        return True
    cpath = os.environ.get("CPATH", "")
    for d in cpath.split(":"):
        d = d.strip()
        if d and os.path.exists(os.path.join(d, "nvml.h")):
            return True
    return False


def run_build() -> tuple[str, str]:
    sources = _cpp_sources()
    if not sources:
        return STATUS_FAILED, "no cpp sources in core/engines"

    includes = _pybind_includes()
    base_flags = ["-O3", "-shared", "-std=c++17", "-fPIC", "-fvisibility=hidden", *includes]

    compiled = 0
    failed = []
    optional_skipped = []

    for src in sources:
        name = src.stem
        out_so = src.with_suffix(".so")

        if not _needs_rebuild(src, out_so):
            continue

        if name == "gpu_nvidia" and not _has_nvml_headers():
            optional_skipped.append(name)
            continue

        tmp_out = Path(str(out_so) + ".tmp")
        cmd = ["g++", *base_flags, str(src), "-o", str(tmp_out)]
        if name == "gpu_nvidia":
            cmd.append("-lnvidia-ml")

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            try:
                tmp_out.unlink(missing_ok=True)
            except Exception:
                pass
            err = (result.stderr or result.stdout or "build failed").strip()
            if name in OPTIONAL_ENGINES and ("nvml.h" in err.lower() or "nvidia" in err.lower()):
                optional_skipped.append(name)
                continue
            failed.append(f"{name}: {err}")
            continue

        os.replace(tmp_out, out_so)
        compiled += 1

    if failed:
        return STATUS_PARTIAL, "; ".join(failed)
    if compiled == 0:
        return STATUS_UP_TO_DATE, "no changes"
    if optional_skipped:
        return STATUS_PARTIAL, f"optional skipped: {', '.join(optional_skipped)}"
    return STATUS_SUCCESS, f"compiled={compiled}"


def main() -> int:
    status, detail = run_build()
    print(f"__LXMONITOR_BUILD_STATUS__={status}")
    if detail:
        print(f"__LXMONITOR_BUILD_DETAIL__={detail}")
    return 0 if status in {STATUS_UP_TO_DATE, STATUS_SUCCESS, STATUS_PARTIAL} else 1


if __name__ == "__main__":
    raise SystemExit(main())
