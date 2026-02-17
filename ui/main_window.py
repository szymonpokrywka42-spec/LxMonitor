from PyQt6.QtWidgets import QMainWindow
import json
import os

from core.console_logic import ConsoleLogic
from core.compat import collect_runtime_compat
from core.handlers.cpp_handler1 import CppHandler1
from core.handlers.cpp_handler2 import CppHandler2
from core.language_handler import LanguageHandler
from core.themes_handler import ThemeHandler

from ui.console import ConsoleDialog
from ui.window.mixins import (
    EnginePrivilegedMixin,
    InteractionsMixin,
    MetricsMixin,
    UiSetupMixin,
)


class LxMainWindow(
    QMainWindow,
    UiSetupMixin,
    MetricsMixin,
    EnginePrivilegedMixin,
    InteractionsMixin,
):
    CONFIG_VERSION = 2
    OPTIONAL_ENGINES = {"gpu_nvidia"}

    def __init__(self, startup_logs=None, build_failures=None):
        super().__init__()

        self.config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config.json"))
        self.user_config = self._load_user_config()
        self.user_config, self._config_migrated = self._migrate_user_config(self.user_config)
        self.config_version = int(self.user_config.get("config_version", self.CONFIG_VERSION))
        self.release_mode_enabled = bool(self.user_config.get("release_mode", False))
        self.language_preference = self.user_config.get("language", "system")
        self.theme_preference = self.user_config.get("theme", "system")
        self.power_mode_preference = self.user_config.get("power_mode", "auto")
        if self.power_mode_preference not in ("auto", "desktop", "laptop"):
            self.power_mode_preference = "auto"
        self.system_power_profile = self._detect_system_power_profile()
        self.advanced_details_enabled = bool(self.user_config.get("advanced_details", True))
        self.safe_mode_enabled = bool(self.user_config.get("safe_mode", False))
        self.safe_mode_auto = bool(self.user_config.get("safe_mode_auto", True))
        self.log_profile = str(self.user_config.get("log_profile", "normal") or "normal").lower()
        if self.log_profile not in ("normal", "debug", "quiet"):
            self.log_profile = "normal"
        self.smoke_report = {"status": "unknown", "required_missing": [], "probes": {}}

        self.repair_language_file()
        self.apply_base_stylesheet()

        self.lang_handler = LanguageHandler(config_lang=self.language_preference)
        self.console_logic = ConsoleLogic(self)
        self.console_logic.set_log_profile(self.log_profile)
        self.theme_manager = ThemeHandler(self, self.console_logic)
        if self._config_migrated:
            self.save_user_config()
            self.console_logic.log(
                f"Config migrated to v{self.CONFIG_VERSION}.",
                "INFO",
            )

        self.h1 = CppHandler1(self.console_logic)
        self.h2 = CppHandler2(self.h1, self.console_logic)

        if startup_logs:
            for log_msg in startup_logs:
                self.console_logic.history.append(log_msg)

        self.console_dialog = ConsoleDialog(self, self.console_logic)
        self.setup_icon()

        self.poll_interval_ms = int(self.user_config.get("poll_interval_ms", 120) or 120)
        if self.poll_interval_ms < 80:
            self.poll_interval_ms = 80
        if self.poll_interval_ms > 3000:
            self.poll_interval_ms = 3000
        if self.safe_mode_enabled and self.poll_interval_ms < 250:
            self.poll_interval_ms = 250
        self.metric_locks = {
            "gpu": True,
            "cpu_temp": True,
            "gpu_temp": True,
        }
        self.metric_cards = {}
        self.cpu_core_graphs = {}
        self.power_sensor_graphs = {}
        self.selected_metric = "cpu"

        self.dynamic_metric_hidden = set()
        self.metric_last_seen = {}
        self.metric_last_active = {}
        self.dynamic_metric_missing_hide_s = 8.0 if self.safe_mode_enabled else 6.0
        self.dynamic_metric_idle_hide_s = 30.0 if self.safe_mode_enabled else 20.0
        self.dynamic_rebuild_interval_s = 1.5 if self.safe_mode_enabled else 1.0
        self._dynamic_last_rebuild_ts = 0.0
        self._priv_backend_cache = None
        self._auth_verified_this_session = False
        self._psu_debug_last_log_ts = 0.0
        self.build_failures = dict(build_failures or {})

        self.latest_sensor_values = {
            "cpu_temp": None,
            "gpu_temp": None,
            "net_rx": 0.0,
            "net_tx": 0.0,
            "net_meta": {},
            "net_bt_merge": {},
            "sys_processes_total": None,
            "sys_procs_running": None,
            "sys_procs_blocked": None,
            "sys_uptime_s": None,
            "sys_load_1m": None,
            "sys_load_5m": None,
            "sys_load_15m": None,
            "sys_mem_total_kb": None,
            "sys_mem_available_kb": None,
            "sys_swap_total_kb": None,
            "sys_swap_free_kb": None,
            "sys_cpu_count": None,
            "sys_cpu_vendor": None,
            "sys_cpu_packages": None,
            "sys_cpu_cores_usage": [],
            "gpu_all": [],
            "bt_all": {},
            "psu_all": {},
        }

        self.cpu_name = self._detect_cpu_name()
        self.gpu_name = self._detect_gpu_name()

        self.setup_ui()
        self.setup_engine_connections()
        self._apply_auto_safe_mode_if_needed()
        self.run_startup_smoke_check()
        self.retranslate_ui()
        self.refresh_blocked_graphs()
        self.show_locked_metrics_warning()

        self.theme_manager.apply_theme(self.theme_preference)
        self.apply_theme_overrides()
        self.h2.start(self.poll_interval_ms)
        self.console_logic.log(
            f"Power mode '{self.power_mode_preference}' resolved to '{self.get_power_mode_resolved()}'.",
            "INFO",
        )

        self.console_logic.log("LxMonitor UI: Ready and Monitoring.", "SUCCESS")

    def _load_user_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    def _migrate_user_config(self, data):
        cfg = dict(data or {})
        changed = False
        try:
            current_ver = int(cfg.get("config_version", 0) or 0)
        except Exception:
            current_ver = 0
            changed = True
        if current_ver < self.CONFIG_VERSION:
            changed = True

        if "release_mode" not in cfg:
            cfg["release_mode"] = False
            changed = True

        valid_profiles = {"normal", "debug", "quiet"}
        has_profile = "log_profile" in cfg
        profile = str(cfg.get("log_profile", "normal") or "normal").strip().lower()
        if profile not in valid_profiles:
            profile = "normal"
            changed = True
        if bool(cfg.get("release_mode", False)) and not has_profile:
            profile = "quiet"
            changed = True
        cfg["log_profile"] = profile

        cfg["config_version"] = self.CONFIG_VERSION
        return cfg, changed

    def save_user_config(self):
        self.user_config["config_version"] = self.CONFIG_VERSION
        self.user_config["release_mode"] = bool(getattr(self, "release_mode_enabled", False))
        self.user_config["language"] = self.language_preference
        self.user_config["theme"] = self.theme_preference
        self.user_config["power_mode"] = self.power_mode_preference
        self.user_config["advanced_details"] = bool(getattr(self, "advanced_details_enabled", True))
        self.user_config["safe_mode"] = bool(getattr(self, "safe_mode_enabled", False))
        self.user_config["safe_mode_auto"] = bool(getattr(self, "safe_mode_auto", True))
        self.user_config["log_profile"] = str(getattr(self, "log_profile", "normal") or "normal")
        self.user_config["poll_interval_ms"] = int(getattr(self, "poll_interval_ms", 120))
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.user_config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            if hasattr(self, "console_logic") and self.console_logic:
                self.console_logic.log(f"Config save error: {e}", "WARN")

    def build_compatibility_report(self):
        runtime_link_failures = dict(getattr(self.h1, "link_failures", {}))
        merged_failures = dict(self.build_failures)
        for engine_name, reason in runtime_link_failures.items():
            if engine_name not in merged_failures:
                merged_failures[engine_name] = reason
        optional = dict((k, v) for k, v in merged_failures.items() if k in self.OPTIONAL_ENGINES)
        required = dict((k, v) for k, v in merged_failures.items() if k not in self.OPTIONAL_ENGINES)
        return {
            "runtime": collect_runtime_compat(),
            "config": {
                "config_version": self.CONFIG_VERSION,
                "release_mode": self.release_mode_enabled,
                "language": self.language_preference,
                "theme": self.theme_preference,
                "power_mode": self.power_mode_preference,
                "safe_mode": self.safe_mode_enabled,
                "safe_mode_auto": self.safe_mode_auto,
                "log_profile": self.log_profile,
                "poll_interval_ms": self.poll_interval_ms,
                "advanced_details": self.advanced_details_enabled,
            },
            "engines": {
                "loaded": sorted(getattr(self.h1, "loaded_engines", {}).keys()),
                "active": sorted(getattr(self.h2.worker, "active_engines", [])),
            },
            "locks": dict(getattr(self, "metric_locks", {})),
            "smoke": dict(getattr(self, "smoke_report", {})),
            "build_failures": {
                "count": len(merged_failures),
                "required_count": len(required),
                "optional_count": len(optional),
                "required": required,
                "optional": optional,
                "engines": merged_failures,
            },
        }

    def _detect_system_power_profile(self):
        if os.path.isdir("/sys/class/power_supply"):
            try:
                for name in os.listdir("/sys/class/power_supply"):
                    if str(name).startswith("BAT"):
                        return "laptop"
            except Exception:
                pass
        return "desktop"

    def get_power_mode_resolved(self):
        if self.power_mode_preference == "auto":
            return self.system_power_profile
        return self.power_mode_preference

    def _infer_power_profile_from_psu(self, psu_all):
        if isinstance(psu_all, dict):
            if bool(psu_all.get("has_battery", False)):
                return "laptop"
            src = str(psu_all.get("source") or "").strip().lower()
            if src == "battery":
                return "laptop"
        return self._detect_system_power_profile()

    def _update_auto_power_profile(self, psu_all=None):
        if self.power_mode_preference != "auto":
            return
        old = self.system_power_profile
        new = self._infer_power_profile_from_psu(psu_all)
        if new not in ("desktop", "laptop"):
            return
        if new == old:
            return
        self.system_power_profile = new
        self.console_logic.log(
            f"Auto power profile changed: {old} -> {new}",
            "INFO",
        )
        if "psu" in self.metric_cards:
            self._set_card_subtitle("psu", self._metric_card_subtitle("psu"))
        if self.selected_metric in self.metric_cards:
            self._set_primary_subtitle(self._metric_device_info(self.selected_metric))
            self._refresh_primary_info(self.selected_metric)

    def run_startup_smoke_check(self):
        required = ("cpu", "ram", "disc")
        missing = [e for e in required if e not in self.h1.loaded_engines]
        smoke = {"required_missing": list(missing), "probes": {}, "status": "ok"}
        if missing:
            self.console_logic.log(
                f"Smoke check: Missing required engines: {', '.join(missing)}",
                "WARN",
            )
            smoke["status"] = "warn"
        else:
            self.console_logic.log("Smoke check: core engines OK.", "SUCCESS")

        # Quick probe to surface runtime issues early.
        probes = {
            "cpu": "get_usage",
            "ram": "get_usage",
            "disc": "get_all_usage",
        }
        for engine, method in probes.items():
            if engine not in self.h1.loaded_engines:
                smoke["probes"][f"{engine}.{method}"] = "missing_engine"
                continue
            val = self.h1.invoke_method(engine, method)
            if val is None:
                self.console_logic.log(f"Smoke check: {engine}.{method} returned None", "WARN")
                smoke["probes"][f"{engine}.{method}"] = "warn_none"
                smoke["status"] = "warn"
            else:
                self.console_logic.log(f"Smoke check: {engine}.{method} OK", "INFO")
                smoke["probes"][f"{engine}.{method}"] = "ok"
        self.smoke_report = smoke

    def _apply_safe_mode_runtime(self):
        if self.poll_interval_ms < 250:
            self.poll_interval_ms = 250
        self.dynamic_metric_missing_hide_s = 8.0
        self.dynamic_metric_idle_hide_s = 30.0
        self.dynamic_rebuild_interval_s = 1.5

    def _apply_auto_safe_mode_if_needed(self):
        if not self.safe_mode_auto or self.safe_mode_enabled:
            return
        try:
            compat = collect_runtime_compat()
        except Exception as e:
            self.console_logic.log(f"Safe mode probe error: {e}", "WARN")
            return

        reasons = []
        loaded = set(getattr(self.h1, "loaded_engines", {}).keys())
        active = set(getattr(self.h2.worker, "active_engines", []))
        core_missing = [e for e in ("cpu", "ram", "disc") if e not in loaded]
        if core_missing:
            reasons.append(f"missing core engines: {', '.join(core_missing)}")
        if len(active) <= 2:
            reasons.append("limited active engines")

        sensors = compat.get("sensors", {})
        if isinstance(sensors, dict):
            if not bool(sensors.get("proc_stat", False)):
                reasons.append("no /proc/stat")
            if not bool(sensors.get("proc_meminfo", False)):
                reasons.append("no /proc/meminfo")

        if not reasons:
            return

        self.safe_mode_enabled = True
        self._apply_safe_mode_runtime()
        self.save_user_config()
        self.console_logic.log(
            f"Auto Safe Mode enabled: {', '.join(reasons)}",
            "WARN",
        )
