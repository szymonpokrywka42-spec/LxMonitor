# pyright: reportAttributeAccessIssue=false
import json
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.toolbar import MainToolbar
from ui.widgets.graph_widget import GraphWidget


class UiSetupMixin:
    def apply_base_stylesheet(self):
        self.setStyleSheet(
            """
            #central_widget {
                background: transparent;
            }
            QWidget#dashboard {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 rgba(13, 20, 30, 0.92),
                    stop: 0.5 rgba(17, 26, 38, 0.90),
                    stop: 1 rgba(10, 18, 28, 0.94)
                );
            }
            QWidget#mainPanel {
                background: rgba(10, 18, 28, 0.45);
                border: 1px solid rgba(114, 126, 145, 0.45);
                border-radius: 10px;
            }
            QWidget#sidebarContent {
                background: transparent;
            }
            #panelSeparatorV,
            #panelSeparatorH {
                background: rgba(120, 130, 148, 0.52);
                border: none;
            }
            QFrame#metricCard {
                border: 1px solid rgba(120, 130, 148, 0.48);
                border-radius: 10px;
                background: rgba(20, 30, 44, 0.44);
            }
            QFrame#metricCard:hover {
                border: 1px solid rgba(145, 166, 194, 0.92);
                background: rgba(31, 47, 70, 0.70);
            }
            QFrame#metricCardActive {
                border: 2px solid rgba(99, 195, 230, 0.95);
                border-radius: 10px;
                background: rgba(17, 36, 56, 0.62);
            }
            QFrame#metricCardSeparator {
                background: rgba(136, 148, 168, 0.55);
                border: none;
                min-height: 2px;
                max-height: 2px;
            }
            QScrollArea#sidebarScroll,
            QScrollArea#cpuCoresScroll {
                background: transparent;
                border: none;
            }
            QScrollArea#sidebarScroll > QWidget#qt_scrollarea_viewport,
            QScrollArea#cpuCoresScroll > QWidget#qt_scrollarea_viewport {
                background: transparent;
                border: none;
            }
            QWidget#sidebarContent,
            QWidget#cpuCoresContent {
                background: transparent;
            }
            QScrollArea#sidebarScroll QScrollBar:vertical,
            QScrollArea#cpuCoresScroll QScrollBar:vertical {
                background: rgba(128, 128, 128, 0.25);
                width: 10px;
                margin: 2px;
                border-radius: 5px;
            }
            QScrollArea#sidebarScroll QScrollBar::handle:vertical,
            QScrollArea#cpuCoresScroll QScrollBar::handle:vertical {
                background: rgba(108, 116, 129, 0.75);
                min-height: 22px;
                border-radius: 5px;
            }
            QScrollArea#sidebarScroll QScrollBar::handle:vertical:hover,
            QScrollArea#cpuCoresScroll QScrollBar::handle:vertical:hover {
                background: rgba(91, 100, 116, 0.9);
            }
            QScrollArea#sidebarScroll QScrollBar::add-line:vertical,
            QScrollArea#sidebarScroll QScrollBar::sub-line:vertical,
            QScrollArea#cpuCoresScroll QScrollBar::add-line:vertical,
            QScrollArea#cpuCoresScroll QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollArea#sidebarScroll QScrollBar::add-page:vertical,
            QScrollArea#sidebarScroll QScrollBar::sub-page:vertical,
            QScrollArea#cpuCoresScroll QScrollBar::add-page:vertical,
            QScrollArea#cpuCoresScroll QScrollBar::sub-page:vertical {
                background: transparent;
            }
            """
        )

    def _theme_is_dark(self):
        return getattr(self.theme_manager, "current_theme", "dark") == "dark"

    def _spark_style(self):
        if self._theme_is_dark():
            return "background-color: #111722; border: 1px solid #2e3748; border-radius: 4px;"
        return "background-color: #e3e9f1; border: 1px solid #8894a8; border-radius: 4px;"

    def _primary_graph_style(self, accent):
        if self._theme_is_dark():
            return (
                "background-color: rgba(14, 21, 31, 0.95);"
                f"border: 1px solid {accent}; border-radius: 7px;"
            )
        return (
            "background-color: rgba(226, 233, 243, 0.96);"
            f"border: 1px solid {accent}; border-radius: 7px;"
        )

    def apply_theme_overrides(self):
        is_dark = self._theme_is_dark()
        title_color = "#ecf4ff" if is_dark else "#1f2937"
        subtitle_color = "#9cb1c8" if is_dark else "#5b667a"
        info_color = "#d2deec" if is_dark else "#334155"

        self.page_title.setStyleSheet(
            f"font-size: 18px; color: {title_color}; font-weight: 600; letter-spacing: 0.3px;"
            "font-family: 'Noto Sans', 'Segoe UI', sans-serif;"
        )
        self.primary_title.setStyleSheet(
            f"font-size: 34px; color: {title_color}; font-weight: 600;"
            "font-family: 'Noto Sans', 'Segoe UI', sans-serif;"
        )
        self.primary_subtitle.setStyleSheet(
            f"font-size: 17px; color: {subtitle_color}; font-family: 'Noto Sans', 'Segoe UI', sans-serif;"
        )

        info_style = (
            f"color: {info_color}; font-size: 14px; line-height: 1.3;"
            "font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace;"
        )
        self.info_left.setStyleSheet(info_style)
        self.info_right.setStyleSheet(info_style)

        self.primary_graph.update_theme(is_dark)
        selected = self.metric_cards.get(self.selected_metric)
        accent = selected.get("accent", "#4ec9b0") if selected else "#4ec9b0"
        self.primary_graph.setStyleSheet(self._primary_graph_style(accent))

        card_title_color = "#edf3fb" if is_dark else "#1f2937"
        card_subtitle_color = "#7fa0bf" if is_dark else "#5b667a"
        card_value_color = "#9fb0c2" if is_dark else "#475569"
        for parts in self.metric_cards.values():
            parts["title"].setStyleSheet(
                f"font-size: 15px; color: {card_title_color}; font-family: 'Noto Sans', 'Segoe UI', sans-serif;"
            )
            parts["subtitle"].setStyleSheet(
                f"font-size: 11px; color: {card_subtitle_color}; font-family: 'Noto Sans', 'Segoe UI', sans-serif;"
            )
            parts["value"].setStyleSheet(
                f"font-size: 12px; color: {card_value_color}; font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace;"
            )
            parts["spark"].setStyleSheet(self._spark_style())
            parts["spark"].update_theme(is_dark)

        sep_color = "rgba(139, 154, 178, 0.78)" if is_dark else "rgba(111, 123, 144, 0.88)"
        for sep in getattr(self, "metric_card_separators", {}).values():
            sep.setStyleSheet(f"background: {sep_color}; border: none;")

        for graph in self.cpu_core_graphs.values():
            graph.setStyleSheet(self._spark_style())
            graph.update_theme(is_dark)
        for graph in getattr(self, "power_sensor_graphs", {}).values():
            graph.setStyleSheet(self._spark_style())
            graph.update_theme(is_dark)

    def repair_language_file(self):
        base_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        lang_dir = os.path.join(base_dir, "assets", "languages")
        if not os.path.exists(lang_dir):
            os.makedirs(lang_dir)
        for lang_file in ["en-us.json", "pl-pl.json"]:
            path = os.path.join(lang_dir, lang_file)
            if not os.path.exists(path) or os.path.getsize(path) == 0:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({}, f)

    def setup_icon(self):
        base_path = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        icon_path = os.path.join(base_path, "assets", "icons", "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

    def setup_ui(self):
        self.setWindowTitle(self.lang_handler.tr("window_title"))
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            target_w = max(980, min(1240, int(avail.width() * 0.9)))
            target_h = max(680, min(780, int(avail.height() * 0.9)))
            self.setMinimumSize(980, 680)
            self.setMaximumSize(avail.width(), avail.height())
            self.resize(target_w, target_h)
            self.move(
                avail.x() + (avail.width() - target_w) // 2,
                avail.y() + (avail.height() - target_h) // 2,
            )
        else:
            self.setMinimumSize(980, 680)
            self.resize(1240, 780)

        self.central_widget = QWidget()
        self.central_widget.setObjectName("central_widget")
        self.setCentralWidget(self.central_widget)

        root = QVBoxLayout(self.central_widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.toolbar = MainToolbar(self)
        root.addWidget(self.toolbar)

        self.dashboard = QWidget()
        self.dashboard.setObjectName("dashboard")
        content = QHBoxLayout(self.dashboard)
        content.setContentsMargins(10, 10, 10, 10)
        content.setSpacing(10)

        self.sidebar_widget = QWidget()
        self.sidebar_widget.setObjectName("sidebarContent")
        self.sidebar_widget.setFixedWidth(305)
        self.sidebar_layout = QVBoxLayout(self.sidebar_widget)
        self.sidebar_layout.setContentsMargins(0, 0, 0, 0)
        self.sidebar_layout.setSpacing(10)
        self.metric_card_separators = {}

        self.sidebar_scroll = QScrollArea()
        self.sidebar_scroll.setObjectName("sidebarScroll")
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.sidebar_scroll.setStyleSheet("background: transparent; border: none;")
        self.sidebar_scroll.setWidget(self.sidebar_widget)
        self.sidebar_scroll.setFixedWidth(305)

        self.main_panel = QWidget()
        self.main_panel.setObjectName("mainPanel")
        panel = QVBoxLayout(self.main_panel)
        panel.setContentsMargins(14, 10, 14, 10)
        panel.setSpacing(10)

        self.page_title = QLabel()
        self.page_title.setStyleSheet(
            "font-size: 19px; font-weight: 600; letter-spacing: 0.5px;"
            "font-family: 'Noto Sans', 'Segoe UI', sans-serif;"
        )
        panel.addWidget(self.page_title)

        self.header_separator = QFrame()
        self.header_separator.setObjectName("panelSeparatorH")
        self.header_separator.setFrameShape(QFrame.Shape.HLine)
        self.header_separator.setFixedHeight(1)
        panel.addWidget(self.header_separator)

        title_row = QHBoxLayout()
        self.primary_title = QLabel()
        self.primary_title.setWordWrap(False)
        self.primary_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.primary_title.setStyleSheet(
            "font-size: 34px; font-weight: 600;"
            "font-family: 'Noto Sans', 'Segoe UI', sans-serif;"
        )
        self.primary_subtitle = QLabel()
        self.primary_subtitle.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.primary_subtitle.setWordWrap(False)
        self.primary_subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.primary_subtitle.setStyleSheet(
            "font-size: 17px; font-family: 'Noto Sans', 'Segoe UI', sans-serif;"
        )
        title_row.addWidget(self.primary_title)
        title_row.addWidget(self.primary_subtitle, 1)
        panel.addLayout(title_row)

        self.primary_graph = GraphWidget(label="", unit="%", max_value=100.0, peak_window=6)
        self.primary_graph.setMinimumHeight(320)
        panel.addWidget(self.primary_graph)

        self.graph_separator = QFrame()
        self.graph_separator.setObjectName("panelSeparatorH")
        self.graph_separator.setFrameShape(QFrame.Shape.HLine)
        self.graph_separator.setFixedHeight(1)
        panel.addWidget(self.graph_separator)

        # Per-core/thread mini charts (Windows-like) for CPU view.
        self.cpu_cores_scroll = QScrollArea()
        self.cpu_cores_scroll.setObjectName("cpuCoresScroll")
        self.cpu_cores_scroll.setWidgetResizable(True)
        self.cpu_cores_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cpu_cores_scroll.setMinimumHeight(260)
        self.cpu_cores_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cpu_cores_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.cpu_cores_scroll.setStyleSheet("background: transparent; border: none;")

        self.cpu_cores_widget = QWidget()
        self.cpu_cores_widget.setObjectName("cpuCoresContent")
        self.cpu_cores_layout = QGridLayout(self.cpu_cores_widget)
        self.cpu_cores_layout.setContentsMargins(0, 0, 0, 0)
        self.cpu_cores_layout.setHorizontalSpacing(8)
        self.cpu_cores_layout.setVerticalSpacing(8)
        self.cpu_cores_scroll.setWidget(self.cpu_cores_widget)
        self.cpu_cores_scroll.hide()
        panel.addWidget(self.cpu_cores_scroll)

        self.info_grid = QGridLayout()
        self.info_grid.setHorizontalSpacing(30)
        self.info_grid.setVerticalSpacing(6)

        self.info_left = QLabel()
        self.info_right = QLabel()
        info_style = (
            "font-size: 15px; line-height: 1.3;"
            "font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace;"
        )
        self.info_left.setStyleSheet(info_style)
        self.info_right.setStyleSheet(info_style)
        self.info_left.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.info_right.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self.info_grid.addWidget(self.info_left, 0, 0)
        self.info_grid.addWidget(self.info_right, 0, 1)
        panel.addLayout(self.info_grid)

        self.sidebar_main_separator = QFrame()
        self.sidebar_main_separator.setObjectName("panelSeparatorV")
        self.sidebar_main_separator.setFrameShape(QFrame.Shape.VLine)
        self.sidebar_main_separator.setFixedWidth(1)

        content.addWidget(self.sidebar_scroll)
        content.addWidget(self.sidebar_main_separator)
        content.addWidget(self.main_panel, 1)
        root.addWidget(self.dashboard, 1)

        self._add_metric_card("cpu", "graph_cpu_load", "%", 100.0, peak_window=3)
        self._add_metric_card("ram", "gauge_ram", "%", 100.0, peak_window=3)
        self._add_metric_card("gpu", "graph_gpu_load", "%", 100.0, peak_window=6, protected=True)
        self._add_metric_card("psu", "graph_psu_power", "W", None, peak_window=4)
        self._add_metric_card("net_total", "graph_net_total", "Mbps", None, peak_window=4)

        self.sidebar_layout.addStretch()
        self._select_metric("cpu")

    def _add_metric_card(self, metric_name, title_key, unit, max_value, peak_window=1, protected=False):
        card = QFrame()
        card.setObjectName("metricCard")

        layout = QHBoxLayout(card)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(8)

        spark = GraphWidget(label="", unit=unit, max_value=max_value, peak_window=peak_window)
        spark.setMinimumHeight(52)
        spark.setMaximumHeight(52)
        spark.setMinimumWidth(74)
        spark.setMaximumWidth(74)
        spark.setStyleSheet(self._spark_style())
        spark.set_accent_color(self._metric_accent(metric_name))

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        title_lbl = QLabel()
        title_lbl.setWordWrap(False)
        title_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title_lbl.setStyleSheet(
            "font-size: 16px; font-family: 'Noto Sans', 'Segoe UI', sans-serif;"
        )
        subtitle_lbl = QLabel()
        subtitle_lbl.setWordWrap(False)
        subtitle_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        subtitle_lbl.setStyleSheet(
            "font-size: 12px; font-family: 'Noto Sans', 'Segoe UI', sans-serif;"
        )
        value_lbl = QLabel("0")
        value_lbl.setStyleSheet(
            "font-size: 13px; font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace;"
        )

        text_col.addWidget(title_lbl)
        text_col.addWidget(subtitle_lbl)
        text_col.addWidget(value_lbl)

        layout.addWidget(spark)
        layout.addLayout(text_col, 1)

        def on_click(_event, m=metric_name):
            self._select_metric(m)

        card.mousePressEvent = on_click

        self.metric_cards[metric_name] = {
            "card": card,
            "spark": spark,
            "title": title_lbl,
            "subtitle": subtitle_lbl,
            "value": value_lbl,
            "title_key": title_key,
            "unit": unit,
            "max": max_value,
            "protected": protected,
            "last": 0.0,
            "seen": False,
            "accent": self._metric_accent(metric_name),
        }
        insert_at = self.sidebar_layout.count()
        if insert_at > 0:
            tail_item = self.sidebar_layout.itemAt(insert_at - 1)
            if tail_item is not None and tail_item.spacerItem() is not None:
                insert_at -= 1
        self.sidebar_layout.insertWidget(insert_at, card)
        self._refresh_metric_separators()
        self._set_card_title(metric_name, self._metric_display_name(metric_name))
        self._set_card_subtitle(metric_name, self._metric_card_subtitle(metric_name))
        self.apply_theme_overrides()

    def _refresh_metric_separators(self):
        # Remove old separators first.
        for sep in self.metric_card_separators.values():
            try:
                self.sidebar_layout.removeWidget(sep)
                sep.setParent(None)
            except Exception:
                pass
        self.metric_card_separators = {}

        # Insert separators between visible metric cards.
        names = list(self.metric_cards.keys())
        for i in range(len(names) - 1):
            upper = self.metric_cards[names[i]].get("card")
            if upper is None:
                continue
            sep = QFrame()
            sep.setObjectName("metricCardSeparator")
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setFixedHeight(2)
            is_dark = self._theme_is_dark() if hasattr(self, "_theme_is_dark") else True
            color = "rgba(139, 154, 178, 0.78)" if is_dark else "rgba(111, 123, 144, 0.88)"
            sep.setStyleSheet(f"background: {color}; border: none;")
            idx = self.sidebar_layout.indexOf(upper)
            if idx >= 0:
                self.sidebar_layout.insertWidget(idx + 1, sep)
                self.metric_card_separators[names[i]] = sep

    def _shorten_text(self, text, max_len):
        if text is None:
            return ""
        text = str(text).strip()
        if len(text) <= max_len:
            return text
        return text[: max(1, max_len - 1)].rstrip() + "…"

    def _set_card_title(self, metric_name, full_title):
        parts = self.metric_cards.get(metric_name)
        if not parts:
            return
        full = str(full_title)
        short = self._shorten_text(full, 30)
        parts["title"].setText(short)
        parts["title"].setToolTip(full if short != full else "")

    def _set_card_subtitle(self, metric_name, full_subtitle):
        parts = self.metric_cards.get(metric_name)
        if not parts:
            return
        full = str(full_subtitle or "")
        short = self._shorten_text(full, 34)
        parts["subtitle"].setText(short)
        parts["subtitle"].setToolTip(full if short != full else "")

    def _set_primary_subtitle(self, text):
        full = str(text)
        short = self._shorten_text(full, 64)
        self.primary_subtitle.setText(short)
        self.primary_subtitle.setToolTip(full if short != full else "")

    def _set_primary_title(self, text):
        full = str(text)
        short = self._shorten_text(full, 42)
        self.primary_title.setText(short)
        self.primary_title.setToolTip(full if short != full else "")
