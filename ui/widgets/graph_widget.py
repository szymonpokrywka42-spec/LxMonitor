from __future__ import annotations

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QLinearGradient, QPolygonF

class GraphWidget(QWidget):
    def __init__(
        self,
        parent=None,
        max_points=50,
        label="Usage",
        unit="%",
        max_value: float | None = 100.0,
        peak_window=1,
    ):
        super().__init__(parent)
        self.max_points = max_points
        self.label = label
        self.unit = unit
        self.max_value = max_value
        self.peak_window = max(1, int(peak_window))
        self.recent_raw = []
        self.data = [0.0] * self.max_points
        
        self.setMinimumHeight(120)

        # Kolorystyka Evergreen
        self.color_line = QColor("#4ec9b0")  # Turkus
        self.color_fill_top = QColor(78, 201, 176, 100)
        self.color_fill_bottom = QColor(78, 201, 176, 0)
        self.color_grid = QColor(60, 60, 60, 150)
        self.color_text = QColor("#888888")
        self.blocked = False
        self.blocked_message = "Blocked: no permissions"

    def add_value(self, value):
        """Dodaje nową wartość i przesuwa wykres."""
        if self.blocked:
            return
        raw = float(value)
        if self.peak_window > 1:
            self.recent_raw.append(raw)
            if len(self.recent_raw) > self.peak_window:
                self.recent_raw.pop(0)
            plotted = max(self.recent_raw)
        else:
            plotted = raw
        self.data.append(plotted)
        if len(self.data) > self.max_points:
            self.data.pop(0)
        self.update()

    def set_blocked(self, blocked, message=None):
        self.blocked = bool(blocked)
        if message is not None:
            self.blocked_message = message
        self.update()

    def set_accent_color(self, color):
        """Sets line/fill color theme for this graph."""
        if isinstance(color, str):
            color = QColor(color)
        if not isinstance(color, QColor) or not color.isValid():
            return
        self.color_line = QColor(color)
        self.color_fill_top = QColor(color.red(), color.green(), color.blue(), 110)
        self.color_fill_bottom = QColor(color.red(), color.green(), color.blue(), 0)
        self.update()

    def _resolve_scale_max(self):
        if self.max_value is not None:
            return max(1.0, float(self.max_value))
        dynamic_max = max(self.data) if self.data else 1.0
        return max(1.0, dynamic_max * 1.15)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        padding = 20
        graph_w = w - (padding * 2)
        graph_h = h - (padding * 2)

        if self.blocked:
            painter.setPen(QColor("#ce9178"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self.blocked_message,
            )
            return

        # 1. Rysowanie tła i siatki
        painter.setPen(QPen(self.color_grid, 1, Qt.PenStyle.DashLine))
        for i in range(4):  # Linie poziome (0%, 33%, 66%, 100%)
            y = padding + (graph_h / 3) * i
            painter.drawLine(int(padding), int(y), int(w - padding), int(y))

        # 2. Przygotowanie punktów wykresu
        points = QPolygonF()
        x_step = graph_w / (self.max_points - 1)
        scale_max = self._resolve_scale_max()
        
        for i, val in enumerate(self.data):
            # Mapowanie wartości na wysokość widgetu (odwrócone Y)
            val_clamped = max(0.0, min(scale_max, val))
            x = padding + (i * x_step)
            y = (padding + graph_h) - (val_clamped / scale_max * graph_h)
            points.append(QPointF(x, y))

        # 3. Rysowanie wypełnienia (Gradient pod linią)
        path_fill = QPolygonF(points)
        path_fill.append(QPointF(padding + graph_w, padding + graph_h))
        path_fill.append(QPointF(padding, padding + graph_h))

        gradient = QLinearGradient(0, padding, 0, padding + graph_h)
        gradient.setColorAt(0, self.color_fill_top)
        gradient.setColorAt(1, self.color_fill_bottom)
        
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(path_fill)

        # 4. Rysowanie głównej linii
        pen = QPen(self.color_line, 2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(points)

        # 5. Etykieta i aktualna wartość
        painter.setPen(self.color_text)
        current = self.data[-1] if self.data else 0.0
        if self.unit == "%":
            value_text = f"{int(current)}{self.unit}"
        else:
            value_text = f"{current:.1f} {self.unit}"
        painter.drawText(padding, padding - 5, f"{self.label}: {value_text}")

    def update_theme(self, is_dark):
        """Dostosowanie kolorów do motywu."""
        base = self.color_line if isinstance(self.color_line, QColor) else QColor("#4ec9b0")
        if is_dark:
            self.color_grid = QColor(60, 60, 60, 150)
            self.color_text = QColor("#8fa2b8")
            self.color_fill_top = QColor(base.red(), base.green(), base.blue(), 110)
            self.color_fill_bottom = QColor(base.red(), base.green(), base.blue(), 0)
        else:
            self.color_grid = QColor(130, 140, 155, 130)
            self.color_text = QColor("#4b5563")
            self.color_fill_top = QColor(base.red(), base.green(), base.blue(), 75)
            self.color_fill_bottom = QColor(base.red(), base.green(), base.blue(), 0)
        self.update()
