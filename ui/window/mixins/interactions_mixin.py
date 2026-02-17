# pyright: reportAttributeAccessIssue=false
import datetime
import json
import os
import platform

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QMainWindow

from ui.about import AboutDialog
from ui.settings import SettingsDialog


class InteractionsMixin:
    def show_about_dialog(self):
        self.console_logic.log(self.lang_handler.tr("about_opening"), "INFO")
        self.about_window = AboutDialog(self)
        self.about_window.exec()

    def show_settings(self):
        self.console_logic.log(self.lang_handler.tr("settings_opened"), "INFO")
        dialog = SettingsDialog(self)
        dialog.exec()

    def change_theme(self):
        self.theme_manager.apply_theme("dark")

    def toggle_console(self):
        if self.console_dialog.isVisible():
            self.console_logic.log("UI: Console hidden.", "INFO")
            self.console_dialog.hide()
        else:
            self.console_logic.log("UI: Console shown.", "INFO")
            self.console_dialog.show()
            self.console_dialog.input.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F12:
            self.toggle_console()
            return
        if event.key() == Qt.Key.Key_F11:
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()
            return
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.showNormal()
            return
        try:
            super().keyPressEvent(event)
        except AttributeError:
            QMainWindow.keyPressEvent(self, event)

    def set_language(self, lang_code):
        if not self.lang_handler.set_language(lang_code):
            return
        self.language_preference = (lang_code or "system").lower()
        self.save_user_config()
        self.retranslate_ui()
        if hasattr(self, "console_dialog") and self.console_dialog:
            self.console_dialog.retranslate_ui()
        lang_label = self.lang_handler.get_language_display_name(self.language_preference)
        self.console_logic.log(self.lang_handler.tr("settings_saved").format(lang=lang_label), "SUCCESS")

    def set_theme(self, theme_code):
        mode = (theme_code or "system").lower()
        if mode not in ("system", "dark", "light"):
            mode = "system"
        self.theme_preference = mode
        self.theme_manager.apply_theme(mode)
        self.apply_theme_overrides()
        if hasattr(self, "console_dialog") and self.console_dialog:
            self.console_dialog.refresh_theme_colors()
        if hasattr(self, "about_window") and self.about_window and self.about_window.isVisible():
            self.about_window.retranslate_ui()
        self.save_user_config()
        msg = self.lang_handler.tr("theme_changed").format(theme=self.lang_handler.tr(f"theme_{mode}"))
        self.console_logic.log(msg, "SUCCESS")

    def set_power_mode(self, mode_code):
        mode = (mode_code or "auto").lower()
        if mode not in ("auto", "desktop", "laptop"):
            mode = "auto"
        self.power_mode_preference = mode
        self.save_user_config()
        if self.selected_metric in self.metric_cards:
            self._refresh_primary_info(self.selected_metric)
            self._set_card_subtitle("psu", self._metric_card_subtitle("psu"))
        resolved = self.get_power_mode_resolved() if hasattr(self, "get_power_mode_resolved") else mode
        msg = self.lang_handler.tr("power_mode_changed").format(
            mode=self.lang_handler.tr(f"power_mode_{mode}"),
            resolved=self.lang_handler.tr(f"power_mode_{resolved}"),
        )
        self.console_logic.log(msg, "INFO")

    def set_advanced_details(self, enabled):
        self.advanced_details_enabled = bool(enabled)
        self.save_user_config()
        if self.selected_metric in self.metric_cards:
            self._refresh_primary_info(self.selected_metric)
        msg = self.lang_handler.tr("settings_advanced_details_changed").format(
            state=self.lang_handler.tr("settings_state_on") if self.advanced_details_enabled else self.lang_handler.tr("settings_state_off")
        )
        self.console_logic.log(msg, "INFO")

    def set_safe_mode(self, enabled):
        self.safe_mode_enabled = bool(enabled)
        if self.safe_mode_enabled and self.poll_interval_ms < 250:
            self.poll_interval_ms = 250
        self.dynamic_metric_missing_hide_s = 8.0 if self.safe_mode_enabled else 6.0
        self.dynamic_metric_idle_hide_s = 30.0 if self.safe_mode_enabled else 20.0
        self.dynamic_rebuild_interval_s = 1.5 if self.safe_mode_enabled else 1.0
        if hasattr(self, "h2") and self.h2:
            self.h2.start(self.poll_interval_ms)
        self.save_user_config()
        state = self.lang_handler.tr("settings_state_on") if self.safe_mode_enabled else self.lang_handler.tr("settings_state_off")
        self.console_logic.log(self.lang_handler.tr("settings_safe_mode_changed").format(state=state), "INFO")

    def set_poll_interval(self, interval_ms):
        try:
            ms = int(interval_ms)
        except Exception:
            ms = 120
        ms = max(80, min(3000, ms))
        if self.safe_mode_enabled and ms < 250:
            ms = 250
        self.poll_interval_ms = ms
        if hasattr(self, "h2") and self.h2:
            self.h2.start(self.poll_interval_ms)
        self.save_user_config()
        self.console_logic.log(self.lang_handler.tr("settings_poll_interval_changed").format(ms=self.poll_interval_ms), "INFO")

    def set_log_profile(self, profile_code):
        profile = str(profile_code or "normal").strip().lower()
        if profile not in ("normal", "debug", "quiet"):
            profile = "normal"
        self.log_profile = profile
        if hasattr(self, "console_logic") and self.console_logic:
            self.console_logic.set_log_profile(profile)
        self.save_user_config()
        self.console_logic.log(
            self.lang_handler.tr("settings_log_profile_changed").format(
                profile=self.lang_handler.tr(f"settings_log_profile_{profile}")
            ),
            "INFO",
        )

    def export_compatibility_report(self):
        report = self.build_compatibility_report()
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        default_name = f"lxmonitor-compat-{ts}.json"
        start_dir = os.path.dirname(getattr(self, "config_path", "")) or os.getcwd()
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.lang_handler.tr("settings_export_compat"),
            os.path.join(start_dir, default_name),
            "JSON (*.json)",
        )
        if not path:
            return self.lang_handler.tr("settings_export_cancelled")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            msg = self.lang_handler.tr("settings_export_done").format(path=path)
            self.console_logic.log(msg, "SUCCESS")
            return msg
        except Exception as e:
            msg = self.lang_handler.tr("settings_export_failed").format(error=str(e))
            self.console_logic.log(msg, "ERROR")
            return msg

    def build_diagnostic_report(self):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        backend = self._privilege_backend() if hasattr(self, "_privilege_backend") else "n/a"
        loaded = sorted(getattr(self.h1, "loaded_engines", {}).keys())
        active = sorted(getattr(self.h2.worker, "active_engines", []))

        lines = [
            "LxMonitor Diagnostic Report",
            f"Generated: {now}",
            f"Platform: {platform.platform()}",
            f"Language: {self.lang_handler.current_lang}",
            f"Power mode: {getattr(self, 'power_mode_preference', 'auto')} (resolved: {self.get_power_mode_resolved() if hasattr(self, 'get_power_mode_resolved') else 'n/a'})",
            f"Poll interval: {self.poll_interval_ms} ms",
            f"Privilege backend: {backend}",
            f"Unlock session: {'active' if getattr(self, '_auth_verified_this_session', False) else 'inactive'}",
            f"Loaded engines: {', '.join(loaded) if loaded else 'none'}",
            f"Active engines: {', '.join(active) if active else 'none'}",
            f"Metric locks: {self.metric_locks}",
            f"Dynamic cards: {len([m for m in self.metric_cards if m.startswith(('disk:', 'net:', 'gpu:'))])}",
            f"CPU: {self.cpu_name}",
            f"GPU: {self.gpu_name}",
            "",
            "Latest sensors:",
        ]

        for k in sorted(self.latest_sensor_values.keys()):
            lines.append(f"- {k}: {self.latest_sensor_values.get(k)}")

        lines.append("")
        lines.append("Recent logs:")
        for msg in self.console_logic.history[-50:]:
            lines.append(msg)

        return "\n".join(lines)

    def copy_diagnostic_report(self):
        report = self.build_diagnostic_report()
        QApplication.clipboard().setText(report)
        msg = self.lang_handler.tr("diagnostics_copied")
        self.console_logic.log(msg, "SUCCESS")
        return msg

    def retranslate_ui(self):
        tr = self.lang_handler.tr
        self.setWindowTitle(tr("window_title"))
        self.page_title.setText(tr("performance_title"))

        for metric_name, parts in self.metric_cards.items():
            if metric_name.startswith("disk:"):
                self._set_card_title(metric_name, tr("graph_disk_usage"))
            elif metric_name.startswith("net:"):
                self._set_card_title(metric_name, tr("graph_net_iface"))
            else:
                self._set_card_title(metric_name, tr(parts["title_key"]))
            self._set_card_subtitle(metric_name, self._metric_card_subtitle(metric_name))

        if hasattr(self, "toolbar") and self.toolbar:
            self.toolbar.retranslate_ui()

        self.refresh_blocked_graphs()
        self._select_metric(self.selected_metric)
