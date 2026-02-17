from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QSpacerItem, QSizePolicy
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon
import os

class MainToolbar(QWidget):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setObjectName("MainToolbar")
        
        self.setup_ui()

    def setup_ui(self):
        # HBoxLayout dla paska narzędzi
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(10, 5, 10, 5)
        self.layout.setSpacing(10)

        # 1. Przycisk Ustawień
        self.settings_btn = QPushButton()
        self.settings_btn.setObjectName("toolbarButton")
        self.settings_btn.clicked.connect(self.main_window.show_settings)
        self.layout.addWidget(self.settings_btn)

        # Spacer wypychający resztę na prawo
        self.layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        # 2. Przycisk Info (wywołuje Twoje InfoMenu/About)
        self.info_btn = QPushButton()
        self.info_btn.setObjectName("toolbarButton")
        self.info_btn.clicked.connect(self.main_window.show_about_dialog)
        self.layout.addWidget(self.info_btn)

        self.update_icons()
        self.retranslate_ui()

    def update_icons(self):
        """Ładuje ikony z assets/icons/"""
        # Ustalanie ścieżki (wychodzimy z ui/ do głównego folderu)
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../"))
        icon_dir = os.path.join(base_path, "assets", "icons")

        def set_icon(btn, name):
            path = os.path.join(icon_dir, name)
            if os.path.exists(path):
                btn.setIcon(QIcon(path))
                btn.setIconSize(QSize(24, 24))

        set_icon(self.settings_btn, "settings.png")
        set_icon(self.info_btn, "info.png")

    def retranslate_ui(self):
        tr = self.main_window.lang_handler.tr
        self.settings_btn.setText(tr("toolbar_settings"))
        self.info_btn.setText(tr("toolbar_info"))
        self.settings_btn.setToolTip(tr("tooltip_settings"))
        self.info_btn.setToolTip(tr("tooltip_info"))
