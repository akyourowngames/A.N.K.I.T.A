import base64
import io
import os
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv
from PyQt5.QtCore import (
    QThread, pyqtSignal, Qt, QTimer, QPoint, QRect, QRectF,
    QPropertyAnimation, pyqtProperty, QEasingCurve, QSize
)
from PyQt5.QtGui import (
    QColor, QPainter, QPainterPath, QLinearGradient,
    QRadialGradient, QFont, QIcon, QPixmap, QBrush, QPen
)
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QGraphicsDropShadowEffect,
)

from agent_runtime import AgentRuntime, new_session
from agents import Orchestrator
from corn import CornRunner
from llm import build_runtime_from_env
from memory import MemoryStore
from proactive import ProactiveEngine
import voice_web

WORKSPACE_ROOT = Path.cwd().resolve()

try:
    import numpy as np  # type: ignore
    import sounddevice as sd  # type: ignore

    HAS_AUDIO_STACK = True
except Exception:
    HAS_AUDIO_STACK = False

try:
    import speech_recognition as sr  # type: ignore

    HAS_SPEECH_RECOGNITION = True
except Exception:
    HAS_SPEECH_RECOGNITION = False

try:
    from pynput import keyboard as pynput_keyboard  # type: ignore

    HAS_PYNPUT = True
except Exception:
    HAS_PYNPUT = False


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


class AskWorker(QThread):
    done = pyqtSignal(str, str)

    def __init__(self, agent: AgentRuntime, messages: List[Dict[str, Any]], user_text: str):
        super().__init__()
        self.agent = agent
        self.messages = messages
        self.user_text = user_text

    def run(self) -> None:
        try:
            reply = self.agent.process_user_text(user_text=self.user_text, messages=self.messages)
            self.done.emit(reply or "(empty response)", "")
        except Exception as err:
            self.done.emit("", str(err))


class _ContentRequestWorker(QThread):
    """
    Background QThread that runs an Orchestrator call for a proactive
    content_request event (triggered by a file drop into raw_ideas/).

    Emits:
        done(reply: str, error: str) — on completion or failure.
    """
    done = pyqtSignal(str, str)

    def __init__(self, orchestrator: Any, agent: AgentRuntime, use_multi_agent: bool,
                 suggested_prompt: str) -> None:
        super().__init__()
        self.orchestrator = orchestrator
        self.agent = agent
        self.use_multi_agent = use_multi_agent
        self.suggested_prompt = suggested_prompt

    def run(self) -> None:
        from agent_runtime import new_session as _new_session
        fresh_messages = _new_session()   # isolated session — no chat history contamination
        try:
            if self.use_multi_agent:
                reply = self.orchestrator.run(
                    user_text=self.suggested_prompt,
                    messages=fresh_messages,
                )
            else:
                reply = self.agent.process_user_text(
                    user_text=self.suggested_prompt,
                    messages=fresh_messages,
                )
            self.done.emit(reply or "(empty response)", "")
        except Exception as err:
            self.done.emit("", str(err))


class _OrchestratorWorker(QThread):  # noqa: F811
    """QThread wrapper for the multi-agent Orchestrator."""
    done = pyqtSignal(str, str)

    def __init__(self, orchestrator: Any, messages: List[Dict[str, Any]], user_text: str):
        super().__init__()
        self.orchestrator = orchestrator
        self.messages = messages
        self.user_text = user_text

    def run(self) -> None:
        try:
            reply = self.orchestrator.run(user_text=self.user_text, messages=self.messages)
            self.done.emit(reply or "(empty response)", "")
        except Exception as err:
            self.done.emit("", str(err))


class VoiceCallWorker(QThread):
    heard = pyqtSignal(str)
    replied = pyqtSignal(str)
    status = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, agent: AgentRuntime, messages: List[Dict[str, Any]], api_key: str, lang_code: str):
        super().__init__()
        self.agent = agent
        self.messages = messages
        self.api_key = api_key
        self.lang_code = lang_code
        self.running = True
        self.sample_rate = int(os.getenv("VOICE_GUI_SAMPLE_RATE", "16000"))
        self.chunk_sec = float(os.getenv("VOICE_GUI_CHUNK_SEC", "4.0"))
        self.silence_rms = float(os.getenv("VOICE_GUI_SILENCE_RMS", "450"))
        
        idx_str = os.getenv("VOICE_GUI_DEVICE_INDEX", "").strip()
        self.device_index = int(idx_str) if idx_str.isdigit() else None
        
        self.stt_provider = (os.getenv("VOICE_STT_PROVIDER", "speech_recognition").strip().lower() or "speech_recognition")
        self.recognizer = sr.Recognizer() if HAS_SPEECH_RECOGNITION else None

    def stop(self) -> None:
        self.running = False

    def _record_chunk_wav(self) -> bytes | None:
        frames = int(self.sample_rate * self.chunk_sec)
        audio = sd.rec(frames, samplerate=self.sample_rate, channels=1, dtype="int16", device=self.device_index)
        sd.wait()
        rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float32)))))
        print(f"[DEBUG] Mic RMS: {rms:.2f} (Silence threshold: {self.silence_rms})")
        if rms < self.silence_rms:
            return None

        pcm = audio.tobytes()
        bio = io.BytesIO()
        with wave.open(bio, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm)
        return bio.getvalue()

    def _stt_speech_recognition(self, wav_bytes: bytes) -> str:
        if self.recognizer is None:
            raise RuntimeError("speech_recognition is not installed")
        with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
            audio = self.recognizer.record(source)
        try:
            return str(self.recognizer.recognize_google(audio, language=self.lang_code)).strip()
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as err:
            raise RuntimeError(f"speech_recognition request failed: {err}") from err

    def _play_wav_b64(self, audio_b64: str) -> None:
        raw = base64.b64decode(audio_b64)
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            with open(path, "wb") as f:
                f.write(raw)
            if os.name == "nt":
                import winsound

                winsound.PlaySound(path, winsound.SND_FILENAME)
            else:
                # best-effort fallback for non-Windows
                os.system(f'afplay "{path}" >/dev/null 2>&1 || true')
        finally:
            try:
                os.remove(path)
            except Exception:
                pass

    def run(self) -> None:
        if not HAS_AUDIO_STACK:
            self.error.emit("Voice dependencies missing. Install: pip install numpy sounddevice")
            return
        while self.running:
            try:
                self.status.emit("Listening...")
                wav_bytes = self._record_chunk_wav()
                if not self.running:
                    break
                if wav_bytes is None:
                    continue

                self.status.emit("Transcribing...")
                detected_lang = self.lang_code
                transcript = ""
                if self.stt_provider == "speech_recognition":
                    transcript = self._stt_speech_recognition(wav_bytes)
                else:
                    try:
                        stt = voice_web._sarvam_stt(api_key=self.api_key, audio_bytes=wav_bytes, mime="audio/wav")
                        print(f"[DEBUG] Sarvam STT returned: {stt}")
                        transcript = str(stt.get("transcript", "")).strip()
                        detected_lang = str(stt.get("language_code", "")).strip() or self.lang_code
                    except Exception as e:
                        print(f"[DEBUG] STT Error: {e}")
                        raise e
                print(f"[DEBUG] Final transcript: '{transcript}'")
                if not transcript:
                    continue
                self.heard.emit(transcript)

                self.status.emit("Thinking...")
                reply_text = self.agent.process_user_text(user_text=transcript, messages=self.messages)
                self.replied.emit(reply_text)

                self.status.emit("Speaking...")
                tts = voice_web._sarvam_tts(api_key=self.api_key, text=reply_text, lang_code=detected_lang)
                audio_b64 = voice_web._extract_audio_b64(tts)
                self._play_wav_b64(audio_b64)
            except requests.HTTPError as err:
                status = err.response.status_code if err.response is not None else "?"
                body = err.response.text[:800] if err.response is not None else str(err)
                self.error.emit(f"Sarvam HTTP {status}: {body}")
                time.sleep(0.8)
            except Exception as err:
                self.error.emit(str(err))
                time.sleep(0.5)
        self.status.emit("Voice call stopped.")



class OrbWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(250, 250)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._glow_radius = 15.0
        self._orb_state = "idle"  # idle, listening, thinking, speaking
        
        self.anim = QPropertyAnimation(self, b"glowRadius")
        self.anim.setDuration(2000)
        self.anim.setLoopCount(-1)
        self.anim.setStartValue(10.0)
        self.anim.setEndValue(20.0)
        self.anim.setEasingCurve(QEasingCurve.InOutSine)
        self.anim.start()

    @pyqtProperty(float)
    def glowRadius(self) -> float:
        return self._glow_radius

    @glowRadius.setter
    def glowRadius(self, value: float) -> None:
        self._glow_radius = value
        self.update()
        
    def setState(self, state: str) -> None:
        if self._orb_state == state:
            return
        self._orb_state = state
        self.anim.stop()
        if state == "idle":
            self.anim.setDuration(2000)
            self.anim.setStartValue(10.0)
            self.anim.setEndValue(25.0)
        elif state == "listening":
            self.anim.setDuration(800)
            self.anim.setStartValue(20.0)
            self.anim.setEndValue(45.0)
        elif state == "thinking":
            self.anim.setDuration(500)
            self.anim.setStartValue(15.0)
            self.anim.setEndValue(60.0)
        elif state == "speaking":
            self.anim.setDuration(1200)
            self.anim.setStartValue(20.0)
            self.anim.setEndValue(40.0)
        self.anim.start()
        self.update()
        
    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        center = rect.center()
        
        # Decide colors based on state
        base_color = QColor(0, 243, 255) # Cyan
        if self._orb_state == "listening":
            base_color = QColor(0, 255, 65) # Green
        elif self._orb_state == "thinking":
            base_color = QColor(255, 170, 0) # Orange/Gold
        elif self._orb_state == "speaking":
            base_color = QColor(0, 243, 255) # Cyan
        
        # Outer glow (Flat transparent brush)
        glow_color = QColor(base_color)
        glow_color.setAlpha(40)
        painter.setBrush(QBrush(glow_color))
        painter.setPen(Qt.NoPen)
        r_glow = int(70 + self._glow_radius)
        painter.drawEllipse(center, r_glow, r_glow)
        
        # Inner core (Solid center)
        core_color = QColor(base_color).lighter(120)
        painter.setBrush(QBrush(core_color))
        painter.setPen(QPen(base_color, 2))
        painter.drawEllipse(center, 70, 70)
        
        # Draw some tech rings
        painter.setBrush(Qt.NoBrush)
        ring_pen = QPen(base_color, 1)
        ring_pen.setStyle(Qt.DashLine)
        painter.setPen(ring_pen)
        r_ring = int(85 + self._glow_radius*0.3)
        painter.drawEllipse(center, r_ring, r_ring)

        painter.end()


class CustomTitleBar(QWidget):
    def __init__(self, parent: QMainWindow) -> None:
        super().__init__(parent)
        self.parent_window = parent
        self.setFixedHeight(40)
        self.setStyleSheet("background-color: transparent;")
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 0, 15, 0)
        
        # Title
        self.title_label = QLabel("A.N.K.I.T.A  //  SYSTEM ACTIVE")
        self.title_label.setStyleSheet("color: rgba(0, 243, 255, 0.8); font-weight: bold; letter-spacing: 2px; font-family: 'Segoe UI', Arial; font-size: 11px;")
        layout.addWidget(self.title_label)
        
        layout.addStretch()
        
        # Min Button
        self.min_btn = QPushButton("—")
        self.min_btn.setFixedSize(30, 30)
        self.min_btn.setCursor(Qt.PointingHandCursor)
        self.min_btn.setStyleSheet("""
            QPushButton { color: #888; background: transparent; border: none; font-size: 14px; }
            QPushButton:hover { color: #fff; background: rgba(255,255,255,0.1); border-radius: 4px; }
        """)
        self.min_btn.clicked.connect(self.parent_window.showMinimized)
        layout.addWidget(self.min_btn)
        
        # Close Button
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setStyleSheet("""
            QPushButton { color: #888; background: transparent; border: none; font-size: 14px; }
            QPushButton:hover { color: #fff; background: #e81123; border-radius: 4px; }
        """)
        self.close_btn.clicked.connect(self.parent_window.close)
        layout.addWidget(self.close_btn)
        
        self.start_pos = None

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.LeftButton:
            self.start_pos = event.globalPos()

    def mouseMoveEvent(self, event: Any) -> None:
        if self.start_pos is not None:
            delta = event.globalPos() - self.start_pos
            self.parent_window.move(self.parent_window.pos() + delta)
            self.start_pos = event.globalPos()

    def mouseReleaseEvent(self, event: Any) -> None:
        self.start_pos = None


class AnkitaWindow(QMainWindow):
    hotkey_toggle_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        load_dotenv()
        runtime = build_runtime_from_env()
        self.agent = AgentRuntime(runtime=runtime, workspace_root=WORKSPACE_ROOT)
        self.orchestrator = Orchestrator(runtime=runtime, workspace_root=WORKSPACE_ROOT)
        self.use_multi_agent = _env_bool("ANKITA_MULTI_AGENT", True)
        self.memory = MemoryStore(workspace_root=WORKSPACE_ROOT)
        self.session_id = "gui-session"
        self.messages = new_session()
        self.worker: AskWorker | None = None
        self.voice_worker: VoiceCallWorker | None = None
        self._content_worker: _ContentRequestWorker | None = None
        self.hotkey_listener = None
        self.hotkey_key = (os.getenv("VOICE_HOTKEY_KEY", "f8").strip().lower() or "f8")
        self.hotkey_window_ms = max(120, int(os.getenv("VOICE_HOTKEY_DOUBLE_PRESS_MS", "400")))
        self.hotkey_last_press_ts = 0.0

        self.corn_runner: CornRunner | None = None
        if _env_bool("CORN_AUTO_RUN", True):
            self.corn_runner = CornRunner(
                workspace_root=WORKSPACE_ROOT,
                poll_interval_sec=float(os.getenv("CORN_POLL_INTERVAL_SEC", "5")),
                max_jobs_per_tick=int(os.getenv("CORN_MAX_JOBS_PER_TICK", "5")),
            )
            self.corn_runner.start()

        # Proactive engine — polls for events via QTimer
        self.proactive = ProactiveEngine(workspace_root=WORKSPACE_ROOT)
        self.proactive.start()
        self._proactive_timer = None  # set up after UI is built

        # Restore standard OS window for stability
        self.setWindowTitle("A.N.K.I.T.A")
        # self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        # self.setAttribute(Qt.WA_TranslucentBackground)
        # self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(1000, 700)

        self.root = QWidget(self)
        self.root.setObjectName("MainRoot")
        self.root.setStyleSheet("""
            QWidget#MainRoot {
                background-color: #0d0d12;
            }
            QLabel {
                color: #8892b0;
                font-family: 'Segoe UI', Arial;
            }
            QTextEdit {
                background-color: rgba(10, 15, 25, 0.6);
                border: 1px solid rgba(0, 243, 255, 0.15);
                border-radius: 8px;
                padding: 12px;
                font-size: 14px;
                color: #e6f1ff;
                font-family: 'Consolas', 'Courier New', monospace;
            }
            QScrollBar:vertical {
                border: none;
                background: rgba(0,0,0,0);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 243, 255, 0.3);
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(0, 243, 255, 0.6);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { border: none; background: none; }
            QLineEdit {
                background-color: rgba(10, 15, 25, 0.8);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 10px 15px;
                font-size: 14px;
                color: #00f3ff;
            }
            QLineEdit:focus {
                border: 1px solid rgba(0, 243, 255, 0.6);
                background-color: rgba(0, 243, 255, 0.05);
            }
            QPushButton {
                background-color: rgba(0, 243, 255, 0.05);
                border: 1px solid rgba(0, 243, 255, 0.2);
                border-radius: 6px;
                color: #00f3ff;
                padding: 10px 20px;
                font-weight: bold;
                letter-spacing: 1px;
                text-transform: uppercase;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(0, 243, 255, 0.15);
                border: 1px solid #00f3ff;
            }
            QPushButton:pressed {
                background-color: rgba(0, 243, 255, 0.25);
            }
            QPushButton:disabled {
                background-color: rgba(255, 255, 255, 0.02);
                border: 1px solid rgba(255, 255, 255, 0.05);
                color: #444;
            }
        """)

        main_layout = QVBoxLayout(self.root)
        main_layout.setContentsMargins(10, 10, 10, 10)
        self.setCentralWidget(self.root)

        # Content layout
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(20, 10, 20, 20)
        content_layout.setSpacing(20)
        main_layout.addLayout(content_layout)

        # Left Panel - Chat
        left_panel = QVBoxLayout()
        left_panel.setSpacing(15)

        self.info = QLabel(f"PROVIDER: {runtime.provider}  //  MODEL: {runtime.model}")
        self.info.setStyleSheet("color: rgba(0, 243, 255, 0.5); font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        left_panel.addWidget(self.info)

        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setPlaceholderText("Awaiting input...")
        left_panel.addWidget(self.chat)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Terminal input...")
        self.input.returnPressed.connect(self.on_send)
        row.addWidget(self.input)

        self.send_btn = QPushButton("Execute")
        self.send_btn.clicked.connect(self.on_send)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        row.addWidget(self.send_btn)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.on_reset)
        self.reset_btn.setCursor(Qt.PointingHandCursor)
        row.addWidget(self.reset_btn)

        self.agents_btn = QPushButton("⚡ MULTI-AGENT: ON" if self.use_multi_agent else "⚡ MULTI-AGENT: OFF")
        self.agents_btn.setCheckable(True)
        self.agents_btn.setChecked(self.use_multi_agent)
        self.agents_btn.clicked.connect(self.on_toggle_agents)
        self.agents_btn.setCursor(Qt.PointingHandCursor)
        self.agents_btn.setStyleSheet("""
            QPushButton { background-color: rgba(0,243,255,0.12); border: 1px solid rgba(0,243,255,0.4);
                          border-radius: 6px; color: #00f3ff; padding: 10px 14px; font-weight: bold;
                          letter-spacing: 1px; font-size: 10px; }
            QPushButton:checked { background-color: rgba(0,243,255,0.25); border: 1px solid #00f3ff; }
            QPushButton:hover { background-color: rgba(0,243,255,0.2); }
        """)
        row.addWidget(self.agents_btn)

        left_panel.addLayout(row)
        content_layout.addLayout(left_panel, stretch=6)

        # Right Panel - Simple Status
        right_panel = QVBoxLayout()
        right_panel.setAlignment(Qt.AlignCenter)
        right_panel.setSpacing(10)

        self.status_ball = QLabel("●")
        self.status_ball.setStyleSheet("color: #00f3ff; font-size: 80px;")
        right_panel.addWidget(self.status_ball, alignment=Qt.AlignCenter)

        # Voice controls
        vrow = QHBoxLayout()
        self.voice_lang = QLineEdit(os.getenv("VOICE_GUI_LANG", "en-IN"))
        self.voice_lang.setPlaceholderText("Lang code")
        self.voice_lang.setFixedWidth(80)
        vrow.addWidget(self.voice_lang)

        self.voice_start_btn = QPushButton("Listen")
        self.voice_start_btn.clicked.connect(self.on_voice_start)
        self.voice_start_btn.setCursor(Qt.PointingHandCursor)
        vrow.addWidget(self.voice_start_btn)

        self.voice_stop_btn = QPushButton("Stop")
        self.voice_stop_btn.clicked.connect(self.on_voice_stop)
        self.voice_stop_btn.setEnabled(False)
        self.voice_stop_btn.setCursor(Qt.PointingHandCursor)
        vrow.addWidget(self.voice_stop_btn)

        right_panel.addLayout(vrow)

        self.voice_status = QLabel("STATUS: IDLE")
        self.voice_status.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 11px; font-weight: bold; letter-spacing: 2px;")
        self.voice_status.setAlignment(Qt.AlignCenter)
        right_panel.addWidget(self.voice_status)

        content_layout.addLayout(right_panel, stretch=4)
        
        self.hotkey_toggle_requested.connect(self._toggle_voice_by_hotkey)

        self._append("System", "ANKITA GUI ready.")
        if not HAS_AUDIO_STACK:
            self._append("System", "Voice deps missing: install numpy + sounddevice for continuous call.")
        if not HAS_SPEECH_RECOGNITION:
            self._append("System", "SpeechRecognition not installed. STT will fallback to Sarvam when VOICE_STT_PROVIDER=sarvam.")
        if self.memory.enabled:
            self._append("System", "Vector memory: ON (ChromaDB)")
        self._append("System", f"Multi-agent mode: {'ON' if self.use_multi_agent else 'OFF'}")
        self._setup_hotkey_listener()

        # Start proactive polling timer (every 5 seconds)
        self._proactive_timer = QTimer(self)
        self._proactive_timer.timeout.connect(self._on_proactive_tick)
        self._proactive_timer.start(5000)

    def _normalize_hotkey_name(self, key_obj: Any) -> str:
        key_char = getattr(key_obj, "char", None)
        if isinstance(key_char, str) and key_char:
            return key_char.lower()
        text = str(key_obj).strip().lower()
        if text.startswith("key."):
            return text[4:]
        return text

    def _on_global_key_press(self, key_obj: Any) -> None:
        name = self._normalize_hotkey_name(key_obj)
        if name != self.hotkey_key:
            return
        now = time.monotonic() * 1000.0
        if now - self.hotkey_last_press_ts <= float(self.hotkey_window_ms):
            self.hotkey_last_press_ts = 0.0
            self.hotkey_toggle_requested.emit()
            return
        self.hotkey_last_press_ts = now

    def _setup_hotkey_listener(self) -> None:
        enabled = _env_bool("VOICE_HOTKEY_ENABLED", True)
        if not enabled:
            self._append("System", "Voice hotkey disabled (VOICE_HOTKEY_ENABLED=false).")
            return
        if not HAS_PYNPUT:
            self._append("System", "Global hotkey unavailable: install pynput.")
            return
        try:
            self.hotkey_listener = pynput_keyboard.Listener(on_press=self._on_global_key_press)
            self.hotkey_listener.daemon = True
            self.hotkey_listener.start()
            self._append(
                "System",
                f"Hotkey ready: double-press {self.hotkey_key} within {self.hotkey_window_ms} ms to toggle voice.",
            )
        except Exception as err:
            self._append("System", f"Failed to start global hotkey: {err}")

    def _toggle_voice_by_hotkey(self) -> None:
        running = self.voice_worker is not None and self.voice_worker.isRunning()
        if running:
            self.on_voice_stop()
            self._append("System", "Voice stopped by hotkey.")
        else:
            self.on_voice_start()
            running_after = self.voice_worker is not None and self.voice_worker.isRunning()
            if running_after:
                self._append("System", "Voice started by hotkey.")

    def _append(self, who: str, text: str) -> None:
        safe = text.replace("\\n", "<br>").strip()
        
        # Color code the chat
        if who in ["You", "You (voice)"]:
            color = "#00ff41" # Matrix green
        elif who == "Assistant":
            color = "#00f3ff" # Cyan
        else:
            color = "#8892b0" # System text
            
        styled_text = f"<span style='color:{color}; font-weight:bold;'>{who}:</span> <span style='color:#e6f1ff;'>{safe}</span><br>"
        self.chat.append(styled_text)

    def _set_busy(self, busy: bool) -> None:
        self.input.setDisabled(busy)
        self.send_btn.setDisabled(busy)
        self.reset_btn.setDisabled(busy)
        if busy:
            self.status_ball.setStyleSheet("color: #ffaa00; font-size: 80px;") # Thinking
        else:
            self.status_ball.setStyleSheet("color: #00f3ff; font-size: 80px;") # Idle

    def _on_proactive_tick(self) -> None:
        """Called every 5s by QTimer to check for proactive events."""
        for event in self.proactive.get_pending_events():
            self._append("A.N.K.I.T.A", event.message)

            # content_request: auto-run ContentAgent in background, then speak result via TTS
            if event.kind == "content_request":
                suggested_prompt = event.data.get("suggested_prompt", "")
                if not suggested_prompt:
                    continue
                # Prevent overlapping content workers
                if hasattr(self, "_content_worker") and self._content_worker is not None:
                    if self._content_worker.isRunning():
                        self._append("System", "⏳ Content generation already in progress — queuing after current job.")
                        continue

                self._append("A.N.K.I.T.A", "🖊️ Working on it in the background...")
                self.status_ball.setStyleSheet("color: #ffaa00; font-size: 80px;")  # thinking colour

                worker = _ContentRequestWorker(
                    orchestrator=self.orchestrator,
                    agent=self.agent,
                    use_multi_agent=self.use_multi_agent,
                    suggested_prompt=suggested_prompt,
                )

                def _on_content_done(reply: str, error: str, _ev_data: dict = event.data) -> None:
                    self.status_ball.setStyleSheet("color: #00f3ff; font-size: 80px;")  # idle colour
                    if error:
                        self._append("A.N.K.I.T.A [Error]", error)
                        return

                    self._append("A.N.K.I.T.A", reply)
                    self.memory.add(self.session_id, "assistant", reply)

                    # Speak the reply via TTS (Sarvam) if API key is available
                    api_key = os.getenv("SARVAM_API_KEY", "").strip()
                    if api_key:
                        try:
                            lang = self.voice_lang.text().strip() or "en-IN"
                            tts = voice_web._sarvam_tts(api_key=api_key, text=reply, lang_code=lang)
                            audio_b64 = voice_web._extract_audio_b64(tts)
                            # Play in a minimal throwaway thread so UI never blocks
                            import threading
                            def _play() -> None:
                                import base64, tempfile, os as _os
                                raw = base64.b64decode(audio_b64)
                                fd, path = tempfile.mkstemp(suffix=".wav")
                                _os.close(fd)
                                try:
                                    with open(path, "wb") as f:
                                        f.write(raw)
                                    if _os.name == "nt":
                                        import winsound
                                        winsound.PlaySound(path, winsound.SND_FILENAME)
                                    else:
                                        _os.system(f'afplay "{path}" >/dev/null 2>&1 || true')
                                finally:
                                    try:
                                        _os.remove(path)
                                    except Exception:
                                        pass
                            threading.Thread(target=_play, daemon=True).start()
                        except Exception as tts_err:
                            self._append("System", f"TTS error: {tts_err}")

                worker.done.connect(_on_content_done)
                worker.start()
                self._content_worker = worker

    def on_toggle_agents(self) -> None:
        self.use_multi_agent = self.agents_btn.isChecked()
        label = "ON" if self.use_multi_agent else "OFF"
        self.agents_btn.setText(f"⚡ MULTI-AGENT: {label}")
        self._append("System", f"Multi-agent mode: {label}")

    def on_send(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._append("You", text)

        # Inject relevant memories as a system context message
        mem_context = self.memory.format_memory_context(text, n=4)
        if mem_context:
            self.messages.append({"role": "system", "content": mem_context})

        self._set_busy(True)
        if self.use_multi_agent:
            # Use orchestrator — wrap in AskWorker-compatible thread
            self.worker = _OrchestratorWorker(self.orchestrator, self.messages, text)
        else:
            self.worker = AskWorker(self.agent, self.messages, text)
        self.worker.done.connect(self._on_reply)
        self.worker.start()

    def _on_reply(self, reply: str, error: str) -> None:
        if error:
            self._append("Assistant [Error]", error)
            QMessageBox.critical(self, "ANKITA Error", error)
        else:
            self._append("Assistant", reply)
            # Store in vector memory
            last_user = next(
                (m["content"] for m in reversed(self.messages) if m.get("role") == "user"), ""
            )
            if last_user:
                self.memory.add(self.session_id, "user", last_user)
            self.memory.add(self.session_id, "assistant", reply)
        self._set_busy(False)
        self.input.setFocus()

    def on_reset(self) -> None:
        self.messages = new_session()
        self._append("System", "Conversation reset.")

    def on_voice_start(self) -> None:
        if self.voice_worker is not None and self.voice_worker.isRunning():
            return
        if not HAS_AUDIO_STACK:
            QMessageBox.warning(self, "Voice unavailable", "Install dependencies: pip install numpy sounddevice")
            return
        api_key = os.getenv("SARVAM_API_KEY", "").strip()
        if not api_key:
            QMessageBox.warning(self, "Voice unavailable", "SARVAM_API_KEY is not set.")
            return
        lang = self.voice_lang.text().strip() or "en-IN"
        self.voice_worker = VoiceCallWorker(self.agent, self.messages, api_key=api_key, lang_code=lang)
        
        # Listen for specific signals to update Orb state
        self.voice_worker.heard.connect(lambda t: self._append("You (voice)", t))
        self.voice_worker.replied.connect(lambda t: self._append("Assistant", t))
        
        def on_status(s: str) -> None:
            self.voice_status.setText(f"STATUS: {s.upper()}")
            if "Transcribing" in s or "Listening" in s:
                self.status_ball.setStyleSheet("color: #00ff41; font-size: 80px;")
            elif "Thinking" in s:
                self.status_ball.setStyleSheet("color: #ffaa00; font-size: 80px;")
            elif "Speaking" in s:
                self.status_ball.setStyleSheet("color: #00f3ff; font-size: 80px;")
            else:
                self.status_ball.setStyleSheet("color: #00f3ff; font-size: 80px;")
                
        self.voice_worker.status.connect(on_status)
        self.voice_worker.error.connect(lambda e: self._append("Voice [Error]", e))
        
        self.voice_worker.start()
        self.voice_start_btn.setEnabled(False)
        self.voice_stop_btn.setEnabled(True)
        self.voice_status.setText("STATUS: STARTING...")
        self.orb.setState("listening")

    def on_voice_stop(self) -> None:
        if self.voice_worker is None:
            return
        self.voice_worker.stop()
        self.voice_worker.wait(1500)
        self.voice_start_btn.setEnabled(True)
        self.voice_stop_btn.setEnabled(False)
        self.voice_status.setText("STATUS: IDLE")
        self.status_ball.setStyleSheet("color: #00f3ff; font-size: 80px;")

    def closeEvent(self, event: Any) -> None:
        if self._proactive_timer is not None:
            self._proactive_timer.stop()
        self.proactive.stop()
        if self.worker is not None and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(1000)
        if self.voice_worker is not None and self.voice_worker.isRunning():
            self.voice_worker.stop()
            self.voice_worker.wait(1500)
        if self.corn_runner is not None:
            self.corn_runner.stop()
        if self.hotkey_listener is not None:
            try:
                self.hotkey_listener.stop()
            except Exception:
                pass
        super().closeEvent(event)


def main() -> None:
    # Enable High DPI scaling
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    app = QApplication(sys.argv)
    
    # Optional styling for message boxes
    app.setStyleSheet("""
        QMessageBox {
            background-color: #0d0d12;
            color: #e6f1ff;
        }
        QMessageBox QLabel { color: #e6f1ff; }
        QMessageBox QPushButton {
            background-color: rgba(0, 243, 255, 0.1);
            color: #00f3ff;
            border: 1px solid rgba(0, 243, 255, 0.3);
            border-radius: 4px;
            padding: 5px 15px;
        }
    """)
    
    window = AnkitaWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
