# pyright: reportAttributeAccessIssue=false
import os


class EnginePrivilegedMixin:
    def _is_any_readable(self, paths):
        for p in paths:
            if os.path.exists(p) and os.access(p, os.R_OK):
                return True
        return False

    def _is_cpu_temp_readable(self):
        candidates = []
        # hwmon
        base = "/sys/class/hwmon"
        if os.path.isdir(base):
            try:
                for hw in os.listdir(base):
                    d = os.path.join(base, hw)
                    if not os.path.isdir(d):
                        continue
                    try:
                        for fn in os.listdir(d):
                            if fn.startswith("temp") and fn.endswith("_input"):
                                candidates.append(os.path.join(d, fn))
                    except Exception:
                        continue
            except Exception:
                pass
        # thermal zones
        tbase = "/sys/class/thermal"
        if os.path.isdir(tbase):
            try:
                for name in os.listdir(tbase):
                    if name.startswith("thermal_zone"):
                        candidates.append(os.path.join(tbase, name, "temp"))
            except Exception:
                pass
        return self._is_any_readable(candidates)

    def _ensure_privilege_engine(self):
        if "privilege" in self.h1.loaded_engines:
            return True
        return self.h1.link_engine("privilege")

    def _privilege_backend(self):
        if not self._ensure_privilege_engine():
            return "none"
        backend = self.h1.invoke_method("privilege", "detect_backend")
        return str(backend or "none")

    def _privilege_verify(self, password):
        if not self._ensure_privilege_engine():
            return {"ok": False, "error": "Brak silnika privilege.so"}
        res = self.h1.invoke_method("privilege", "verify", password or "")
        if isinstance(res, dict):
            return res
        return {"ok": False, "error": "Błąd odpowiedzi silnika privilege.verify"}

    def _prepare_system_access(self, password):
        if not self._ensure_privilege_engine():
            self.console_logic.log("Brak silnika privilege.so", "WARN")
            return False
        res = self.h1.invoke_method("privilege", "prepare_access", password or "")
        if not isinstance(res, dict):
            self.console_logic.log("Błąd odpowiedzi silnika privilege.prepare_access", "WARN")
            return False
        ok = bool(res.get("ok"))
        if not ok:
            self.console_logic.log(f"Privileged setup warning: {res.get('error', '')}", "WARN")
        return ok

    def get_unlock_status_text(self):
        tr = self.lang_handler.tr
        if getattr(self, "_auth_verified_this_session", False):
            return tr("unlock_session_active")
        return tr("unlock_session_inactive")

    def check_privileges(self):
        tr = self.lang_handler.tr
        backend = self._privilege_backend()
        if backend == "none":
            msg = tr("unlock_no_priv_tool")
            self.console_logic.log(msg, "WARN")
            return False, msg

        verify = self._privilege_verify("")
        if bool(verify.get("ok")):
            self._auth_verified_this_session = True
            msg = tr("unlock_check_ok")
            self.console_logic.log(msg, "SUCCESS")
            return True, msg

        err = str(verify.get("error", "") or "").lower()
        if "required" in err or "wymagane jest hasło" in err or "password" in err:
            msg = tr("unlock_check_password_needed")
            self.console_logic.log(msg, "INFO")
            return False, msg
        if "sudoers" in err:
            msg = tr("unlock_no_sudoers")
            self.console_logic.log(msg, "WARN")
            return False, msg

        short = str(verify.get("error", "") or "").splitlines()[0][:120]
        msg = tr("unlock_priv_error").format(error=short if short else "unknown")
        self.console_logic.log(msg, "WARN")
        return False, msg

    def _try_activate_metric_engine(self, metric):
        if metric == "gpu":
            is_nvidia_hw = os.path.exists("/proc/driver/nvidia/version") or os.path.exists("/dev/nvidia0")
            gpu_nvidia_so = os.path.join(self.h1.engines_dir, "gpu_nvidia.so")
            if is_nvidia_hw and os.path.exists(gpu_nvidia_so):
                candidates = ["gpu_nvidia", "gpu_others"]
            else:
                candidates = ["gpu_others"]
        elif metric == "gpu_temp":
            candidates = ["gpu_temp"]
        else:
            candidates = []

        for engine in candidates:
            if engine in self.h1.loaded_engines or self.h1.link_engine(engine):
                if engine not in self.h2.worker.active_engines:
                    self.h2.worker.active_engines.append(engine)
                return True
        return False

    def unlock_protected_metrics(self, password):
        password = (password or "").strip()
        backend = self._privilege_backend()
        requires_local_password = backend in ("local_sudo", "host_sudo")
        session_auth = bool(getattr(self, "_auth_verified_this_session", False))
        if requires_local_password and not password and not session_auth:
            msg = self.lang_handler.tr("unlock_enter_password")
            self.console_logic.log(msg, "WARN")
            return False, msg

        self.console_logic.log(self.lang_handler.tr("unlock_checking_permissions"), "INFO")
        verify = self._privilege_verify(password)
        ok = bool(verify.get("ok"))
        err = str(verify.get("error", "") or "")
        if not ok and requires_local_password and session_auth and not password:
            # Session token likely expired; ask user for password again.
            self._auth_verified_this_session = False
            msg = self.lang_handler.tr("unlock_enter_password")
            self.console_logic.log("Cached sudo session expired.", "WARN")
            self.console_logic.log(msg, "WARN")
            return False, msg
        if not ok:
            err_l = err.lower()
            if "not in the sudoers" in err_l:
                msg = self.lang_handler.tr("unlock_no_sudoers")
            elif "terminal is required" in err_l or "tty" in err_l:
                msg = self.lang_handler.tr("unlock_tty_required")
            elif "command not found" in err_l or "no such file" in err_l or "brak narzędzia" in err_l:
                msg = self.lang_handler.tr("unlock_no_priv_tool")
            elif "authentication failed" in err_l or "wrong password" in err_l:
                msg = self.lang_handler.tr("unlock_wrong_password")
            elif "cancelled" in err_l or "anulowano" in err_l:
                msg = self.lang_handler.tr("unlock_auth_cancelled")
            else:
                short_err = (err or "brak szczegółów").splitlines()[0][:90]
                msg = self.lang_handler.tr("unlock_priv_error").format(error=short_err)
            self.console_logic.log(f"Unlock failed: {err or 'privileged command failed'}", "WARN")
            self.console_logic.log(msg, "WARN")
            return False, msg

        if requires_local_password:
            self._auth_verified_this_session = True
        self.console_logic.log(self.lang_handler.tr("unlock_password_ok_configuring"), "INFO")
        self._prepare_system_access(password)

        gpu_ok = self._try_activate_metric_engine("gpu")
        gpu_temp_ok = self._try_activate_metric_engine("gpu_temp")

        self.metric_locks["gpu"] = not gpu_ok
        self.metric_locks["cpu_temp"] = not self._is_cpu_temp_readable()
        self.metric_locks["gpu_temp"] = not gpu_temp_ok
        self.refresh_blocked_graphs()

        if self.h2.worker.active_engines and not self.h2.refresh_timer.isActive():
            self.h2.start(self.poll_interval_ms)

        if gpu_ok and gpu_temp_ok:
            msg = self.lang_handler.tr("unlock_success_log")
            self.console_logic.log(msg, "SUCCESS")
            return True, msg
        if gpu_ok and not gpu_temp_ok:
            msg = self.lang_handler.tr("unlock_partial_gpu_only")
            self.console_logic.log(msg, "WARN")
            return False, msg
        msg = self.lang_handler.tr("unlock_engine_unavailable")
        self.console_logic.log(msg, "WARN")
        return False, msg

    def setup_engine_connections(self):
        engines_to_link = self.h1.auto_discover_hardware()
        active_engines = []

        fallback_map = {
            "gpu_nvidia": ["gpu_others"],
        }

        for engine in engines_to_link:
            if self.h1.link_engine(engine):
                active_engines.append(engine)
                continue

            for fallback in fallback_map.get(engine, []):
                if fallback in active_engines:
                    break
                if self.h1.link_engine(fallback):
                    active_engines.append(fallback)
                    self.console_logic.log(
                        f"Engine fallback active: '{engine}' -> '{fallback}'",
                        "WARN",
                    )
                    break

        self.h2.setup_monitoring(active_engines)
        self.h2.bind_to_dashboard(self.update_widgets)
        if active_engines:
            self._auto_unlock_metrics_if_readable()
        else:
            self.console_logic.log("Critical: No hardware engines linked! Using Python fallback collectors.", "ERROR")

    def _auto_unlock_metrics_if_readable(self):
        # If metric reads work without privilege escalation, keep it unlocked.
        gpu_ok = False
        for eng in ("gpu_nvidia", "gpu_others"):
            if eng in self.h1.loaded_engines:
                val = self.h1.invoke_method(eng, "get_usage")
                if val is not None:
                    gpu_ok = True
                    break
        if gpu_ok:
            self.metric_locks["gpu"] = False

        if self._is_cpu_temp_readable():
            self.metric_locks["cpu_temp"] = False

        if "gpu_temp" in self.h1.loaded_engines:
            val = self.h1.invoke_method("gpu_temp", "get_usage")
            if val is not None and float(val) > 0.0:
                self.metric_locks["gpu_temp"] = False

    def show_locked_metrics_warning(self):
        tr = self.lang_handler.tr
        msg = tr("startup_locked_warning")
        if self.metric_locks.get("gpu", False) or self.metric_locks.get("gpu_temp", False):
            self.console_logic.log(msg, "WARN")

    def refresh_blocked_graphs(self):
        blocked_msg = self.lang_handler.tr("graph_blocked_no_permissions")
        na_msg = self.lang_handler.tr("value_na")
        for metric_name, parts in self.metric_cards.items():
            locked = self._metric_locked(metric_name)
            parts["spark"].set_blocked(locked, blocked_msg)
            if locked:
                parts["value"].setText(blocked_msg)
            elif not parts.get("seen", False):
                parts["value"].setText(na_msg)
        self.primary_graph.set_blocked(self._metric_locked(self.selected_metric), blocked_msg)
