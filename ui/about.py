import os
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt


class AboutDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.lang_handler = main_window.lang_handler

        self.setFixedSize(360, 420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setObjectName("AboutDialog")

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(30, 30, 30, 30)
        self.layout.setSpacing(15)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.icon_label)

        self.text_label = QLabel()
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label.setWordWrap(True)
        self.text_label.setOpenExternalLinks(True)
        self.layout.addWidget(self.text_label)

        self.layout.addStretch()

        self.close_btn = QPushButton()
        self.close_btn.setObjectName("primaryButton")
        self.close_btn.setMinimumHeight(35)
        self.close_btn.clicked.connect(self.accept)
        self.layout.addWidget(self.close_btn)

        self._load_icon()
        self.retranslate_ui()

    def _load_icon(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        icon_path = os.path.join(base_dir, "assets", "icons", "about_lxico.png")
        if not os.path.exists(icon_path):
            self.icon_label.hide()
            return
        pixmap = QPixmap(icon_path)
        if pixmap.isNull():
            self.icon_label.hide()
            return
        self.icon_label.setPixmap(
            pixmap.scaled(
                90,
                90,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.icon_label.show()

    def retranslate_ui(self):
        tr = self.lang_handler.tr
        self.setWindowTitle(tr("about_title"))
        self.close_btn.setText(tr("btn_close"))

        is_dark = getattr(self.main_window.theme_manager, "current_theme", "dark") == "dark"
        accent_color = "#569cd6" if is_dark else "#005a9e"
        secondary_text = "#888888" if is_dark else "#555555"
        border_color = "#444444" if is_dark else "#dddddd"

        about_html = (
            f"<div style='text-align: center;'>"
            f"  <span style='font-size: 22px; font-weight: bold;'>LxMonitor</span><br>"
            f"  <span style='color: {secondary_text};'>{tr('about_description')}</span>"
            f"  <br><br>"
            f"  <div style='font-size: 13px;'>"
            f"    {tr('about_version')}: <b style='color: {accent_color};'>{tr('about_value_version')}</b><br>"
            f"    {tr('about_created_by')}: <b>{tr('about_value_author')}</b>"
            f"  </div>"
            f"  <br>"
            f"  <hr style='border: 0; border-top: 1px solid {border_color};'>"
            f"  <div style='margin-top: 10px; font-size: 10px; color: {secondary_text};'>"
            f"    {tr('icons_source')}"
            f"  </div>"
            f"</div>"
        )
        self.text_label.setText(about_html)
