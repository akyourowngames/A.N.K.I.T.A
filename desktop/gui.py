"""PyQt5 desktop GUI for Zumba, same design as the Jarvis reference.

Frameless black window + custom white top bar (Home | Chat | minimize |
maximize | close). Two screens on a QStackedWidget:

- home  : fullscreen arc-reactor gif, mic toggle button, status line.
- chat  : scrollable chat log, status line, small gif, text input + Submit.

The GUI never blocks: a 100ms QTimer pulls status lines and chat messages
off the DesktopBus fed by the voice controller.
"""

from __future__ import annotations

import os
import threading

from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QIcon, QMovie, QPainter, QPixmap, QTextCharFormat
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .state import DesktopBus

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def asset(name: str) -> str:
    return os.path.join(ASSETS_DIR, name)


def screen_size(app: QApplication):
    screen = app.primaryScreen()
    if screen is not None:
        geo = screen.geometry()
        return geo.width(), geo.height()
    return 1280, 800


class ChatScreen(QWidget):
    """Message screen: chat log + status + gif + input row."""

    def __init__(self, bus: DesktopBus, on_submit, parent=None):
        super().__init__(parent)
        self.bus = bus
        self.on_submit = on_submit

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setFrameStyle(QFrame.NoFrame)
        self.chat.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.chat.setStyleSheet(
            "QTextEdit { background-color: rgba(0,0,0,0.85); color: white;"
            " font-size: 15px; border-radius: 10px; padding: 10px; }"
        )
        font = QFont()
        font.setPointSize(12)
        self.chat.setFont(font)
        layout.addWidget(self.chat, stretch=3)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 10, 0)
        self.status = QLabel("Available...")
        self.status.setStyleSheet("color: white; font-size: 15px; border: none;")
        self.status.setAlignment(Qt.AlignRight)
        right.addWidget(self.status, alignment=Qt.AlignRight)

        self.gif = QLabel()
        self.gif.setStyleSheet("border: none;")
        movie = QMovie(asset("Jarvis.gif"))
        movie.setScaledSize(QSize(480, 270))
        self.gif.setMovie(movie)
        movie.start()
        self._movie = movie  # keep a reference: QMovie stops when GC'd
        self.gif.setAlignment(Qt.AlignRight)
        right.addWidget(self.gif, alignment=Qt.AlignRight)
        layout.addLayout(right)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask me anything...")
        self.input.setMaximumWidth(420)
        self.input.setStyleSheet(
            "QLineEdit { color: white; background-color: rgba(44,62,80,0.85);"
            " border: 2px solid #3498db; border-radius: 10px; padding: 10px;"
            " font-size: 15px; }"
            "QLineEdit:focus { border: 2px solid #2980b9; }"
        )
        self.input.returnPressed.connect(self._submit)
        row.addWidget(self.input)
        submit = QPushButton("Submit")
        submit.setStyleSheet(
            "QPushButton { color: white; background-color: #3498db;"
            " border: 2px solid #2980b9; border-radius: 10px; padding: 10px 22px;"
            " font-size: 15px; }"
            "QPushButton:hover { background-color: #2980b9; }"
        )
        submit.clicked.connect(self._submit)
        row.addWidget(submit)
        row.addStretch(1)
        layout.addLayout(row)

        self.setStyleSheet("background-color: black;")

    def _submit(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        threading.Thread(target=self.on_submit, args=(text,), daemon=True).start()

    def refresh(self):
        self.status.setText(self.bus.get_status())
        for message in self.bus.drain_messages():
            cursor = self.chat.textCursor()
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("white"))
            cursor.setCharFormat(fmt)
            cursor.insertText(message + "\n")
            self.chat.setTextCursor(cursor)
            self.chat.ensureCursorVisible()


class HomeScreen(QWidget):
    """Initial screen: fullscreen gif, mic toggle, status line."""

    def __init__(self, bus: DesktopBus, width: int, height: int, parent=None):
        super().__init__(parent)
        self.bus = bus

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 24)
        layout.setSpacing(6)

        gif_label = QLabel()
        movie = QMovie(asset("Jarvis.gif"))
        zoomed = int(width * 1.3)
        movie.setScaledSize(QSize(zoomed, int(zoomed / 16 * 9)))
        gif_label.setMovie(movie)
        gif_label.setAlignment(Qt.AlignCenter)
        movie.start()
        self._movie = movie
        layout.addWidget(gif_label, alignment=Qt.AlignCenter)

        self.status = QLabel("Available...")
        self.status.setStyleSheet("color: white; font-size: 15px;")
        layout.addWidget(self.status, alignment=Qt.AlignCenter)

        self.mic = QLabel()
        self.mic.setFixedSize(76, 76)
        self.mic.setAlignment(Qt.AlignCenter)
        self.mic.setCursor(Qt.PointingHandCursor)
        self.mic.mousePressEvent = lambda _event: self.toggle_mic()
        layout.addWidget(self.mic, alignment=Qt.AlignCenter)
        self._paint_mic()

        self.setLayout(layout)
        self.setStyleSheet("background-color: black;")

    def _paint_mic(self):
        pixmap = QPixmap(asset("Mic_on.png") if self.bus.mic_on() else asset("Mic_off.png"))
        self.mic.setPixmap(pixmap.scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def toggle_mic(self):
        self.bus.set_mic(not self.bus.mic_on())
        self._paint_mic()

    def refresh(self):
        self.status.setText(self.bus.get_status())
        self._paint_mic()


class TopBar(QWidget):
    def __init__(self, parent: QMainWindow, stacked: QStackedWidget, title: str):
        super().__init__(parent)
        self.setFixedHeight(50)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 8, 4)

        title_label = QLabel(title)
        title_label.setStyleSheet("color: black; font-size: 18px; background-color: white;")
        layout.addWidget(title_label)
        layout.addStretch(1)

        def _button(icon_name: str, text: str = ""):
            button = QPushButton()
            button.setIcon(QIcon(asset(icon_name)))
            if text:
                button.setText(text)
            button.setStyleSheet(
                "height: 40px; background-color: white; color: black; border: none; padding: 0 10px;"
            )
            button.setCursor(Qt.PointingHandCursor)
            return button

        home = _button("Home.png", " Home")
        home.clicked.connect(lambda: stacked.setCurrentIndex(0))
        chat = _button("Chats.png", " Chat")
        chat.clicked.connect(lambda: stacked.setCurrentIndex(1))
        layout.addWidget(home)
        layout.addWidget(chat)
        layout.addStretch(1)

        minimize = _button("Minimize2.png")
        minimize.clicked.connect(parent.showMinimized)
        layout.addWidget(minimize)

        self.maximize = _button("Maximize.png")
        self.maximize.clicked.connect(self._toggle_maximize)
        layout.addWidget(self.maximize)

        close = _button("Close.png")
        close.clicked.connect(parent.close)
        layout.addWidget(close)

    def _toggle_maximize(self):
        window = self.parent()
        if window.isMaximized():
            window.showNormal()
            self.maximize.setIcon(QIcon(asset("Maximize.png")))
        else:
            window.showMaximized()
            self.maximize.setIcon(QIcon(asset("Minimize.png")))

    def paintEvent(self, event):  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.white)
        super().paintEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, bus: DesktopBus, on_submit):
        super().__init__()
        self.bus = bus
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setWindowTitle(f"{bus.assistant_name} AI")

        app = QApplication.instance()
        width, height = screen_size(app) if app is not None else (1280, 800)

        self.stacked = QStackedWidget(self)
        self.home = HomeScreen(bus, width, height)
        self.chat = ChatScreen(bus, on_submit)
        self.stacked.addWidget(self.home)
        self.stacked.addWidget(self.chat)

        self.setMenuWidget(TopBar(self, self.stacked, f"{bus.assistant_name} AI"))
        self.setCentralWidget(self.stacked)
        self.setGeometry(0, 0, width, height)
        self.setStyleSheet("background-color: black;")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(100)

    def _refresh(self):
        self.home.refresh()
        self.chat.refresh()


def run_gui(bus: DesktopBus, on_submit) -> int:
    """Create the app window and block until it closes. Returns exit code."""
    import sys as _sys

    app = QApplication(_sys.argv)
    window = MainWindow(bus, on_submit)
    bus.on_close(window.close)
    window.showMaximized()
    return app.exec_()
