import os
import subprocess
from PyQt6.QtWidgets import QApplication

class ThemeHandler:
    def __init__(self, main_window=None, console_logic=None):
        self.main_window = main_window
        self.console = console_logic
        self.current_theme = "dark"
        self.current_theme_mode = "system"

        # Ustalenie ścieżki do stylów na podstawie nowej struktury
        # LxMonitor/core/theme_handler.py -> LxMonitor/assets/styles/
        current_file_path = os.path.abspath(__file__)
        base_dir = os.path.dirname(os.path.dirname(current_file_path))
        self.styles_path = os.path.join(base_dir, "assets", "styles")

    def _log(self, message, level="INFO"):
        """Logowanie wykorzystujące Twój nowy system logowania z ConsoleLogic."""
        if self.console:
            self.console.log(message, level)
        else:
            # Jeśli logik jeszcze nie wstał (np. wczesny start main.py)
            print(f"[{level}] {message}")

    def _detect_de(self):
        env = os.environ
        for key in ("XDG_CURRENT_DESKTOP", "DESKTOP_SESSION", "GDMSESSION"):
            val = (env.get(key) or "").lower()
            if val:
                return val
        return ""

    def _detect_system_theme(self):
        de = self._detect_de()

        # KDE/Plasma
        kde_globals = os.path.expanduser("~/.config/kdeglobals")
        if ("kde" in de or "plasma" in de) and os.path.exists(kde_globals):
            try:
                with open(kde_globals, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read().lower()
                if "colorscheme=breeze dark" in text or "dark" in text:
                    return "dark"
                return "light"
            except Exception:
                pass

        # GNOME/Cinnamon/MATE/Budgie/LXQt via gsettings when available.
        if any(x in de for x in ("gnome", "cinnamon", "mate", "budgie", "pantheon", "xfce", "lxqt")):
            if subprocess.getoutput("command -v gsettings >/dev/null 2>&1; echo $?").strip() == "0":
                checks = [
                    "gsettings get org.gnome.desktop.interface color-scheme",
                    "gsettings get org.gnome.desktop.interface gtk-theme",
                ]
                for cmd in checks:
                    out = subprocess.getoutput(cmd).strip().lower()
                    if "dark" in out:
                        return "dark"
                    if out:
                        return "light"

        # Generic env fallback
        gtk_theme = (os.environ.get("GTK_THEME") or "").lower()
        if "dark" in gtk_theme:
            return "dark"
        if gtk_theme:
            return "light"
        return "dark"

    def apply_theme(self, theme_name):
        """Wczytuje plik .qss i aplikuje go do całej aplikacji."""
        theme_name = theme_name.lower()
        self.current_theme_mode = theme_name if theme_name in ("system", "dark", "light") else "system"
        if self.current_theme_mode == "system":
            resolved = self._detect_system_theme()
            self._log(f"Theme mode 'system' resolved to '{resolved}'.", "INFO")
            theme_name = resolved
        if theme_name not in ["light", "dark"]:
            theme_name = "dark"

        style_file = os.path.join(self.styles_path, f"{theme_name}.qss")

        try:
            if not os.path.exists(style_file):
                self._log(f"QSS file missing: {style_file}", "ERROR")
                return

            with open(style_file, "r", encoding="utf-8") as f:
                qss = f.read()
            
            app = QApplication.instance()
            if app:
                app.setStyleSheet(qss)
                self.current_theme = theme_name
                self._refresh_top_level_widgets(app)
                self._log(f"Theme '{theme_name}' applied (mode: {self.current_theme_mode}).", "SUCCESS")
                
                # Jeśli okno już istnieje, wymuszamy odświeżenie ikon w Toolbarze
                if self.main_window and hasattr(self.main_window, 'toolbar'):
                    self.main_window.toolbar.update_icons()
            else:
                self._log("QApplication not found!", "ERROR")
            
        except Exception as e:
            self._log(f"Theme loading error: {e}", "ERROR")

    def _refresh_top_level_widgets(self, app):
        for widget in app.topLevelWidgets():
            try:
                style = widget.style()
                style.unpolish(widget)
                style.polish(widget)
                widget.update()
            except Exception:
                pass

    def toggle_theme(self):
        """Przełącza motyw i powiadamia o tym system."""
        new_theme = "dark" if self.current_theme == "light" else "light"
        self.apply_theme(new_theme)
        
        # Opcjonalnie: zapisz wybór użytkownika w configu (ogarniemy to przy config_handler)
