import json
import math
import socket
import sys
import time

from PyQt5.QtCore import QPoint, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget


_UI_STATE_BIND = ("127.0.0.1", 50555)
_UI_CMD_SEND = ("127.0.0.1", 50556)


class FloatingBubble(QWidget):
    clicked = pyqtSignal()
    long_pressed = pyqtSignal()

    def __init__(self):
        super().__init__()

        self.setFixedSize(74, 74)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._state = "IDLE"
        self._sleeping = False

        self._drag_pos = QPoint()
        self._press_global = QPoint()
        self._press_local = QPoint()
        self._moved = False
        self._long_press_fired = False

        self._pulse_phase = 0.0
        self._spinner_angle = 0.0

        self._base_color = QColor(70, 130, 255)
        self._glow_color = QColor(70, 130, 255)

        self._press_timer = QTimer(self)
        self._press_timer.setSingleShot(True)
        self._press_timer.timeout.connect(self._on_long_press)

        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._on_anim_tick)

        self._state_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._state_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._state_sock.bind(_UI_STATE_BIND)
        except Exception:
            pass
        self._state_sock.setblocking(False)

        self._state_poll_timer = QTimer(self)
        self._state_poll_timer.timeout.connect(self._poll_states)
        self._state_poll_timer.start(40)

        self._cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Create panel early so _apply_state can update it
        self._panel = _MiniPanel()
        self._panel.hide()

        self._apply_state("IDLE")
        self._ensure_anim_timer()

        self.show()

    def _send_command(self, command: str, extra: dict | None = None) -> None:
        try:
            payload: dict = {"type": "command", "command": str(command)}
            if extra:
                payload["extra"] = extra
            data = json.dumps(payload).encode("utf-8")
            self._cmd_sock.sendto(data, _UI_CMD_SEND)
        except Exception:
            return

    def _poll_states(self) -> None:
        while True:
            try:
                data, _ = self._state_sock.recvfrom(65535)
            except BlockingIOError:
                break
            except Exception:
                break
            try:
                msg = json.loads((data or b"").decode("utf-8"))
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("type") != "state":
                continue
            state = str(msg.get("state") or "")
            if state:
                self._apply_state(state)

    def _apply_state(self, state: str) -> None:
        self._state = state
        if state == "SLEEP":
            self._sleeping = True
        elif state in {"IDLE", "LISTENING", "EXECUTING", "WAKE_ACTIVE"}:
            self._sleeping = False

        if self._sleeping:
            self._base_color = QColor(120, 120, 120)
            self._glow_color = QColor(120, 120, 120)
        elif state == "LISTENING":
            self._base_color = QColor(0, 200, 100)
            self._glow_color = QColor(0, 255, 140)
        elif state == "EXECUTING":
            self._base_color = QColor(255, 200, 0)
            self._glow_color = QColor(255, 220, 80)
        else:
            self._base_color = QColor(70, 130, 255)
            self._glow_color = QColor(110, 170, 255)

        self._ensure_anim_timer()
        self._panel.set_state(self._state, self._sleeping)
        self.update()

    def _ensure_anim_timer(self) -> None:
        wants_anim = (self._state == "WAKE_ACTIVE") or (self._state == "EXECUTING")
        if wants_anim and not self._anim_timer.isActive():
            self._anim_timer.start(16)
        if (not wants_anim) and self._anim_timer.isActive():
            self._anim_timer.stop()

    def _on_anim_tick(self) -> None:
        self._pulse_phase += 0.06
        if self._pulse_phase > (2 * math.pi):
            self._pulse_phase -= (2 * math.pi)
        self._spinner_angle = (self._spinner_angle + 6.0) % 360.0
        self.update()

    def _on_long_press(self) -> None:
        self._long_press_fired = True
        self.long_pressed.emit()

    def paintEvent(self, event):
        size = float(min(self.width(), self.height()))
        center = size / 2.0
        padding = 6.0

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        base_r = max(18.0, (size / 2.0) - (padding + 6.0))
        glow_r = base_r + 5.0

        if self._state == "WAKE_ACTIVE":
            t = (math.sin(self._pulse_phase) + 1.0) / 2.0
            ring_alpha = int(40 + 120 * t)
            ring_w = 2 + 3 * t
            max_r = (size / 2.0) - padding - ring_w
            ring_r = min(glow_r + 5.0 + 6.0 * t, max_r)

            pen = QPen(QColor(self._glow_color.red(), self._glow_color.green(), self._glow_color.blue(), ring_alpha))
            pen.setWidthF(ring_w)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPoint(int(center), int(center)), int(ring_r), int(ring_r))

        glow_alpha = 70
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self._glow_color.red(), self._glow_color.green(), self._glow_color.blue(), glow_alpha))
        painter.drawEllipse(QPoint(int(center), int(center)), int(glow_r), int(glow_r))

        painter.setBrush(self._base_color)
        painter.drawEllipse(QPoint(int(center), int(center)), int(base_r), int(base_r))

        if self._state == "EXECUTING":
            arc_r = max(14.0, base_r - 8.0)
            rect = (center - arc_r, center - arc_r, arc_r * 2.0, arc_r * 2.0)
            pen = QPen(QColor(20, 20, 20, 200))
            pen.setWidth(4)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            start_angle = int(-self._spinner_angle * 16)
            span = int(-120 * 16)
            painter.drawArc(int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]), start_angle, span)

        if self._sleeping:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(20, 20, 20, 120))
            painter.drawEllipse(QPoint(int(center + 8), int(center - 10)), 5, 5)
            painter.drawEllipse(QPoint(int(center - 4), int(center - 14)), 3, 3)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        self._press_global = event.globalPos()
        self._press_local = event.pos()
        self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
        self._moved = False
        self._long_press_fired = False
        self._press_timer.start(850)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        delta = event.globalPos() - self._press_global
        if delta.manhattanLength() > 6:
            self._moved = True
            self._press_timer.stop()
        self.move(event.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        was_long = self._long_press_fired
        self._press_timer.stop()
        if was_long:
            return
        if self._moved:
            return
        self.clicked.emit()


class _MiniPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setFixedSize(260, 160)

        self._title = QLabel("Ankita")
        self._state = QLabel("State: IDLE")
        self._hint = QLabel("Click bubble: show/hide\nLong press: sleep/wake")

        self._btn_sleep = QPushButton("Sleep")
        self._btn_close = QPushButton("Close")

        lay = QVBoxLayout()
        lay.addWidget(self._title)
        lay.addWidget(self._state)
        lay.addWidget(self._hint)
        lay.addWidget(self._btn_sleep)
        lay.addWidget(self._btn_close)
        self.setLayout(lay)

        self._sleeping = False

        self._btn_close.clicked.connect(self.hide)

    def set_state(self, state: str, sleeping: bool) -> None:
        self._sleeping = bool(sleeping)
        self._state.setText(f"State: {state}")
        self._btn_sleep.setText("Wake" if self._sleeping else "Sleep")


def main() -> None:
    app = QApplication(sys.argv)
    w = FloatingBubble()

    def _on_click():
        if w._panel.isVisible():
            w._panel.hide()
            return
        pos = w.geometry().topRight()
        w._panel.move(pos.x() + 10, pos.y())
        w._panel.show()
        w._send_command("open_panel")

    def _on_long_press():
        w._send_command("toggle_sleep")

    def _on_panel_sleep_toggle():
        w._send_command("toggle_sleep")

    w._panel._btn_sleep.clicked.connect(_on_panel_sleep_toggle)

    w.clicked.connect(_on_click)
    w.long_pressed.connect(_on_long_press)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
