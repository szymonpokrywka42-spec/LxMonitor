import os
import sys
import importlib
import glob
from typing import Set

class CppHandler1:
    def __init__(self, console_logic=None):
        self.console = console_logic
        # Uwzględniamy strukturę: core/handlers/cpp_handler1.py -> wychodzimy do core/
        self.core_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_dir = os.path.dirname(self.core_dir)
        self.engines_dir = os.path.join(self.core_dir, "engines")
        self.lxbinman_dir = os.path.join(self.project_dir, "LxBinMan")
        
        self.loaded_engines = {}
        self.link_failures = {}
        self._hotfix_attempted: Set[str] = set()
        
        # Rejestracja ścieżki w sys.path dla importów .so
        if self.engines_dir not in sys.path:
            sys.path.append(self.engines_dir)
        if os.path.isdir(self.lxbinman_dir) and self.lxbinman_dir not in sys.path:
            sys.path.insert(0, self.lxbinman_dir)
            
        self._log("CppHandler1: Discovery & Linker module online.", "BOOT")

    def _is_readable(self, path):
        return os.path.exists(path) and os.access(path, os.R_OK)

    def _engine_binary_exists(self, engine_name):
        return os.path.exists(os.path.join(self.engines_dir, f"{engine_name}.so"))

    def _append_engine_if_available(self, to_load, engine_name, reason, missing_level="WARN"):
        if self._engine_binary_exists(engine_name):
            to_load.append(engine_name)
            self._log(reason, "INFO")
            return True
        self._log(f"Engine binary missing: {engine_name}.so ({reason}). Using fallback collectors.", missing_level)
        return False

    def _looks_recoverable_link_error(self, error_text):
        t = (error_text or "").lower()
        markers = (
            "python version mismatch",
            "undefined symbol",
            "wrong elf class",
            "invalid elf header",
            "cannot open shared object file",
            "file too short",
        )
        return any(m in t for m in markers)

    def _run_self_hotfix_build(self, engine_name, reason):
        if engine_name in self._hotfix_attempted:
            return False
        self._hotfix_attempted.add(engine_name)
        self._log(
            f"Self-hotfix: attempting rebuild for '{engine_name}' ({reason}).",
            "WARN",
        )
        try:
            from lxbinman import builder as binman_builder

            result = binman_builder.build_all(
                source_dir=self.engines_dir,
                output_dir=self.engines_dir,
                compile_only=True,
                policy="prefer_cache",
            )
            ready = self._engine_binary_exists(engine_name)
            expected = len(glob.glob(os.path.join(self.engines_dir, "*.cpp")))
            built = len(result) if isinstance(result, dict) else 0
            self._log(
                f"Self-hotfix build status: ready={ready}, engines_ready={built}/{expected}",
                "INFO",
            )
            return ready
        except Exception as e:
            self._log(f"Self-hotfix build error: {e}", "ERROR")
            return False

    def _link_engine_once(self, engine_name):
        so_file = os.path.join(self.engines_dir, f"{engine_name}.so")
        if not os.path.exists(so_file):
            self.link_failures[engine_name] = "binary not found"
            self._log(f"Linker: Binary '{engine_name}.so' not found in engines directory.", "ERROR")
            return False

        if engine_name in sys.modules:
            module = importlib.reload(sys.modules[engine_name])
        else:
            module = importlib.import_module(engine_name)
        self.loaded_engines[engine_name] = module
        if engine_name in self.link_failures:
            self.link_failures.pop(engine_name, None)
        return True

    def _log(self, message, level="SYSTEM"):
        """Wysyła logi do konsoli UI lub na terminal."""
        if self.console:
            self.console.log(message, level)
        else:
            print(f"[{level}] {message}")

    def auto_discover_hardware(self):
        """
        Skanuje system w poszukiwaniu ścieżek sprzętowych.
        Loguje każdy znaleziony (lub brakujący) komponent.
        """
        self._log("Starting hardware auto-discovery...", "DEBUG")
        to_load = []
        # Core engines first; if missing we still run Python fallbacks from worker.
        self._append_engine_if_available(to_load, "cpu", "Hardware: CPU collector ready.")
        self._append_engine_if_available(to_load, "ram", "Hardware: RAM collector ready.")
        self._append_engine_if_available(to_load, "disc", "Hardware: Disk collector ready.")
        
        # 1. Detekcja GPU
        is_nvidia = os.path.exists("/proc/driver/nvidia/version") or os.path.exists("/dev/nvidia0")

        if is_nvidia:
            if self._append_engine_if_available(
                to_load,
                "gpu_nvidia",
                "Hardware: NVIDIA GPU detected. Selected 'gpu_nvidia' engine.",
            ):
                pass
            else:
                self._log("GPU: NVIDIA detected but engine binary missing. Falling back to generic GPU paths.", "WARN")
                if os.path.exists("/sys/class/drm/card0"):
                    self._append_engine_if_available(
                        to_load,
                        "gpu_others",
                        "Hardware: Generic GPU (AMD/Intel) path found via DRM card0.",
                    )
        else:
            # Fallback na AMD/Intel
            gpu_candidates = [
                "/sys/class/drm/card0/device/gpu_busy_percent",
                "/sys/class/drm/card1/device/gpu_busy_percent",
                "/sys/class/drm/card0/device/usage",
            ]
            has_gpu_usage = any(self._is_readable(p) for p in gpu_candidates)
            if has_gpu_usage or os.path.exists("/sys/class/drm/card0"):
                self._append_engine_if_available(
                    to_load,
                    "gpu_others",
                    "Hardware: Generic GPU (AMD/Intel) found via DRM card0.",
                )
            else:
                self._log("Hardware: No supported GPU interface found.", "WARN")

        # 2. GPU Temperature
        gpu_temp_candidates = glob.glob("/sys/class/drm/card*/device/hwmon/hwmon*/temp*_input")
        gpu_temp_candidates += glob.glob("/sys/class/hwmon/hwmon*/temp*_input")
        if any(self._is_readable(p) for p in gpu_temp_candidates):
            self._append_engine_if_available(to_load, "gpu_temp", "Hardware: GPU temperature sensor found.")
        else:
            self._log("Hardware: GPU temperature sensor not readable.", "WARN")

        # 3. Network interfaces
        if self._is_readable("/proc/net/dev"):
            self._append_engine_if_available(to_load, "net", "Hardware: Network interfaces detected.")
        else:
            self._log("Hardware: /proc/net/dev not readable.", "WARN")

        # 4. Bluetooth adapters
        if os.path.isdir("/sys/class/bluetooth"):
            self._append_engine_if_available(to_load, "bt", "Hardware: Bluetooth adapters detected.")

        # 5. Power telemetry (component + battery/AC when available)
        has_psu_paths = (
            os.path.isdir("/sys/class/power_supply")
            or os.path.isdir("/sys/class/powercap")
            or os.path.isdir("/sys/class/hwmon")
        )
        if has_psu_paths:
            self._append_engine_if_available(to_load, "psu", "Hardware: Power telemetry paths detected.")

        if to_load:
            self._log(f"Discovery complete. Target engines: {', '.join(to_load)}", "SUCCESS")
        else:
            self._log("Discovery complete: no C++ engines ready, Python fallback collectors only.", "WARN")
        return to_load

    def link_engine(self, engine_name):
        """Ładuje skompilowaną binarkę C++ i rejestruje ją w systemie."""
        try:
            if not self._link_engine_once(engine_name):
                return False
            self._log(f"Linked engine: {engine_name} [OK]", "SUCCESS")
            return True

        except Exception as e:
            err = str(e)
            self.link_failures[engine_name] = err
            self._log(f"Linker: Critical error loading '{engine_name}': {err}", "ERROR")
            if self._looks_recoverable_link_error(err):
                if self._run_self_hotfix_build(engine_name, err):
                    try:
                        if self._link_engine_once(engine_name):
                            self._log(f"Self-hotfix success: linked '{engine_name}' after rebuild.", "SUCCESS")
                            self.link_failures.pop(engine_name, None)
                            return True
                    except Exception as e2:
                        self.link_failures[engine_name] = str(e2)
                        self._log(f"Self-hotfix link retry failed for '{engine_name}': {e2}", "ERROR")
            return False

    def invoke_method(self, engine_name, method_name, *args):
        """Bezpieczne wywołanie metody C++ z raportowaniem błędów."""
        engine = self.loaded_engines.get(engine_name)
        if engine is None and self._engine_binary_exists(engine_name):
            # Lazy self-heal: try to relink missing module on first access.
            self.link_engine(engine_name)
            engine = self.loaded_engines.get(engine_name)
        if engine and hasattr(engine, method_name):
            try:
                method = getattr(engine, method_name)
                return method(*args)
            except Exception as e:
                self._log(f"Runtime: Error in {engine_name}::{method_name}() -> {str(e)}", "ERROR")
                return None
        return None
