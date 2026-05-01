from __future__ import annotations

import argparse
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterable

from PyQt5.QtCore import (
    QObject,
    QPoint,
    QRectF,
    QSize,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QFontDatabase,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)


PROJECT_ROOT = Path(__file__).resolve().parent
ACCENT = QColor("#f49a23")
CYAN = QColor("#23c7e8")
GREEN = QColor("#42d77d")
RED = QColor("#ff5757")
TEXT = QColor("#d8dde3")
MUTED = QColor("#8b949e")
PANEL = QColor("#151a20")
PANEL_DARK = QColor("#101419")
LINE = QColor("#343b43")


APP_QSS = """
* {
    font-family: "Segoe UI";
    font-size: 14px;
    color: #d8dde3;
}
QFrame#Root {
    background: #0d1116;
    border: 1px solid #28303a;
    border-radius: 8px;
}
QFrame#TitleBar {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #14191f, stop:1 #0d1116);
    border-bottom: 1px solid #303842;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
QFrame#NavStrip {
    background: #10151b;
    border: 1px solid #202832;
    border-radius: 8px;
}
QFrame#Card {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #171d24, stop:1 #10151b);
    border: 1px solid #3a424d;
    border-radius: 8px;
}
QFrame#CoreCard {
    background: qradialgradient(cx:0.5, cy:0.45, radius:0.78, fx:0.5, fy:0.48, stop:0 #1b2027, stop:0.5 #12171d, stop:1 #0f1318);
    border: 1px solid #333c47;
    border-radius: 8px;
}
QFrame#TelemetryBar {
    background: #10151b;
    border: 1px solid #303842;
    border-radius: 8px;
}
QFrame#MessageBubble {
    background: transparent;
}
QFrame#ListBox {
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid #2b333d;
    border-radius: 6px;
}
QFrame#StatusPill {
    background: rgba(255, 255, 255, 0.025);
    border: 1px solid #38414c;
    border-radius: 8px;
}
QLabel#TitleJarvis {
    color: #f5a033;
    font-size: 23px;
    font-weight: 700;
}
QLabel#HeroTitle {
    color: #f5a033;
    font-size: 44px;
    font-weight: 600;
}
QLabel#PanelTitle {
    color: #f5a033;
    font-size: 16px;
    font-weight: 600;
}
QLabel#PathLabel {
    color: #f5a033;
    font-size: 13px;
}
QLabel#Muted {
    color: #8b949e;
}
QLabel#Cyan {
    color: #22c3e4;
}
QLabel#Green {
    color: #42d77d;
}
QLabel#StatusText {
    color: #42d77d;
    font-size: 19px;
}
QLineEdit#CommandInput {
    background: #161b22;
    border: 1px solid #343c47;
    border-radius: 6px;
    padding: 0 14px;
    color: #e5eaf0;
    selection-background-color: #f49a23;
}
QLineEdit#CommandInput:focus {
    border: 1px solid #d28122;
}
QPushButton#IconButton {
    background: transparent;
    border: 0;
    border-radius: 6px;
}
QPushButton#IconButton:hover {
    background: #202832;
}
QPushButton#IconButton:pressed {
    background: #2a333e;
}
QPushButton#SendButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f6a23b, stop:1 #ba6918);
    border: 1px solid #c7771d;
    border-radius: 6px;
}
QPushButton#SendButton:hover {
    background: #f2a94a;
}
QPushButton#StopButton {
    background: rgba(255, 87, 87, 0.12);
    border: 1px solid #ff5757;
    border-radius: 22px;
}
QPushButton#WindowButton {
    background: transparent;
    border: 0;
    color: #c9d0d8;
    font-size: 16px;
}
QPushButton#WindowButton:hover {
    background: #242b34;
}
QPushButton#CloseButton {
    background: transparent;
    border: 0;
    color: #c9d0d8;
    font-size: 16px;
}
QPushButton#CloseButton:hover {
    background: #b73a3a;
    color: #ffffff;
}
QListWidget {
    background: transparent;
    border: 0;
    outline: 0;
}
QListWidget::item {
    padding: 4px 4px;
}
QPlainTextEdit {
    background: #0d1116;
    border: 0;
    border-radius: 6px;
    color: #d8dde3;
    padding: 10px;
    selection-background-color: #f49a23;
    font-family: "Consolas";
    font-size: 12px;
}
QProgressBar {
    background: #10151b;
    border: 1px solid #303842;
    border-radius: 3px;
    height: 6px;
    text-align: center;
}
QProgressBar::chunk {
    background: #22c3e4;
    border-radius: 3px;
}
QScrollArea {
    background: transparent;
    border: 0;
}
QScrollBar:vertical {
    background: #0f141a;
    border: 0;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #5b6470;
    border-radius: 4px;
    min-height: 40px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
"""


class BrainLoader(QObject):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, project_root: Path) -> None:
        super().__init__()
        self.project_root = project_root

    def run(self) -> None:
        try:
            from core.brain import Brain

            self.ready.emit(Brain.create(self.project_root))
        except Exception as error:
            self.failed.emit(str(error))


class AssistantWorker(QObject):
    chunk = pyqtSignal(str)
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, brain: object, prompt: str) -> None:
        super().__init__()
        self.brain = brain
        self.prompt = prompt

    def run(self) -> None:
        parts: list[str] = []
        try:
            answer_stream = getattr(self.brain, "answer_stream")
            for chunk in answer_stream(self.prompt):
                if not chunk:
                    continue
                parts.append(str(chunk))
                self.chunk.emit(str(chunk))
            self.finished.emit("".join(parts))
        except Exception as error:
            self.failed.emit(str(error))


class HudIconButton(QPushButton):
    def __init__(self, kind: str, tooltip: str = "", accent: QColor | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.accent = accent or TEXT
        self.setObjectName("IconButton")
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(36, 36)
        self.setText("")

    def sizeHint(self) -> QSize:
        return QSize(36, 36)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(self.accent)
        if not self.isEnabled():
            color = QColor("#59616c")
        pen = QPen(color, 1.7)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        r = self.rect().adjusted(9, 9, -9, -9)
        cx = self.width() / 2
        cy = self.height() / 2

        if self.kind == "menu":
            for y in (12, 18, 24):
                painter.drawLine(11, y, 25, y)
        elif self.kind == "chat":
            painter.drawRoundedRect(QRectF(10, 11, 16, 12), 3, 3)
            painter.drawLine(16, 23, 14, 27)
            painter.drawLine(14, 27, 20, 23)
            painter.drawPoint(15, 17)
            painter.drawPoint(18, 17)
            painter.drawPoint(21, 17)
        elif self.kind == "grid":
            for x in (11, 20):
                for y in (11, 20):
                    painter.drawRect(x, y, 5, 5)
        elif self.kind == "pulse":
            path = QPainterPath()
            path.moveTo(9, 18)
            path.lineTo(13, 18)
            path.lineTo(15, 13)
            path.lineTo(19, 25)
            path.lineTo(22, 11)
            path.lineTo(24, 18)
            path.lineTo(28, 18)
            painter.drawPath(path)
        elif self.kind == "gear":
            painter.drawEllipse(QRectF(cx - 5, cy - 5, 10, 10))
            for index in range(8):
                angle = math.tau * index / 8
                painter.drawLine(
                    int(cx + math.cos(angle) * 8),
                    int(cy + math.sin(angle) * 8),
                    int(cx + math.cos(angle) * 11),
                    int(cy + math.sin(angle) * 11),
                )
        elif self.kind == "search":
            painter.drawEllipse(QRectF(11, 10, 12, 12))
            painter.drawLine(21, 21, 27, 27)
        elif self.kind == "trash":
            painter.drawLine(12, 13, 25, 13)
            painter.drawLine(16, 10, 21, 10)
            painter.drawRoundedRect(QRectF(14, 15, 9, 12), 2, 2)
            painter.drawLine(17, 17, 17, 25)
            painter.drawLine(20, 17, 20, 25)
        elif self.kind == "mic":
            painter.drawRoundedRect(QRectF(15, 9, 7, 14), 3, 3)
            painter.drawArc(QRectF(11, 15, 15, 12), 200 * 16, 140 * 16)
            painter.drawLine(18, 27, 18, 30)
            painter.drawLine(14, 30, 22, 30)
        elif self.kind == "send":
            painter.setBrush(QBrush(color))
            path = QPainterPath()
            path.moveTo(10, 10)
            path.lineTo(28, 18)
            path.lineTo(10, 26)
            path.lineTo(14, 18)
            path.closeSubpath()
            painter.drawPath(path)
        elif self.kind == "folder":
            path = QPainterPath()
            path.moveTo(9, 13)
            path.lineTo(15, 13)
            path.lineTo(17, 10)
            path.lineTo(25, 10)
            path.lineTo(27, 14)
            path.lineTo(27, 26)
            path.lineTo(9, 26)
            path.closeSubpath()
            painter.drawPath(path)
        elif self.kind == "image":
            painter.drawRoundedRect(QRectF(10, 11, 17, 14), 2, 2)
            painter.drawEllipse(QRectF(13, 14, 3, 3))
            path = QPainterPath()
            path.moveTo(12, 23)
            path.lineTo(17, 18)
            path.lineTo(20, 21)
            path.lineTo(23, 17)
            path.lineTo(26, 23)
            painter.drawPath(path)
        elif self.kind == "terminal":
            painter.drawRoundedRect(QRectF(10, 12, 17, 13), 2, 2)
            painter.drawLine(14, 16, 17, 18)
            painter.drawLine(17, 18, 14, 20)
            painter.drawLine(19, 21, 24, 21)
        elif self.kind == "refresh":
            painter.drawArc(QRectF(11, 11, 15, 15), 25 * 16, 290 * 16)
            painter.drawLine(25, 12, 26, 18)
            painter.drawLine(25, 12, 20, 13)
        elif self.kind == "more":
            painter.setBrush(QBrush(color))
            for x in (13, 18, 23):
                painter.drawEllipse(QRectF(x, 17, 3, 3))
        elif self.kind == "open":
            painter.drawRect(11, 14, 11, 11)
            painter.drawLine(19, 11, 26, 11)
            painter.drawLine(26, 11, 26, 18)
            painter.drawLine(26, 11, 17, 20)
        elif self.kind == "stop":
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(QRectF(14, 14, 9, 9), 2, 2)
        elif self.kind == "dot":
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QRectF(15, 15, 6, 6))


class MiniIcon(HudIconButton):
    def __init__(self, kind: str, color: QColor | None = None, parent: QWidget | None = None) -> None:
        super().__init__(kind, accent=color or ACCENT, parent=parent)
        self.setFixedSize(30, 30)
        self.setCursor(Qt.ArrowCursor)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)


class LogoDot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(28, 28)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center = self.rect().center()
        painter.setPen(QPen(QColor("#8d5316"), 1))
        painter.setBrush(QColor("#171d24"))
        painter.drawEllipse(QRectF(5, 5, 18, 18))
        painter.setPen(QPen(ACCENT, 2))
        painter.drawArc(QRectF(7, 7, 14, 14), 30 * 16, 300 * 16)
        painter.setBrush(ACCENT)
        painter.drawEllipse(QRectF(center.x() - 2, center.y() - 2, 4, 4))


class TitleBar(QFrame):
    def __init__(self, window: QMainWindow) -> None:
        super().__init__()
        self.window = window
        self.drag_origin: QPoint | None = None
        self.setObjectName("TitleBar")
        self.setFixedHeight(46)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)
        layout.addWidget(LogoDot())
        title = QLabel("JARVIS")
        title.setObjectName("TitleJarvis")
        layout.addWidget(title)
        layout.addStretch(1)

        minimize = QPushButton("_")
        minimize.setObjectName("WindowButton")
        minimize.setFixedSize(42, 34)
        minimize.clicked.connect(window.showMinimized)
        maximize = QPushButton("[]")
        maximize.setObjectName("WindowButton")
        maximize.setFixedSize(42, 34)
        maximize.clicked.connect(self._toggle_maximize)
        close = QPushButton("X")
        close.setObjectName("CloseButton")
        close.setFixedSize(42, 34)
        close.clicked.connect(window.close)
        layout.addWidget(minimize)
        layout.addWidget(maximize)
        layout.addWidget(close)

    def _toggle_maximize(self) -> None:
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self.drag_origin = event.globalPos() - self.window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self.drag_origin is not None and event.buttons() & Qt.LeftButton and not self.window.isMaximized():
            self.window.move(event.globalPos() - self.drag_origin)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self.drag_origin = None


class SparklineWidget(QWidget):
    def __init__(self, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color = color
        self.values: list[float] = [0.0] * 42
        self.setMinimumWidth(120)
        self.setFixedHeight(24)

    def add_value(self, value: float) -> None:
        self.values = (self.values + [max(0.0, min(100.0, value))])[-42:]
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(2, 3, -2, -3)
        if len(self.values) < 2:
            return
        painter.setPen(QPen(QColor(self.color.red(), self.color.green(), self.color.blue(), 130), 1.2))
        step = rect.width() / max(1, len(self.values) - 1)
        path = QPainterPath()
        for index, value in enumerate(self.values):
            x = rect.left() + index * step
            y = rect.bottom() - (value / 100.0) * rect.height()
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.drawPath(path)


class WaveformWidget(QWidget):
    def __init__(self, color: QColor = CYAN, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color = color
        self.phase = 0.0
        self.active = True
        self.setMinimumHeight(38)
        self.timer = QTimer(self)
        self.timer.setInterval(45)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def set_active(self, active: bool) -> None:
        self.active = active
        self.update()

    def _tick(self) -> None:
        if self.active:
            self.phase += 0.16
            self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(6, 6, -6, -6)
        center_y = rect.center().y()
        bars = 48
        step = rect.width() / bars
        color = QColor(self.color)
        if not self.active:
            color = QColor("#47515e")
        painter.setPen(QPen(color, 1.3))
        for index in range(bars):
            x = rect.left() + index * step
            wave = math.sin(self.phase + index * 0.62) * 0.55 + math.sin(self.phase * 0.7 + index * 0.21) * 0.45
            envelope = math.sin((index / bars) * math.pi)
            height = 5 + abs(wave) * envelope * rect.height()
            painter.drawLine(int(x), int(center_y - height / 2), int(x), int(center_y + height / 2))


class OrbWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.phase = 0.0
        self.setMinimumSize(440, 440)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _tick(self) -> None:
        self.phase = (self.phase + 1.4) % 360.0
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height()) - 24
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        center = rect.center()

        glow = QRadialGradient(center, side * 0.48)
        glow.setColorAt(0.0, QColor(244, 154, 35, 65))
        glow.setColorAt(0.32, QColor(244, 154, 35, 20))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(glow))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(rect)

        self._draw_ticks(painter, center, side * 0.42, side * 0.46, 120)
        self._draw_ring(painter, rect, 0.88, QColor(141, 83, 18), 1.1)
        self._draw_ring(painter, rect, 0.78, QColor(244, 154, 35), 1.2)
        self._draw_ring(painter, rect, 0.59, QColor(244, 154, 35), 1.3)
        self._draw_ring(painter, rect, 0.43, QColor(244, 154, 35), 1.2)

        self._draw_arc_band(painter, rect, 0.76, 18, 82, QColor(202, 133, 38, 190), width=22)
        self._draw_arc_band(painter, rect, 0.60, 170, 102, QColor(202, 133, 38, 170), width=20)
        self._draw_arc_band(painter, rect, 0.36, 230, 90, QColor(202, 133, 38, 160), width=12)

        self._draw_arc_line(painter, rect, 0.91, self.phase + 7, 36, CYAN, 4.0)
        self._draw_arc_line(painter, rect, 0.66, -self.phase * 0.7 + 40, 58, ACCENT, 2.0)
        self._draw_arc_line(painter, rect, 0.51, self.phase * 1.2 + 180, 68, ACCENT, 2.2)
        self._draw_arc_line(painter, rect, 0.82, -self.phase + 205, 18, CYAN, 3.8)

        painter.setPen(QPen(QColor(244, 154, 35, 150), 2))
        for angle in (0, 90, 180, 270):
            radians = math.radians(angle)
            r1 = side * 0.39
            r2 = side * 0.43
            painter.drawLine(
                int(center.x() + math.cos(radians) * r1),
                int(center.y() + math.sin(radians) * r1),
                int(center.x() + math.cos(radians) * r2),
                int(center.y() + math.sin(radians) * r2),
            )

        core_rect = QRectF(center.x() - side * 0.085, center.y() - side * 0.085, side * 0.17, side * 0.17)
        core = QRadialGradient(core_rect.center(), core_rect.width() * 0.7)
        core.setColorAt(0.0, QColor("#fff1b8"))
        core.setColorAt(0.25, QColor("#ffc24a"))
        core.setColorAt(0.65, QColor("#f49a23"))
        core.setColorAt(1.0, QColor(244, 154, 35, 0))
        painter.setBrush(QBrush(core))
        painter.setPen(QPen(QColor(244, 154, 35, 210), 2))
        painter.drawEllipse(core_rect)

        inner = QRectF(center.x() - side * 0.15, center.y() - side * 0.15, side * 0.30, side * 0.30)
        gradient = QConicalGradient(center, -self.phase)
        gradient.setColorAt(0.0, QColor(244, 154, 35, 30))
        gradient.setColorAt(0.55, QColor(244, 154, 35, 170))
        gradient.setColorAt(1.0, QColor(244, 154, 35, 30))
        painter.setPen(QPen(QBrush(gradient), 4))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(inner)

    def _draw_ticks(self, painter: QPainter, center, inner: float, outer: float, count: int) -> None:
        painter.setPen(QPen(QColor(94, 106, 122, 80), 1))
        for index in range(count):
            angle = math.tau * index / count
            length = outer if index % 5 else outer + 6
            painter.drawLine(
                int(center.x() + math.cos(angle) * inner),
                int(center.y() + math.sin(angle) * inner),
                int(center.x() + math.cos(angle) * length),
                int(center.y() + math.sin(angle) * length),
            )

    def _draw_ring(self, painter: QPainter, rect: QRectF, scale: float, color: QColor, width: float) -> None:
        ring = _scaled_rect(rect, scale)
        painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 110), width))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(ring)

    def _draw_arc_band(
        self,
        painter: QPainter,
        rect: QRectF,
        scale: float,
        start: float,
        span: float,
        color: QColor,
        *,
        width: float,
    ) -> None:
        ring = _scaled_rect(rect, scale)
        painter.setPen(QPen(color, width, Qt.SolidLine, Qt.FlatCap))
        painter.drawArc(ring, int((start + self.phase * 0.18) * 16), int(span * 16))

    def _draw_arc_line(
        self,
        painter: QPainter,
        rect: QRectF,
        scale: float,
        start: float,
        span: float,
        color: QColor,
        width: float,
    ) -> None:
        ring = _scaled_rect(rect, scale)
        painter.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(ring, int(start * 16), int(span * 16))


def _scaled_rect(rect: QRectF, scale: float) -> QRectF:
    side = min(rect.width(), rect.height()) * scale
    return QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)


class Card(QFrame):
    def __init__(
        self,
        title: str,
        icon: str,
        actions: Iterable[HudIconButton] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(0, 0, 0, 0)
        self.outer.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(14, 8, 10, 8)
        header.setSpacing(8)
        header.addWidget(MiniIcon(icon, ACCENT))
        label = QLabel(title)
        label.setObjectName("PanelTitle")
        header.addWidget(label)
        header.addStretch(1)
        for action in actions:
            header.addWidget(action)
        self.outer.addLayout(header)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: #303842;")
        self.outer.addWidget(line)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(14, 10, 14, 12)
        self.body.setSpacing(8)
        self.outer.addLayout(self.body)


class Avatar(QWidget):
    def __init__(self, kind: str, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.color = color
        self.setFixedSize(42, 42)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(3, 3, 36, 36)
        painter.setPen(QPen(self.color, 1.7))
        painter.setBrush(QColor(20, 25, 31))
        painter.drawEllipse(rect)
        if self.kind == "jarvis":
            painter.drawArc(rect.adjusted(7, 7, -7, -7), 20 * 16, 310 * 16)
            painter.setBrush(self.color)
            painter.drawEllipse(QRectF(18, 18, 6, 6))
        else:
            painter.setBrush(self.color)
            painter.drawEllipse(QRectF(17, 10, 8, 8))
            painter.drawRoundedRect(QRectF(12, 20, 18, 10), 8, 8)


class ChatMessage(QWidget):
    def __init__(self, role: str, speaker: str, text: str, color: QColor) -> None:
        super().__init__()
        self.setObjectName("MessageBubble")
        self.setAutoFillBackground(False)
        self.role = role
        self.raw_text = text
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(10)
        layout.addWidget(Avatar("jarvis" if role == "assistant" else "user", color), 0, Qt.AlignTop)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        name = QLabel(speaker)
        name.setStyleSheet(f"color: {color.name()}; font-weight: 650;")
        timestamp = QLabel(time.strftime("%H:%M:%S"))
        timestamp.setObjectName("Muted")
        top.addWidget(name)
        top.addStretch(1)
        top.addWidget(timestamp)
        column.addLayout(top)
        self.text_label = QLabel()
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.text_label.setStyleSheet("font-size: 14px; line-height: 1.25; color: #d8dde3;")
        column.addWidget(self.text_label)
        layout.addLayout(column, 1)
        self.set_text(text)

    def append_text(self, text: str) -> None:
        self.raw_text += text
        self.set_text(self.raw_text)

    def set_text(self, text: str) -> None:
        self.raw_text = text
        escaped = _html_escape(text).replace("\n", "<br>")
        self.text_label.setText(escaped)


class ChatPanel(Card):
    submitted = pyqtSignal(str)

    def __init__(self, user_name: str = "Krish", ai_name: str = "JARVIS") -> None:
        self.search_button = HudIconButton("search", "Search chat")
        self.clear_button = HudIconButton("trash", "Clear visible chat")
        super().__init__("CHAT", "chat", actions=(self.search_button, self.clear_button))
        self.user_name = user_name
        self.ai_name = ai_name
        self.current_assistant: ChatMessage | None = None
        self.pending_stream = ""

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setAutoFillBackground(False)
        self.scroll.setStyleSheet("background: transparent; border: 0;")
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.viewport().setStyleSheet("background: transparent;")
        self.scroll_content = QWidget()
        self.scroll_content.setAutoFillBackground(False)
        self.scroll_content.setStyleSheet("background: transparent;")
        self.messages = QVBoxLayout(self.scroll_content)
        self.messages.setContentsMargins(4, 4, 8, 4)
        self.messages.setSpacing(6)
        self.messages.addStretch(1)
        self.scroll.setWidget(self.scroll_content)
        self.body.addWidget(self.scroll, 1)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 4, 0, 0)
        input_row.setSpacing(10)
        self.command = QLineEdit()
        self.command.setObjectName("CommandInput")
        self.command.setPlaceholderText("Type your command...")
        self.command.setMinimumHeight(48)
        self.command.returnPressed.connect(self._submit)
        self.mic_button = HudIconButton("mic", "Voice input")
        self.mic_button.setFixedSize(48, 48)
        self.send_button = HudIconButton("send", "Send command", QColor("#ffffff"))
        self.send_button.setObjectName("SendButton")
        self.send_button.setFixedSize(52, 48)
        self.send_button.clicked.connect(self._submit)
        input_row.addWidget(self.command, 1)
        input_row.addWidget(self.mic_button)
        input_row.addWidget(self.send_button)
        self.body.addLayout(input_row)

        self.flush_timer = QTimer(self)
        self.flush_timer.setInterval(35)
        self.flush_timer.timeout.connect(self.flush_stream)
        self.flush_timer.start()
        self.clear_button.clicked.connect(self.clear_messages)
        self._seed_messages()

    def _seed_messages(self) -> None:
        self.add_assistant_message("Hello, Sir. How can I assist you today?")
        self.add_user_message("Show me the files on my Desktop.")
        self.add_assistant_message(
            "Here are the files on your Desktop:\n\n"
            "- desktop.ini (282 bytes)\n"
            "- notes.txt (1.2 KB)\n"
            "- project.zip (4.8 MB)\n"
            "- image.png (1.1 MB)\n"
            "- report.pdf (532 KB)"
        )
        self.add_user_message("Generate an image of a futuristic city.")
        self.add_assistant_message("Generating image...")

    def _submit(self) -> None:
        text = self.command.text().strip()
        if not text:
            return
        self.command.clear()
        self.submitted.emit(text)

    def set_busy(self, busy: bool) -> None:
        self.command.setEnabled(not busy)
        self.send_button.setEnabled(not busy)

    def clear_messages(self) -> None:
        while self.messages.count() > 1:
            item = self.messages.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.current_assistant = None

    def add_user_message(self, text: str) -> None:
        self._insert_message(ChatMessage("user", self.user_name, text, CYAN))

    def add_assistant_message(self, text: str) -> ChatMessage:
        message = ChatMessage("assistant", self.ai_name, text, ACCENT)
        self._insert_message(message)
        return message

    def start_assistant_stream(self) -> None:
        self.pending_stream = ""
        self.current_assistant = self.add_assistant_message("")

    def queue_stream_chunk(self, text: str) -> None:
        self.pending_stream += text

    def flush_stream(self) -> None:
        if not self.pending_stream or self.current_assistant is None:
            return
        chunk = self.pending_stream
        self.pending_stream = ""
        self.current_assistant.append_text(chunk)
        self._scroll_bottom()

    def finish_stream(self) -> None:
        self.flush_stream()
        self.current_assistant = None

    def _insert_message(self, message: ChatMessage) -> None:
        self.messages.insertWidget(max(0, self.messages.count() - 1), message)
        self._scroll_bottom()

    def _scroll_bottom(self) -> None:
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))


class CorePanel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("CoreCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 22)
        layout.setSpacing(8)

        hero = QLabel("J A R V I S")
        hero.setObjectName("HeroTitle")
        hero.setAlignment(Qt.AlignCenter)
        layout.addWidget(hero)

        status_row = QHBoxLayout()
        status_row.addStretch(1)
        status_row.addWidget(StatusDot(GREEN))
        status_label = QLabel("SYSTEM ONLINE")
        status_label.setStyleSheet("font-size: 13px; letter-spacing: 0;")
        status_row.addWidget(status_label)
        status_row.addStretch(1)
        layout.addLayout(status_row)

        self.orb = OrbWidget()
        layout.addWidget(self.orb, 1)

        pill = QFrame()
        pill.setObjectName("StatusPill")
        pill_layout = QHBoxLayout(pill)
        pill_layout.setContentsMargins(16, 8, 16, 8)
        pill_layout.setSpacing(16)
        left_wave = WaveformWidget(ACCENT)
        right_wave = WaveformWidget(ACCENT)
        left_wave.setMinimumWidth(140)
        right_wave.setMinimumWidth(140)
        text_box = QVBoxLayout()
        caption = QLabel("STATUS")
        caption.setObjectName("Muted")
        self.status = QLabel("Ready")
        self.status.setObjectName("StatusText")
        text_box.addWidget(caption)
        text_box.addWidget(self.status)
        pill_layout.addWidget(left_wave, 1)
        pill_layout.addLayout(text_box)
        pill_layout.addWidget(right_wave, 1)
        layout.addWidget(pill, 0, Qt.AlignHCenter)
        pill.setMinimumWidth(380)

    def set_status(self, text: str, color: QColor = GREEN) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color.name()}; font-size: 19px;")


class StatusDot(QWidget):
    def __init__(self, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color = color
        self.setFixedSize(14, 14)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(self.color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(3, 3, 8, 8))


class FilesPanel(Card):
    def __init__(self) -> None:
        self.refresh_button = HudIconButton("refresh", "Refresh files")
        self.more_button = HudIconButton("more", "More")
        super().__init__("FILES", "folder", actions=(self.refresh_button, self.more_button))
        self.path_label = QLabel()
        self.path_label.setObjectName("PathLabel")
        self.body.addWidget(self.path_label)
        self.list = QListWidget()
        self.body.addWidget(self.list, 1)
        self.refresh_button.clicked.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        desktop = Path.home() / "Desktop"
        if not desktop.exists():
            desktop = Path.home()
        self.path_label.setText(str(desktop))
        self.list.clear()
        try:
            entries = sorted(desktop.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))[:24]
        except OSError as error:
            self.list.addItem(f"Could not read folder: {error}")
            return
        for entry in entries:
            kind = "folder" if entry.is_dir() else "file"
            size = "" if entry.is_dir() else format_size(entry.stat().st_size)
            item = QListWidgetItem(f"{kind}: {entry.name:<34} {size}")
            self.list.addItem(item)


class ImagesPanel(Card):
    def __init__(self) -> None:
        self.more_button = HudIconButton("more", "More")
        super().__init__("IMAGES", "image", actions=(self.more_button,))
        row = QHBoxLayout()
        row.setSpacing(12)
        self.preview = QLabel()
        self.preview.setFixedSize(128, 72)
        self.preview.setStyleSheet("background: #202832; border: 1px solid #3a424d; border-radius: 4px;")
        self.preview.setScaledContents(True)
        row.addWidget(self.preview)
        details = QVBoxLayout()
        self.name = QLabel("No image yet")
        self.name.setStyleSheet("font-size: 14px;")
        self.meta = QLabel("Image generations appear here")
        self.meta.setObjectName("Muted")
        self.state = QLabel("Ready")
        self.state.setObjectName("Green")
        details.addWidget(self.name)
        details.addWidget(self.meta)
        details.addWidget(self.state)
        row.addLayout(details, 1)
        self.body.addLayout(row)
        bottom = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        bottom.addWidget(self.progress, 1)
        bottom.addWidget(HudIconButton("folder", "Open folder"))
        bottom.addWidget(HudIconButton("open", "Open image"))
        bottom.addWidget(HudIconButton("trash", "Clear image"))
        self.body.addLayout(bottom)
        self.refresh_latest()

    def refresh_latest(self) -> None:
        latest = latest_image_file()
        if latest is not None:
            self.set_image(latest, "Completed")

    def set_progress_text(self, text: str) -> None:
        match = re.search(r"Generating image\s+(\d+)\s*/\s*(\d+)", text, flags=re.IGNORECASE)
        if match:
            current = int(match.group(1))
            total = max(1, int(match.group(2)))
            self.progress.setValue(int((current - 1) / total * 100))
            self.state.setText(f"Generating image {current}/{total}")
            self.state.setStyleSheet(f"color: {ACCENT.name()};")

    def set_image(self, path: Path, state: str = "Completed") -> None:
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self.preview.setPixmap(pixmap.scaled(self.preview.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        self.name.setText(shorten_middle(path.name, 42))
        self.name.setToolTip(str(path))
        try:
            width = pixmap.width()
            height = pixmap.height()
            size = format_size(path.stat().st_size)
            self.meta.setText(f"{width} x {height} | {size}")
        except OSError:
            self.meta.setText(str(path.parent))
        self.state.setText(state)
        self.state.setStyleSheet(f"color: {GREEN.name()};")
        self.progress.setValue(100)


class TerminalPanel(Card):
    def __init__(self) -> None:
        self.more_button = HudIconButton("more", "More")
        super().__init__("TERMINAL", "terminal", actions=(self.more_button,))
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlainText(sample_terminal_text())
        self.body.addWidget(self.output, 1)

    def append_result(self, text: str) -> None:
        if not looks_like_tool_output(text):
            return
        self.output.appendPlainText("\n" + text.strip()[:2500])
        self.output.verticalScrollBar().setValue(self.output.verticalScrollBar().maximum())


class VoicePanel(Card):
    def __init__(self) -> None:
        self.more_button = HudIconButton("more", "More")
        super().__init__("VOICE", "mic", actions=(self.more_button,))
        row = QHBoxLayout()
        left = QVBoxLayout()
        self.state = QLabel("Listening...")
        self.state.setObjectName("Green")
        self.waveform = WaveformWidget(CYAN)
        left.addWidget(self.state)
        left.addWidget(self.waveform)
        row.addLayout(left, 1)
        self.stop = HudIconButton("stop", "Toggle listening", RED)
        self.stop.setObjectName("StopButton")
        self.stop.setFixedSize(50, 50)
        self.stop.clicked.connect(self.toggle)
        row.addWidget(self.stop, 0, Qt.AlignCenter)
        self.body.addLayout(row)
        self.active = True

    def toggle(self) -> None:
        self.active = not self.active
        self.waveform.set_active(self.active)
        if self.active:
            self.state.setText("Listening...")
            self.state.setStyleSheet(f"color: {GREEN.name()};")
        else:
            self.state.setText("Idle")
            self.state.setStyleSheet(f"color: {MUTED.name()};")


class MetricWidget(QFrame):
    def __init__(self, label: str, color: QColor) -> None:
        super().__init__()
        self.label = label
        self.color = color
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(10)
        self.icon = StatusDot(color)
        self.title = QLabel(label)
        self.title.setStyleSheet(f"color: {color.name()}; font-weight: 600;")
        self.value = QLabel("--")
        self.value.setStyleSheet("color: #d8dde3;")
        self.spark = SparklineWidget(color)
        layout.addWidget(self.icon)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.spark)

    def set_value(self, text: str, numeric: float = 0.0) -> None:
        self.value.setText(text)
        self.spark.add_value(numeric)


class TelemetryBar(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("TelemetryBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)
        self.cpu = MetricWidget("CPU", CYAN)
        self.ram = MetricWidget("RAM", CYAN)
        self.net = MetricWidget("NET", CYAN)
        self.time_metric = MetricWidget("TIME", CYAN)
        self.date_metric = MetricWidget("DATE", CYAN)
        for widget in (self.cpu, self.ram, self.net, self.time_metric, self.date_metric):
            layout.addWidget(widget, 1)
        self.last_net_bytes = 0
        self.last_net_time = time.time()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self) -> None:
        cpu, ram, net_kb = read_system_metrics(self.last_net_bytes, self.last_net_time)
        self.last_net_bytes = net_kb[1]
        self.last_net_time = time.time()
        self.cpu.set_value("--" if cpu is None else f"{cpu:.0f}%", cpu or 0)
        self.ram.set_value("--" if ram is None else f"{ram:.0f}%", ram or 0)
        self.net.set_value(f"{net_kb[0]:.1f} KB/s", min(100, net_kb[0]))
        now = time.localtime()
        self.time_metric.set_value(time.strftime("%H:%M:%S", now), now.tm_sec * 100 / 59)
        self.date_metric.set_value(time.strftime("%d-%m-%Y", now), 100)


class JarvisWindow(QMainWindow):
    def __init__(self, project_root: Path, *, load_brain: bool = True) -> None:
        super().__init__()
        self.project_root = project_root
        self.brain: object | None = None
        self.loader_thread: QThread | None = None
        self.loader_worker: BrainLoader | None = None
        self.stream_thread: QThread | None = None
        self.stream_worker: AssistantWorker | None = None
        self.setWindowTitle("JARVIS")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setMinimumSize(1180, 720)
        self.resize(1440, 820)

        root = QFrame()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(4, 4, 4, 4)
        root_layout.setSpacing(8)
        root_layout.addWidget(TitleBar(self))

        main = QHBoxLayout()
        main.setContentsMargins(8, 0, 8, 0)
        main.setSpacing(10)
        left = QVBoxLayout()
        left.setSpacing(8)
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setMinimumWidth(410)
        left_widget.setMaximumWidth(520)
        left.addWidget(self._nav_strip())
        self.chat = ChatPanel()
        self.chat.submitted.connect(self.submit_prompt)
        left.addWidget(self.chat, 1)

        self.core = CorePanel()

        right_widget = QWidget()
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        right_widget.setMinimumWidth(390)
        right_widget.setMaximumWidth(520)
        self.files = FilesPanel()
        self.images = ImagesPanel()
        self.terminal = TerminalPanel()
        self.voice = VoicePanel()
        right.addWidget(self.files, 2)
        right.addWidget(self.images, 2)
        right.addWidget(self.terminal, 2)
        right.addWidget(self.voice, 1)

        main.addWidget(left_widget, 32)
        main.addWidget(self.core, 37)
        main.addWidget(right_widget, 31)
        root_layout.addLayout(main, 1)
        self.telemetry = TelemetryBar()
        self.telemetry.setFixedHeight(48)
        root_layout.addWidget(self.telemetry)

        self.setStyleSheet(APP_QSS)
        if load_brain:
            self._start_brain_loader()
        else:
            self.core.set_status("Preview", ACCENT)

    def _nav_strip(self) -> QFrame:
        strip = QFrame()
        strip.setObjectName("NavStrip")
        strip.setFixedHeight(48)
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(18)
        for kind, tip in (
            ("menu", "Menu"),
            ("chat", "Chat"),
            ("grid", "Tools"),
            ("pulse", "Activity"),
            ("gear", "Settings"),
        ):
            layout.addWidget(HudIconButton(kind, tip))
        layout.addStretch(1)
        return strip

    def _start_brain_loader(self) -> None:
        self.core.set_status("Loading", ACCENT)
        self.chat.set_busy(True)
        self.loader_thread = QThread(self)
        loader = BrainLoader(self.project_root)
        self.loader_worker = loader
        loader.moveToThread(self.loader_thread)
        self.loader_thread.started.connect(loader.run)
        loader.ready.connect(self._brain_ready)
        loader.failed.connect(self._brain_failed)
        loader.ready.connect(loader.deleteLater)
        loader.failed.connect(loader.deleteLater)
        self.loader_thread.finished.connect(self.loader_thread.deleteLater)
        self.loader_thread.start()

    def _brain_ready(self, brain: object) -> None:
        self.brain = brain
        self.loader_worker = None
        ai_name = str(getattr(brain, "ai_name", "JARVIS"))
        user_name = str(getattr(brain, "user_name", "Krish"))
        self.chat.ai_name = ai_name
        self.chat.user_name = user_name
        self.core.set_status("Ready", GREEN)
        self.chat.set_busy(False)
        if self.loader_thread is not None:
            self.loader_thread.quit()

    def _brain_failed(self, message: str) -> None:
        self.loader_worker = None
        self.core.set_status("Brain error", RED)
        self.chat.set_busy(False)
        self.chat.add_assistant_message(f"Frontend loaded, but Brain failed to start:\n{message}")
        if self.loader_thread is not None:
            self.loader_thread.quit()

    def submit_prompt(self, text: str) -> None:
        self.chat.add_user_message(text)
        if self.brain is None:
            self.chat.add_assistant_message("Brain is still loading. Try again in a moment.")
            return
        if self.stream_thread is not None and self.stream_thread.isRunning():
            self.chat.add_assistant_message("I am still finishing the previous command.")
            return

        self.chat.start_assistant_stream()
        self.chat.set_busy(True)
        self.core.set_status("Thinking", ACCENT)
        self.images.set_progress_text(text)

        self.stream_thread = QThread(self)
        self.stream_worker = AssistantWorker(self.brain, text)
        self.stream_worker.moveToThread(self.stream_thread)
        self.stream_thread.started.connect(self.stream_worker.run)
        self.stream_worker.chunk.connect(self._stream_chunk)
        self.stream_worker.finished.connect(self._stream_finished)
        self.stream_worker.failed.connect(self._stream_failed)
        self.stream_worker.finished.connect(self.stream_worker.deleteLater)
        self.stream_worker.failed.connect(self.stream_worker.deleteLater)
        self.stream_thread.finished.connect(self.stream_thread.deleteLater)
        self.stream_thread.start()

    def _stream_chunk(self, chunk: str) -> None:
        self.chat.queue_stream_chunk(chunk)
        self.images.set_progress_text(chunk)
        if "Generating image" in chunk:
            self.core.set_status("Generating", ACCENT)

    def _stream_finished(self, answer: str) -> None:
        self.stream_worker = None
        self.chat.finish_stream()
        self.chat.set_busy(False)
        self.core.set_status("Ready", GREEN)
        self.terminal.append_result(answer)
        image_path = first_existing_image_path(answer)
        if image_path is not None:
            self.images.set_image(image_path)
        if self.stream_thread is not None:
            self.stream_thread.quit()

    def _stream_failed(self, message: str) -> None:
        self.stream_worker = None
        self.chat.queue_stream_chunk(f"\nError: {message}")
        self.chat.finish_stream()
        self.chat.set_busy(False)
        self.core.set_status("Error", RED)
        if self.stream_thread is not None:
            self.stream_thread.quit()


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def shorten_middle(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    keep = max(8, (max_chars - 3) // 2)
    return f"{text[:keep]}...{text[-keep:]}"


def latest_image_file() -> Path | None:
    roots = [
        Path.home() / "Pictures" / "ANKITA" / "images",
        Path.home() / ".codex" / "generated_images",
    ]
    newest: Path | None = None
    newest_time = 0.0
    for root in roots:
        if not root.exists():
            continue
        try:
            candidates = root.rglob("*") if root.name == "generated_images" else root.glob("*")
            for path in candidates:
                if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or not path.is_file():
                    continue
                modified = path.stat().st_mtime
                if modified > newest_time:
                    newest = path
                    newest_time = modified
        except OSError:
            continue
    return newest


def first_existing_image_path(text: str) -> Path | None:
    matches = re.findall(r"[A-Za-z]:\\[^\n\r]+?\.(?:png|jpg|jpeg|webp)", text, flags=re.IGNORECASE)
    for raw in matches:
        path = Path(raw.strip().strip('"'))
        if path.exists():
            return path
    return None


def looks_like_tool_output(text: str) -> bool:
    lower = text.lower()
    return any(
        token in lower
        for token in (
            "ps ",
            "directory:",
            "mode",
            "lastwritetime",
            "tool error:",
            "running command",
            "fallback result:",
            "path does not exist",
        )
    )


def sample_terminal_text() -> str:
    home = str(Path.home())
    return (
        f"PS {home}> dir\n"
        f"Directory: {home}\n\n"
        "Mode      LastWriteTime       Length Name\n"
        "----      -------------       ------ ----\n"
        "d-----    01-05-2026 10:21          Documents\n"
        "d-----    01-05-2026 10:21          Downloads\n"
        "d-----    01-05-2026 10:21          Desktop\n\n"
        f"PS {home}>"
    )


def read_system_metrics(last_net_bytes: int, last_net_time: float) -> tuple[float | None, float | None, tuple[float, int]]:
    try:
        import psutil

        cpu = float(psutil.cpu_percent(interval=None))
        ram = float(psutil.virtual_memory().percent)
        counters = psutil.net_io_counters()
        total = int(counters.bytes_sent + counters.bytes_recv)
        elapsed = max(0.1, time.time() - last_net_time)
        if last_net_bytes <= 0:
            rate = 0.0
        else:
            rate = max(0.0, (total - last_net_bytes) / 1024.0 / elapsed)
        return cpu, ram, (rate, total)
    except Exception:
        return None, None, (0.0, last_net_bytes)


def save_window_screenshot(window: JarvisWindow, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap = window.grab()
    pixmap.save(str(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the PyQt5 JARVIS desktop frontend.")
    parser.add_argument("--screenshot", type=Path, help="Save a preview screenshot and exit.")
    parser.add_argument("--demo", action="store_true", help="Open the frontend without loading the assistant Brain.")
    parser.add_argument("--width", type=int, default=1664, help="Initial window width.")
    parser.add_argument("--height", type=int, default=936, help="Initial window height.")
    args = parser.parse_args(argv)

    if args.screenshot:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    app = QApplication(sys.argv[:1])
    app.setApplicationName("JARVIS")
    windows_font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
    if windows_font.exists():
        QFontDatabase.addApplicationFont(str(windows_font))
    window = JarvisWindow(PROJECT_ROOT, load_brain=not args.demo and not args.screenshot)
    window.resize(args.width, args.height)
    window.show()

    if args.screenshot:
        def capture() -> None:
            save_window_screenshot(window, args.screenshot)
            app.quit()

        QTimer.singleShot(900, capture)

    return int(app.exec_())


if __name__ == "__main__":
    raise SystemExit(main())
