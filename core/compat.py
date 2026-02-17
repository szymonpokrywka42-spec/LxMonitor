from __future__ import annotations

import os
import platform
import shutil
import sys
import sysconfig
from typing import Callable


def collect_runtime_compat() -> dict[str, object]:
    de = (
        os.environ.get("XDG_CURRENT_DESKTOP")
        or os.environ.get("DESKTOP_SESSION")
        or os.environ.get("GDMSESSION")
        or "unknown"
    )
    session = os.environ.get("XDG_SESSION_TYPE", "unknown")

    tools = {
        name: bool(shutil.which(name))
        for name in (
            "python",
            "g++",
            "clang++",
            "pkexec",
            "sudo",
            "lsblk",
            "lspci",
            "sensors",
            "nmcli",
            "iw",
            "bluetoothctl",
            "nvidia-smi",
        )
    }

    sensors = {
        "proc_stat": os.path.isfile("/proc/stat"),
        "proc_meminfo": os.path.isfile("/proc/meminfo"),
        "proc_net_dev": os.path.isfile("/proc/net/dev"),
        "sys_drm": os.path.isdir("/sys/class/drm"),
        "sys_hwmon": os.path.isdir("/sys/class/hwmon"),
        "sys_thermal": os.path.isdir("/sys/class/thermal"),
        "sys_power_supply": os.path.isdir("/sys/class/power_supply"),
        "sys_bluetooth": os.path.isdir("/sys/class/bluetooth"),
    }

    return {
        "system": platform.system().lower(),
        "release": platform.release(),
        "machine": platform.machine().lower(),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "soabi": sysconfig.get_config_var("SOABI") or "",
        "desktop_env": str(de),
        "session_type": str(session),
        "tools": tools,
        "sensors": sensors,
    }


def log_compat_report(report: dict[str, object], log_fn: Callable[[str, str], None]) -> None:
    sys_name = report.get("system", "unknown")
    py = report.get("python", "unknown")
    soabi = report.get("soabi", "unknown")
    de = report.get("desktop_env", "unknown")
    sess = report.get("session_type", "unknown")
    log_fn(f"Runtime: {sys_name} | Python {py} | ABI {soabi}", "BOOT")
    log_fn(f"Session: {sess} | Desktop: {de}", "BOOT")

    tools = report.get("tools", {})
    if isinstance(tools, dict):
        missing_tools = [name for name, ok in tools.items() if not bool(ok)]
        if missing_tools:
            log_fn(f"Optional tools missing: {', '.join(missing_tools)}", "WARN")

    sensors = report.get("sensors", {})
    if isinstance(sensors, dict):
        missing_sensors = [name for name, ok in sensors.items() if not bool(ok)]
        if missing_sensors:
            log_fn(f"Optional sensor paths missing: {', '.join(missing_sensors)}", "WARN")

