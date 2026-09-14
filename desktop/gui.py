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
import math

from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QIcon, QMovie, QPainter, QTextCharFormat
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
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


class VoicePanel(QWidget):
    """The same visible microphone controls on both Home and Chat."""

    def __init__(self, bus, parent=None):
        super().__init__(parent)
        self.bus = bus
        self.setStyleSheet('QWidget { color: #e8edf2; background: #101820; font-size: 13px; }'
            'QPushButton { border: 1px solid #516170; border-radius: 7px; padding: 9px 14px; }'
            'QPushButton:disabled { color: #71808c; border-color: #2e3943; }')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        row = QHBoxLayout()
        self.mic = QPushButton()
        self.mic.setCheckable(True)
        self.mic.setMinimumWidth(190)
        self.mic.setAccessibleName('Toggle microphone')
        self.mic.setToolTip('Enable continuous listening. Mute cancels the current recording and stops speech.')
        self.mic.clicked.connect(lambda checked: bus.set_mic(checked))
        row.addWidget(self.mic)
        self.finish = QPushButton('Transcribe now')
        self.finish.setToolTip('Finish this recording and recognize it immediately.')
        self.finish.clicked.connect(lambda: bus.finish_recording.set())
        row.addWidget(self.finish)
        self.capture = QLabel()
        row.addWidget(self.capture, stretch=1)
        self.debug_toggle = QPushButton('Hide debug stages')
        self.debug_toggle.clicked.connect(self.toggle_debug)
        row.addWidget(self.debug_toggle)
        layout.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet('font-size: 16px; font-weight: 600;')
        layout.addWidget(self.status)
        self.device = QLabel()
        self.device.setWordWrap(True)
        layout.addWidget(self.device)
        meter_row = QHBoxLayout()
        self.meter = QProgressBar()
        self.meter.setRange(0, 60)
        self.meter.setTextVisible(False)
        self.meter.setFixedHeight(8)
        self.meter.setStyleSheet('QProgressBar { background: #28343f; border: 0; }'
                                'QProgressBar::chunk { background: #52dbac; }')
        meter_row.addWidget(self.meter, stretch=1)
        self.level = QLabel()
        meter_row.addWidget(self.level)
        layout.addLayout(meter_row)
        self.transcript = QLabel('Last heard: —')
        self.transcript.setWordWrap(True)
        self.transcript.setMaximumHeight(48)
        self.transcript.setTextFormat(Qt.PlainText)
        self.transcript.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.transcript)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.PlainText)
        self.error.setStyleSheet('color: #ffb8a8;')
        layout.addWidget(self.error)
        self.debug = QPlainTextEdit()
        self.debug.setReadOnly(True)
        self.debug.setFixedHeight(82)
        self.debug.setStyleSheet('background: #080d12; color: #a9bbc9; font-size: 12px; border: 0;')
        self.debug.setPlaceholderText('Stage changes appear here with timestamps. No audio is saved.')
        self._last_events = None
        layout.addWidget(self.debug)
        self.refresh()

    def toggle_debug(self):
        visible = self.debug.isHidden()
        self.debug.setVisible(visible)
        self.debug_toggle.setText('Hide debug stages' if visible else 'Show debug stages')

    def refresh(self):
        state = self.bus.snapshot()
        self.mic.setChecked(state['mic_on'])
        self.mic.setText('MIC ON · Mute' if state['mic_on'] else 'MIC OFF · Enable')
        self.mic.setStyleSheet('background: #13533f; color: #d2ffed; border-color: #47ba91;'
                              if state['mic_on'] else 'background: #492b32; color: #ffdade; border-color: #a76773;')
        self.capture.setText('Capturing audio' if state['capture_active'] else
                             ('Mic enabled · capture paused' if state['mic_on'] else 'Muted · no audio captured'))
        self.finish.setEnabled(state['capture_active'] and state['stage'] == 'recording')
        self.status.setText(f"{state['status']}  ·  {state['elapsed']:.1f}s")
        self.device.setText('Input: ' + state['device'])
        db = 20 * math.log10(max(state['level'], 1e-6))
        self.meter.setValue(max(0, int(db + 60)))
        self.level.setText(f"Level {db:.0f} dB  |  gate {state['threshold']:.4f}  |  captured {state['audio_seconds']:.1f}s")
        self.transcript.setText('Last heard: ' + (state['transcript'] or '—'))
        self.error.setText('Last error: ' + state['last_error'] if state['last_error'] else '')
        self.error.setVisible(bool(state['last_error']))
        events = '\n'.join(state['events'])
        if events != self._last_events:
            self._last_events = events
            self.debug.setPlainText(events)
            self.debug.verticalScrollBar().setValue(self.debug.verticalScrollBar().maximum())


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
        self.gif = QLabel()
        self.gif.setStyleSheet("border: none;")
        movie = QMovie(asset("Jarvis.gif"))
        movie.setScaledSize(QSize(160, 90))
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
        self.input.setStyleSheet(
            "QLineEdit { color: white; background-color: rgba(44,62,80,0.85);"
            " border: 2px solid #3498db; border-radius: 10px; padding: 10px;"
            " font-size: 15px; }"
            "QLineEdit:focus { border: 2px solid #2980b9; }"
        )
        self.input.returnPressed.connect(self._submit)
        row.addWidget(self.input, stretch=1)
        submit = QPushButton("Submit")
        submit.setStyleSheet(
            "QPushButton { color: white; background-color: #3498db;"
            " border: 2px solid #2980b9; border-radius: 10px; padding: 10px 22px;"
            " font-size: 15px; }"
            "QPushButton:hover { background-color: #2980b9; }"
        )
        submit.clicked.connect(self._submit)
        row.addWidget(submit)
        layout.addLayout(row)

        self.setStyleSheet("background-color: black;")

    def _submit(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        threading.Thread(target=self.on_submit, args=(text,), daemon=True).start()

    def refresh(self):
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
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(6)

        gif_label = QLabel()
        self.gif = gif_label
        gif_label.setMinimumSize(0, 0)
        gif_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        movie = QMovie(asset("Jarvis.gif"))
        movie.setScaledSize(QSize(480, 270))
        gif_label.setMovie(movie)
        gif_label.setAlignment(Qt.AlignCenter)
        movie.start()
        self._movie = movie
        layout.addWidget(gif_label, stretch=1)
        hint = QLabel('Hindi + English  ·  Enable the mic below, wait for Listening, then speak.')
        hint.setStyleSheet('color: #a9bbc9; font-size: 14px;')
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

        self.setLayout(layout)
        self.setStyleSheet("background-color: black;")

    def toggle_mic(self):
        self.bus.set_mic(not self.bus.mic_on())

    def refresh(self):
        width = max(1, min(760, self.gif.width(), int(self.gif.height() * 16 / 9)))
        size = QSize(width, max(1, int(width * 9 / 16)))
        if self._movie.scaledSize() != size:
            self._movie.setScaledSize(size)


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
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stacked, stretch=1)
        self.voice = VoicePanel(bus)
        layout.addWidget(self.voice)
        self.setCentralWidget(content)
        self.setGeometry(0, 0, width, height)
        self.setStyleSheet("background-color: black;")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(100)

    def _refresh(self):
        if self.bus.shutdown_requested():
            self.close()
            return
        self.home.refresh()
        self.chat.refresh()
        self.voice.refresh()

    def closeEvent(self, event):
        self.bus.request_close()
        super().closeEvent(event)


def run_gui(bus: DesktopBus, on_submit) -> int:
    """Create the app window and block until it closes. Returns exit code."""
    import sys as _sys

    app = QApplication(_sys.argv)
    window = MainWindow(bus, on_submit)
    window.showMaximized()
    return app.exec_()
