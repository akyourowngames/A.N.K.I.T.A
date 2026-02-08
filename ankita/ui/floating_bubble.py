import json
import math
import socket
import sys
import time

from PyQt5.QtCore import QPoint, QTimer, Qt, pyqtSignal, QRect
from PyQt5.QtGui import QColor, QPainter, QPen, QFont, QLinearGradient
from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget, QLineEdit


_UI_STATE_BIND = ("127.0.0.1", 50555)
_UI_CMD_SEND = ("127.0.0.1", 50556)


class FloatingBubble(QWidget):
    clicked = pyqtSignal()
    long_pressed = pyqtSignal()

    def __init__(self):
        super().__init__()

        self.setFixedSize(200, 200) 
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._state = "IDLE"
        self._sleeping = False
        self._last_msg = ""
        self._history = []
        self._success_pulse = 0

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

        # Create mini console for typing
        self._input_panel = _InputPanel(self)
        self._input_panel.hide()
        self._input_panel.submitted.connect(self._on_text_submit)

        self._apply_state("IDLE")
        self._ensure_anim_timer()

        # Position at bottom-right
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 220, screen.height() - 220)

        self.show()

    def _on_text_submit(self, text):
        if text.strip():
            self._history.append(text)
            self._history = self._history[-5:] # Last 5
            self._send_command("text_input", {"text": text})
        self._input_panel.hide()

    def _send_command(self, command: str, extra: dict | None = None) -> None:
        try:
            payload: dict = {"type": "command", "command": str(command)}
            if extra:
                payload.update(extra)
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
            
            if msg.get("type") == "state":
                state = str(msg.get("state") or "")
                if state:
                    self._apply_state(state)
            
            if msg.get("type") == "text":
                self._last_msg = msg.get("text", "")
                self.update()

    def _apply_state(self, state: str) -> None:
        if state == "SUCCESS_PULSE":
            self._success_pulse = 20
            self.update()
            return

        self._state = state
        if state == "SLEEP":
            self._sleeping = True
        elif state in {"IDLE", "LISTENING", "EXECUTING", "WAKE_ACTIVE"}:
            self._sleeping = False

        if self._sleeping:
            self._base_color = QColor(100, 100, 100)
            self._glow_color = QColor(100, 100, 100)
        elif state == "LISTENING":
            self._base_color = QColor(0, 220, 110)
            self._glow_color = QColor(0, 255, 150)
        elif state == "EXECUTING":
            self._base_color = QColor(255, 180, 0)
            self._glow_color = QColor(255, 200, 50)
        elif state == "WAKE_ACTIVE":
            self._base_color = QColor(200, 100, 255)
            self._glow_color = QColor(220, 150, 255)
        else:
            self._base_color = QColor(70, 130, 255)
            self._glow_color = QColor(110, 170, 255)

        self._ensure_anim_timer()
        self.update()

    def _ensure_anim_timer(self) -> None:
        wants_anim = (self._state == "WAKE_ACTIVE") or (self._state == "EXECUTING") or (self._state == "LISTENING")
        if wants_anim and not self._anim_timer.isActive():
            self._anim_timer.start(16)
        if (not wants_anim) and self._anim_timer.isActive():
            self._anim_timer.stop()

    def _on_anim_tick(self) -> None:
        self._pulse_phase += 0.08
        if self._pulse_phase > (2 * math.pi):
            self._pulse_phase -= (2 * math.pi)
        self._spinner_angle = (self._spinner_angle + 8.0) % 360.0
        
        if self._success_pulse > 0:
            self._success_pulse -= 1
            
        self.update()

    def _on_long_press(self) -> None:
        self._long_press_fired = True
        self._send_command("toggle_sleep")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        center_x, center_y = w // 2, h // 2
        
        base_r = 32
        glow_r = base_r + 10

        # Draw Glow
        glow_alpha = 60 + int(20 * math.sin(self._pulse_phase))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self._glow_color.red(), self._glow_color.green(), self._glow_color.blue(), glow_alpha))
        painter.drawEllipse(QPoint(center_x, center_y), glow_r, glow_r)

        # Draw Base
        painter.setBrush(self._base_color)
        painter.drawEllipse(QPoint(center_x, center_y), base_r, base_r)
        
        # Success Pulse Glow
        if self._success_pulse > 0:
            p_r = base_r + (20 - self._success_pulse) * 2
            alpha = int(self._success_pulse * 10)
            painter.setPen(QPen(QColor(0, 255, 100, alpha), 3))
            painter.drawEllipse(QPoint(center_x, center_y), p_r, p_r)

        # State specific visuals
        if self._state == "EXECUTING":
            rect = QRect(center_x - 38, center_y - 38, 76, 76)
            pen = QPen(QColor(255, 255, 255, 200))
            pen.setWidth(4)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawArc(rect, int(-self._spinner_angle * 16), int(-120 * 16))
            self._draw_status_text(painter, "ANKITA Thinking", center_x, center_y + 55)

        elif self._state == "LISTENING":
            for i in range(3):
                r = base_r + 5 + (i * 8 + self._pulse_phase * 6) % 22
                alpha = 160 - int(r * 5)
                if alpha > 0:
                    painter.setPen(QPen(QColor(0, 255, 150, alpha), 2))
                    painter.drawEllipse(QPoint(center_x, center_y), int(r), int(r))
            self._draw_status_text(painter, "Listening...", center_x, center_y + 55)

        elif self._state == "WAKE_ACTIVE":
            self._draw_status_text(painter, "Yes Krish?", center_x, center_y + 55)

        if self._sleeping:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 120))
            painter.drawEllipse(QPoint(center_x + 8, center_y - 10), 4, 4)
            painter.drawEllipse(QPoint(center_x - 8, center_y - 10), 4, 4)
            self._draw_status_text(painter, "Offline", center_x, center_y + 55)

    def _draw_status_text(self, painter, text, x, y):
        painter.setPen(QColor(255, 255, 255))
        font = QFont("Segoe UI", 10, QFont.Bold)
        painter.setFont(font)
        painter.drawText(QRect(x - 90, y, 180, 25), Qt.AlignCenter, text)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        self._press_global = event.globalPos()
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
        if was_long or self._moved:
            return
        
        if self._input_panel.isVisible():
            self._input_panel.hide()
        else:
            self._input_panel.show_at(self.geometry().center())

class _InputPanel(QWidget):
    submitted = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__()
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(320, 70)

        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("Direct command to ANKITA...")
        self.edit.setStyleSheet("""
            QLineEdit {
                background: rgba(20, 20, 20, 240);
                color: #4682ff;
                border: 2px solid #4682ff;
                border-radius: 20px;
                padding: 12px;
                font-family: 'Segoe UI';
                font-size: 13px;
                font-weight: bold;
            }
        """)
        self.edit.returnPressed.connect(self._on_submit)

        layout = QVBoxLayout()
        layout.addWidget(self.edit)
        self.setLayout(layout)

    def show_at(self, pos):
        self.move(pos.x() - 160, pos.y() - 110)
        self.show()
        self.edit.setFocus()
        self.edit.clear()

    def _on_submit(self):
        self.submitted.emit(self.edit.text())

def main() -> None:
    app = QApplication(sys.argv)
    w = FloatingBubble()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
