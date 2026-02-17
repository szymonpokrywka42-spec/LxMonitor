from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)
from PyQt6.QtCore import Qt


class SettingsDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.lang_handler = main_window.lang_handler

        self.setObjectName("SettingsDialog")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setMinimumWidth(700)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        row = QHBoxLayout()
        self.language_label = QLabel()
        self.language_combo = QComboBox()
        row.addWidget(self.language_label)
        row.addWidget(self.language_combo, 1)
        root.addLayout(row)

        theme_row = QHBoxLayout()
        self.theme_label = QLabel()
        self.theme_combo = QComboBox()
        theme_row.addWidget(self.theme_label)
        theme_row.addWidget(self.theme_combo, 1)
        root.addLayout(theme_row)

        power_mode_row = QHBoxLayout()
        self.power_mode_label = QLabel()
        self.power_mode_combo = QComboBox()
        power_mode_row.addWidget(self.power_mode_label)
        power_mode_row.addWidget(self.power_mode_combo, 1)
        root.addLayout(power_mode_row)

        self.advanced_details_check = QCheckBox()
        root.addWidget(self.advanced_details_check)

        self.safe_mode_check = QCheckBox()
        root.addWidget(self.safe_mode_check)

        log_profile_row = QHBoxLayout()
        self.log_profile_label = QLabel()
        self.log_profile_combo = QComboBox()
        log_profile_row.addWidget(self.log_profile_label)
        log_profile_row.addWidget(self.log_profile_combo, 1)
        root.addLayout(log_profile_row)

        poll_row = QHBoxLayout()
        self.poll_label = QLabel()
        self.poll_combo = QComboBox()
        poll_row.addWidget(self.poll_label)
        poll_row.addWidget(self.poll_combo, 1)
        root.addLayout(poll_row)

        unlock_row = QHBoxLayout()
        self.unlock_label = QLabel()
        self.unlock_password = QLineEdit()
        self.unlock_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.unlock_btn = QPushButton()
        unlock_row.addWidget(self.unlock_label)
        unlock_row.addWidget(self.unlock_password, 1)
        unlock_row.addWidget(self.unlock_btn)
        root.addLayout(unlock_row)

        self.unlock_status = QLabel()
        self.unlock_status.setWordWrap(True)
        root.addWidget(self.unlock_status)

        self.unlock_session_status = QLabel()
        self.unlock_session_status.setWordWrap(True)
        root.addWidget(self.unlock_session_status)

        tools_row = QHBoxLayout()
        self.check_priv_btn = QPushButton()
        self.copy_diag_btn = QPushButton()
        self.export_compat_btn = QPushButton()
        tools_row.addWidget(self.check_priv_btn)
        tools_row.addWidget(self.copy_diag_btn)
        tools_row.addWidget(self.export_compat_btn)
        root.addLayout(tools_row)

        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_btn = QPushButton()
        self.apply_btn = QPushButton()
        actions.addWidget(self.cancel_btn)
        actions.addWidget(self.apply_btn)
        root.addLayout(actions)

        # Prevent Enter key from triggering an extra default-button click.
        for btn in (
            self.unlock_btn,
            self.check_priv_btn,
            self.copy_diag_btn,
            self.export_compat_btn,
            self.cancel_btn,
            self.apply_btn,
        ):
            btn.setAutoDefault(False)
            btn.setDefault(False)

        self.cancel_btn.clicked.connect(self.reject)
        self.apply_btn.clicked.connect(self._apply)
        self.unlock_btn.clicked.connect(self._unlock_metrics)
        self.unlock_password.returnPressed.connect(self._unlock_metrics)
        self.check_priv_btn.clicked.connect(self._check_privileges)
        self.copy_diag_btn.clicked.connect(self._copy_diagnostics)
        self.export_compat_btn.clicked.connect(self._export_compat_report)

        self._load_languages()
        self._load_themes()
        self._load_power_modes()
        self._load_log_profiles()
        self._load_poll_presets()
        self._load_toggles()
        self.retranslate_ui()
        self._fit_dialog_width()

    def _fit_dialog_width(self):
        screen = self.screen()
        if screen is not None:
            available_w = int(screen.availableGeometry().width())
        else:
            available_w = 1920
        target_w = min(max(760, int(self.sizeHint().width()) + 40), max(700, available_w - 120))
        self.resize(target_w, max(self.height(), self.sizeHint().height()))

    def _load_languages(self):
        self.language_combo.clear()
        for code, label in self.lang_handler.get_language_choices():
            self.language_combo.addItem(label, code)
        current = getattr(self.main_window, "language_preference", self.lang_handler.selected_lang)
        idx = self.language_combo.findData(current)
        if idx < 0 and current == "system":
            idx = self.language_combo.findData("system")
        if idx < 0:
            idx = self.language_combo.findData(self.lang_handler.current_lang)
        if idx >= 0:
            self.language_combo.setCurrentIndex(idx)

    def _load_themes(self):
        self.theme_combo.clear()
        self.theme_combo.addItem(self.lang_handler.tr("theme_system"), "system")
        self.theme_combo.addItem(self.lang_handler.tr("theme_dark"), "dark")
        self.theme_combo.addItem(self.lang_handler.tr("theme_light"), "light")
        current = getattr(self.main_window, "theme_preference", "system")
        idx = self.theme_combo.findData(current)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)

    def _load_toggles(self):
        self.advanced_details_check.setChecked(bool(getattr(self.main_window, "advanced_details_enabled", True)))
        self.safe_mode_check.setChecked(bool(getattr(self.main_window, "safe_mode_enabled", False)))

    def _load_log_profiles(self):
        self.log_profile_combo.clear()
        self.log_profile_combo.addItem(self.lang_handler.tr("settings_log_profile_normal"), "normal")
        self.log_profile_combo.addItem(self.lang_handler.tr("settings_log_profile_debug"), "debug")
        self.log_profile_combo.addItem(self.lang_handler.tr("settings_log_profile_quiet"), "quiet")
        current = str(getattr(self.main_window, "log_profile", "normal") or "normal").lower()
        idx = self.log_profile_combo.findData(current)
        if idx < 0:
            idx = self.log_profile_combo.findData("normal")
        if idx >= 0:
            self.log_profile_combo.setCurrentIndex(idx)

    def _load_poll_presets(self):
        self.poll_combo.clear()
        presets = [120, 250, 500, 1000]
        for ms in presets:
            self.poll_combo.addItem(f"{ms} ms", ms)
        current = int(getattr(self.main_window, "poll_interval_ms", 120) or 120)
        idx = self.poll_combo.findData(current)
        if idx < 0:
            self.poll_combo.addItem(f"{current} ms", current)
            idx = self.poll_combo.findData(current)
        if idx >= 0:
            self.poll_combo.setCurrentIndex(idx)

    def _load_power_modes(self):
        self.power_mode_combo.clear()
        self.power_mode_combo.addItem(self.lang_handler.tr("power_mode_auto"), "auto")
        self.power_mode_combo.addItem(self.lang_handler.tr("power_mode_desktop"), "desktop")
        self.power_mode_combo.addItem(self.lang_handler.tr("power_mode_laptop"), "laptop")
        current = getattr(self.main_window, "power_mode_preference", "auto")
        idx = self.power_mode_combo.findData(current)
        if idx >= 0:
            self.power_mode_combo.setCurrentIndex(idx)

    def retranslate_ui(self):
        tr = self.lang_handler.tr
        self.setWindowTitle(tr("settings_title"))
        self.language_label.setText(tr("settings_language_label"))
        self.theme_label.setText(tr("settings_theme_label"))
        self.power_mode_label.setText(tr("settings_power_mode_label"))
        self.advanced_details_check.setText(tr("settings_advanced_details"))
        self.safe_mode_check.setText(tr("settings_safe_mode"))
        self.log_profile_label.setText(tr("settings_log_profile_label"))
        self.poll_label.setText(tr("settings_poll_interval_label"))
        self.unlock_label.setText(tr("settings_unlock_label"))
        self.unlock_password.setPlaceholderText(tr("unlock_password_placeholder"))
        self.unlock_btn.setText(tr("settings_unlock_button"))
        self.unlock_status.setText(tr("settings_unlock_hint"))
        self.unlock_session_status.setText(self.main_window.get_unlock_status_text())
        self.check_priv_btn.setText(tr("settings_check_priv_button"))
        self.copy_diag_btn.setText(tr("settings_copy_diag_button"))
        self.export_compat_btn.setText(tr("settings_export_compat"))
        self.apply_btn.setText(tr("settings_apply"))
        self.cancel_btn.setText(tr("settings_cancel"))

        for i in range(self.language_combo.count()):
            code = self.language_combo.itemData(i)
            self.language_combo.setItemText(i, self.lang_handler.get_language_display_name(code))
        for i in range(self.theme_combo.count()):
            code = self.theme_combo.itemData(i)
            label = {
                "system": tr("theme_system"),
                "dark": tr("theme_dark"),
                "light": tr("theme_light"),
            }.get(code, code)
            self.theme_combo.setItemText(i, label)
        for i in range(self.power_mode_combo.count()):
            code = self.power_mode_combo.itemData(i)
            label = {
                "auto": tr("power_mode_auto"),
                "desktop": tr("power_mode_desktop"),
                "laptop": tr("power_mode_laptop"),
            }.get(code, code)
            self.power_mode_combo.setItemText(i, label)
        for i in range(self.log_profile_combo.count()):
            code = self.log_profile_combo.itemData(i)
            label = {
                "normal": tr("settings_log_profile_normal"),
                "debug": tr("settings_log_profile_debug"),
                "quiet": tr("settings_log_profile_quiet"),
            }.get(code, code)
            self.log_profile_combo.setItemText(i, label)

    def _apply(self):
        lang_code = self.language_combo.currentData()
        theme_code = self.theme_combo.currentData()
        power_mode_code = self.power_mode_combo.currentData()
        if lang_code:
            self.main_window.set_language(lang_code)
        if theme_code:
            self.main_window.set_theme(theme_code)
        if power_mode_code:
            self.main_window.set_power_mode(power_mode_code)
        self.main_window.set_advanced_details(self.advanced_details_check.isChecked())
        self.main_window.set_safe_mode(self.safe_mode_check.isChecked())
        self.main_window.set_log_profile(self.log_profile_combo.currentData())
        self.main_window.set_poll_interval(self.poll_combo.currentData())
        self.retranslate_ui()
        self.accept()

    def _unlock_metrics(self):
        password = self.unlock_password.text()
        if not password and getattr(self.main_window, "_auth_verified_this_session", False):
            msg = self.main_window.get_unlock_status_text()
            self.unlock_status.setText(msg)
            self.unlock_status.setStyleSheet("color: #4ec9b0;")
            self.unlock_session_status.setText(msg)
            return

        ok, msg = self.main_window.unlock_protected_metrics(password)
        self.unlock_status.setText(msg)
        self.unlock_password.clear()
        self.unlock_session_status.setText(self.main_window.get_unlock_status_text())
        if ok:
            self.unlock_status.setStyleSheet("color: #4ec9b0;")
        else:
            self.unlock_status.setStyleSheet("color: #ce9178;")

    def _check_privileges(self):
        ok, msg = self.main_window.check_privileges()
        self.unlock_status.setText(msg)
        self.unlock_session_status.setText(self.main_window.get_unlock_status_text())
        if ok:
            self.unlock_status.setStyleSheet("color: #4ec9b0;")
        else:
            self.unlock_status.setStyleSheet("color: #ce9178;")

    def _copy_diagnostics(self):
        msg = self.main_window.copy_diagnostic_report()
        self.unlock_status.setText(msg)
        self.unlock_status.setStyleSheet("color: #4ec9b0;")

    def _export_compat_report(self):
        msg = self.main_window.export_compatibility_report()
        self.unlock_status.setText(msg)
        if "ERROR" in msg.upper() or "failed" in msg.lower() or "błąd" in msg.lower():
            self.unlock_status.setStyleSheet("color: #ce9178;")
        else:
            self.unlock_status.setStyleSheet("color: #4ec9b0;")
