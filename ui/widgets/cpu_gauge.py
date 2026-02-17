from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRectF, pyqtProperty, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPainter, QColor, QPen, QFont

class CpuGauge(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._title = "USAGE" 
        self.setMinimumSize(160, 160) # Troszkę większy, żeby napisy nie wchodziły na łuk
        
        self.anim = QPropertyAnimation(self, b"value")
        self.anim.setDuration(120)
        self.anim.setEasingCurve(QEasingCurve.Type.OutQuad)

        self.color_bg = QColor("#2d2f3b")
        self.color_active = QColor("#00d4ff")
        self.color_text = QColor("#e6e6e6")

    @pyqtProperty(float)
    def value(self):
        return self._value

    @value.setter
    def value(self, val):
        self._value = val
        self.update()

    @pyqtProperty(QColor)
    def accentColor(self):
        return self.color_active

    @accentColor.setter
    def accentColor(self, val):
        if isinstance(val, QColor):
            self.color_active = val
            self.update()

    def set_title(self, text):
        """Ustawia tekst pod wartością (np. CPU lub RAM)"""
        self._title = text
        self.update()

    def set_value(self, val):
        self.anim.stop()
        self.anim.setStartValue(self._value)
        self.anim.setEndValue(float(val))
        self.anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing) # Ważne dla czystych napisów

        width = self.width()
        height = self.height()
        size = min(width, height) - 24
        
        # Główne koło
        rect = QRectF((width - size) / 2, (height - size) / 2, size, size)

        # Kąty: start z lewej-dół, łuk 270 stopni
        start_angle = -225 * 16 
        max_span = -270 * 16

        # 1. Tło łuku
        pen = QPen(self.color_bg, 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, start_angle, max_span)

        # 2. Aktywny postęp
        span_angle = int((self._value / 100.0) * max_span)
        
        active_pen = QPen(self.color_active, 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        if self._value > 85:
            active_pen.setColor(QColor("#ff4444"))
        elif self._value > 70:
            active_pen.setColor(QColor("#ffaa00"))

        painter.setPen(active_pen)
        painter.drawArc(rect, start_angle, span_angle)

        # 3. Rysowanie Wartości (%)
        painter.setPen(self.color_text)
        # Używamy standardowej czcionki Sans, jeśli Consolas kuleje z %
        val_font = QFont("Arial", int(size / 4), QFont.Weight.Bold)
        painter.setFont(val_font)
        
        # Podnosimy główny tekst lekko do góry, żeby zrobić miejsce na tytuł
        val_rect = rect.adjusted(0, -size/10, 0, -size/10)
        painter.drawText(val_rect, Qt.AlignmentFlag.AlignCenter, f"{int(self._value)}%")

        # 4. Rysowanie Tytułu (CPU / RAM)
        title_font = QFont("Verdana", int(size / 10), QFont.Weight.Bold)
        painter.setFont(title_font)
        
        # Umieszczamy napis dokładnie pod wartością
        title_rect = rect.adjusted(0, size/4, 0, 0)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignCenter, self._title)

    def update_theme(self, is_dark):
        self.color_bg = QColor("#2d2f3b") if is_dark else QColor("#e0e0e0")
        self.color_text = QColor("#e6e6e6") if is_dark else QColor("#222222")
        self.update()
