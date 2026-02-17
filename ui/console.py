from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QLineEdit
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QTextCursor, QKeyEvent

class ConsoleDialog(QDialog):
    def __init__(self, parent=None, logic=None):
        super().__init__(parent)
        self.logic = logic
        self.main_window = parent
        self.theme_manager = parent.theme_manager if parent else None
        self.history_index = -1
        
        self.setObjectName("ConsoleDialog")
        self.resize(720, 480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Wyświetlacz logów (ConsoleDisplay w QSS)
        self.display = QTextEdit()
        self.display.setObjectName("ConsoleDisplay")
        self.display.setReadOnly(True)
        
        # Font monospaced (priorytet dla Cascadia Code, potem systemowy Monospace)
        font = QFont("Cascadia Code", 10)
        if not font.fixedPitch(): 
            font = QFont("Monospace", 10)
        
        self.display.setFont(font)
        layout.addWidget(self.display)

        # Input dla komend (ConsoleInput w QSS)
        self.input = QLineEdit()
        self.input.setObjectName("ConsoleInput")
        self.input.setFont(font)
        self.input.installEventFilter(self)
        self.input.returnPressed.connect(self.handle_input)
        layout.addWidget(self.input)

        self.retranslate_ui()

        # Synchronizacja z historią logiki (zaczytuje logi np. z BOOT)
        if self.logic:
            for msg in self.logic.history:
                self.append_text(msg)

    def refresh_theme_colors(self):
        self.display.clear()
        if not self.logic:
            return
        for msg in self.logic.history:
            self.append_text(msg)

    def keyPressEvent(self, event: QKeyEvent):
        """Obsługa zamykania konsoli tym samym klawiszem F12 lub Esc."""
        if event.key() == Qt.Key.Key_F12 or event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def get_color_for_level(self, level):
        """Zwraca kolor dopasowany do motywów LxMonitor (Light/Dark)."""
        is_dark = True
        if self.theme_manager:
            is_dark = self.theme_manager.current_theme == "dark"

        if is_dark:
            color_map = {
                "INFO": "#cccccc",    # Jasnoszary
                "SUCCESS": "#4ec9b0", # Turkus (Evergreen)
                "WARN": "#ce9178",    # Pomarańcz/Cegła
                "ERROR": "#f44747",   # Czerwony
                "SYSTEM": "#569cd6",  # Błękit
                "BOOT": "#b5cea8",    # Jasna zieleń
                "ENGINE": "#dcdcaa",  # Żółtawy (Logi z C++)
                "ACTION": "#dcdcdc"   # Białawy
            }
        else:
            color_map = {
                "INFO": "#2d2d2d",    # Grafit
                "SUCCESS": "#058b72", # Ciemny turkus
                "WARN": "#a31515",    # Ciemna czerwień
                "ERROR": "#cd3131",   # Wyrazisty czerwony
                "SYSTEM": "#005a9e",  # Ciemny niebieski
                "BOOT": "#228b22",    # Forest Green
                "ENGINE": "#795e26",  # Brązowy/Oliwkowy
                "ACTION": "#4f4f4f"
            }
        return color_map.get(level, color_map["INFO"])

    def append_text(self, text, level="INFO"):
        """Dodaje tekst z dynamicznym kolorowaniem HTML."""
        active_level = level
        # Automatyczne wykrywanie poziomu z tagów [TAG]
        for tag in ["INFO", "SUCCESS", "WARN", "ERROR", "SYSTEM", "BOOT", "ENGINE", "ACTION"]:
            if f"[{tag}]" in text:
                active_level = tag
                break

        color = self.get_color_for_level(active_level)
        
        # Formatowanie HTML z zachowaniem spacji (pre-wrap)
        html_msg = f'<div style="color:{color}; white-space: pre-wrap; margin-bottom: 2px;">{text}</div>'
        self.display.append(html_msg)
        
        # Zawsze przewijaj na dół
        self.display.moveCursor(QTextCursor.MoveOperation.End)

    def retranslate_ui(self):
        tr = self.main_window.lang_handler.tr
        self.setWindowTitle(tr("console_title"))
        self.input.setPlaceholderText(tr("console_placeholder"))

    def handle_input(self):
        text = self.input.text().strip()
        if not text: return
        
        self.history_index = -1
        result = self.logic.execute_command(text)
        
        if result == "clear":
            self.display.clear()
        elif result:
            system_prefix = self.main_window.lang_handler.tr("console_system_prefix")
            self.append_text(f"[{system_prefix}] {result}", "SYSTEM")
            
        self.input.clear()

    def eventFilter(self, source, event):
        """Obsługa strzałek góra/dół dla historii komend w input."""
        if event.type() == event.Type.KeyPress and source is self.input:
            if event.key() == Qt.Key.Key_Up:
                self._browse_history(-1)
                return True
            elif event.key() == Qt.Key.Key_Down:
                self._browse_history(1)
                return True
        return super().eventFilter(source, event)

    def _browse_history(self, direction):
        if not self.logic or not self.logic.command_history: return
        
        self.history_index += direction
        # Ograniczenie indeksu
        self.history_index = max(-1, min(self.history_index, len(self.logic.command_history) - 1))
        
        if self.history_index == -1:
            self.input.clear()
        else:
            # Historia od najnowszych do najstarszych
            cmd = list(reversed(self.logic.command_history))[self.history_index]
            self.input.setText(cmd)
