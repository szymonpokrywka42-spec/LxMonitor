from __future__ import annotations

import json
import platform
import sys
import sysconfig
from pathlib import Path
from typing import Any


def runtime_info() -> dict[str, str]:
    return {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "python_soabi": sysconfig.get_config_var("SOABI") or "",
        "system": platform.system().lower(),
        "machine": platform.machine().lower(),
    }


def cache_key() -> str:
    info = runtime_info()
    raw = (
        f"py{info['python_version']}-"
        f"{info['python_soabi'] or 'no-soabi'}-"
        f"{info['system']}-{info['machine']}"
    )
    return "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in raw)


def read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def is_manifest_compatible(manifest_data: dict[str, Any]) -> bool:
    if not manifest_data:
        return True
    info = runtime_info()

    for key in ("python_version", "python_soabi", "system", "machine"):
        expected = str(manifest_data.get(key, "")).strip().lower()
        if not expected:
            continue
        got = str(info.get(key, "")).strip().lower()
        if expected != got:
            return False
    return True
