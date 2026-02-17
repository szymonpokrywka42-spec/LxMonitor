import sys
import os
import time
import json
import glob

# 1. Ścieżki
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path: 
    sys.path.insert(0, current_dir)
lxbinman_local = os.path.join(current_dir, "LxBinMan")
if os.path.isdir(lxbinman_local) and lxbinman_local not in sys.path:
    sys.path.insert(0, lxbinman_local)

# 2. Szybkie importy do Splasha
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QFontMetrics, QIcon, QPixmap
from PyQt6.QtCore import Qt, QPropertyAnimation


def load_startup_config():
    cfg_path = os.path.join(current_dir, "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

class LxSplashScreen(QWidget):
    def __init__(self, supports_opacity=True):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.panel = QWidget()
        self.panel.setObjectName("splashPanel")
        self.panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.panel.setStyleSheet(
            "#splashPanel {"
            "background: rgba(9, 14, 22, 210);"
            "border: 1px solid rgba(86, 102, 124, 0.7);"
            "border-radius: 12px;"
            "}"
        )
        root.addWidget(self.panel)

        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        self._status_full_text = ""

        self.logo_label = QLabel()
        self.logo_label.setStyleSheet("background: transparent; border: none;")
        self.logo_label.setFixedSize(160, 160)
        app_icon_path = os.path.join(current_dir, "assets", "icons", "icon.png")
        if os.path.exists(app_icon_path):
            self.setWindowIcon(QIcon(app_icon_path))
        # Zmieniona ścieżka na splash.png w LxMonitor
        icon_path = os.path.join(current_dir, "assets", "icons", "splash.png")
        if os.path.exists(icon_path):
            self.logo_label.setPixmap(
                QPixmap(icon_path).scaled(
                    132,
                    132,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.logo_label.setText("🐧")
            self.logo_label.setStyleSheet(
                "background: transparent; border: none; color: #c9d4e3; font-size: 64px;"
            )

        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.logo_label)

        self.msg_label = QLabel("LxMonitor: Initializing...")
        self.msg_label.setMinimumHeight(36)
        self.msg_label.setMaximumHeight(44)
        self.msg_label.setStyleSheet(
            "color: #4ec9b0; background: rgba(14,18,26,210); padding: 8px 10px; border-radius: 8px; "
            "font-family: 'Segoe UI', sans-serif; font-weight: bold;"
        )
        self.msg_label.setWordWrap(False)
        self.msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.msg_label)

        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet(
            "color: #c9d4e3; background: rgba(12,16,24,180); padding: 8px; border-radius: 8px; "
            "font-family: 'Segoe UI', sans-serif; font-size: 11px;"
        )
        self.info_label.hide()
        layout.addWidget(self.info_label)

        self.adjustSize()
        self.center_on_screen()
        
        self.fade_anim = None
        if supports_opacity:
            self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
            self.fade_anim.setDuration(400)
            self.fade_anim.setStartValue(1.0)
            self.fade_anim.setEndValue(0.0)
            self.fade_anim.finished.connect(self.close)

    def center_on_screen(self):
        primary = QApplication.primaryScreen()
        if primary is None:
            return
        screen = primary.availableGeometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)

    def update_msg(self, text):
        raw = str(text or "").strip()
        # Keep splash clean: one-line status, no long multiline logs over the logo area.
        if raw.startswith("[") and "]" in raw:
            raw = raw.split("]", 1)[1].strip()
        fm = QFontMetrics(self.msg_label.font())
        safe = fm.elidedText(raw, Qt.TextElideMode.ElideRight, max(140, self.msg_label.width() - 24))
        self._status_full_text = raw
        self.msg_label.setText(safe)
        self.msg_label.setToolTip(raw if safe != raw else "")
        QApplication.processEvents()

    def update_info(self, text):
        txt = (text or "").strip()
        self.info_label.setText(txt)
        self.info_label.setVisible(bool(txt))
        QApplication.processEvents()

    def fade_out_and_close(self):
        if self.fade_anim: self.fade_anim.start()
        else: self.close()

def main():
    # --- KROK 1: START GUI ---
    app = QApplication(sys.argv)
    app.setApplicationName("LxMonitor")
    platform_name = (app.platformName() or "").lower()
    supports_opacity = not any(x in platform_name for x in ("wayland", "offscreen", "minimal"))
    
    startup_cfg = load_startup_config()
    splash = LxSplashScreen(supports_opacity=supports_opacity)
    splash.show()
    splash_started_at = time.monotonic()
    splash.update_msg("Starting LxMonitor Engine...") 

    # --- KROK 2: KOMPONENTY CORE ---
    # Tutaj importujemy logikę, która od razu przejmuje sys.stdout
    from core.compat import collect_runtime_compat, log_compat_report
    from core.language_handler import LanguageHandler
    from core.console_logic import ConsoleLogic

    boot_logs = []
    build_failures = {}
    optional_engines = {"gpu_nvidia"}

    def log_boot(msg, level="BOOT"):
        # To trafi do terminala i do listy, którą potem wstrzykniemy do konsoli
        full_msg = f"[{level}] {msg}"
        print(full_msg) 
        boot_logs.append(full_msg)
        splash.update_msg(msg)

    # Inicjalizacja języka
    lang = LanguageHandler()
    log_boot("Language system loaded.")
    splash.update_info(lang.tr("startup_locked_warning"))
    try:
        compat = collect_runtime_compat()
        log_compat_report(compat, log_boot)
    except Exception as e:
        log_boot(f"Compat probe error: {e}", "WARN")

    # --- KROK 3: BUILDER (C++ Engines via LxBinMan) ---
    engines_src = os.path.join(current_dir, "core", "engines")
    if os.path.isdir(engines_src):
        try:
            from lxbinman import feedback as binman_feedback
            from lxbinman import builder as binman_builder

            def _on_binman_event(event):
                level = getattr(event, "level", "INFO")
                code = str(getattr(event, "code", "") or "").strip()
                message = str(getattr(event, "message", "") or "").strip()
                ctx = getattr(event, "context", {}) or {}
                if code == "builder:partial":
                    failed_raw = str(ctx.get("failed", "") or "").strip()
                    failed_names = {x.strip() for x in failed_raw.split(",") if x.strip()}
                    if failed_names and failed_names.issubset(optional_engines):
                        level = "INFO"
                        message = f"Only optional engines failed: {', '.join(sorted(failed_names))}"
                if code == "builder:engine" and str(level).upper() == "ERROR":
                    failed_engine = ""
                    if ":" in message:
                        failed_engine = message.split(":", 1)[1].strip()
                    if failed_engine:
                        err = str(ctx.get("error", "")).strip()
                        if not err:
                            err = "engine build/link failed"
                        build_failures[failed_engine] = err
                        if failed_engine in optional_engines:
                            level = "INFO"
                            message = f"Optional engine skipped: {failed_engine}"
                if code:
                    log_boot(f"LxBinMan/{code}: {message}", level)
                else:
                    log_boot(f"LxBinMan: {message}", level)

            binman_feedback.enable_console(False)
            binman_feedback.subscribe(_on_binman_event)
            try:
                log_boot("Checking C++ Engine components...")
                result = binman_builder.build_all(
                    source_dir=engines_src,
                    feedback=binman_feedback,
                    output_dir=engines_src,
                    compile_only=True,
                    policy="prefer_cache",
                )
                source_names = {
                    os.path.splitext(os.path.basename(p))[0]
                    for p in glob.glob(os.path.join(engines_src, "*.cpp"))
                }
                optional_engines = optional_engines & source_names
                expected = len(source_names)
                expected_required = max(0, expected - len(optional_engines))
                ready = len(result) if isinstance(result, dict) else 0
                failed = set(build_failures.keys())
                required_failures = failed - optional_engines
                optional_failures = failed & optional_engines
                if ready <= 0:
                    log_boot("Engine build: FAILED", "ERROR")
                elif required_failures:
                    log_boot(
                        f"Engine build: PARTIAL ({ready}/{expected_required} required) | failed: {', '.join(sorted(required_failures))}",
                        "WARN",
                    )
                elif ready < expected_required:
                    log_boot(f"Engine build: PARTIAL ({ready}/{expected_required})", "WARN")
                elif optional_failures:
                    log_boot(
                        f"Engine build: SUCCESS (optional skipped: {', '.join(sorted(optional_failures))})",
                        "SUCCESS",
                    )
                else:
                    log_boot("Engine build: SUCCESS", "SUCCESS")
            finally:
                binman_feedback.unsubscribe(_on_binman_event)
        except Exception as e:
            log_boot(f"Builder Error: {e}", "ERROR")

    # --- KROK 4: MAIN WINDOW ---
    try:
        log_boot("Preparing Dashboard UI...")
        # Import okna głównego dopiero tutaj
        from ui.main_window import LxMainWindow
        
        # Tworzymy okno, przekazując mu zgromadzone logi z bootowania
        window = LxMainWindow(startup_logs=boot_logs, build_failures=build_failures)
        
        # Minimalny czas widoczności splash screena (domyślnie 2s, konfigurowalne).
        min_splash_s = 2.0
        if "splash_min_seconds" in startup_cfg:
            try:
                min_splash_s = max(0.0, min(12.0, float(startup_cfg.get("splash_min_seconds", 2.0))))
            except Exception:
                min_splash_s = 2.0
        if str(os.environ.get("LXMONITOR_FAST_START", "")).strip().lower() in {"1", "true", "yes", "on"}:
            min_splash_s = 0.0
        remaining = min_splash_s - (time.monotonic() - splash_started_at)
        if remaining > 0:
            end_at = time.monotonic() + remaining
            while time.monotonic() < end_at:
                app.processEvents()
                time.sleep(0.02)

        log_boot("System Ready.")
        window.show()
        
        splash.fade_out_and_close()
        sys.exit(app.exec())
        
    except Exception as e:
        print(f"CRITICAL STARTUP ERROR: {e}")
        if 'splash' in locals(): splash.close()

if __name__ == "__main__":
    main()
