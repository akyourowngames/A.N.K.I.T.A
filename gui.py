import base64
import html
import io
import os
import subprocess
import sys

# Fix Windows console encoding for Unicode
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(errors='replace')
    except Exception:
        pass

import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv
from PyQt5.QtCore import (
    QThread, pyqtSignal, QTimer, Qt, QSize, QPropertyAnimation,
    QEasingCurve, pyqtProperty, QRectF, QPointF,
)
from PyQt5.QtGui import (
    QFont, QColor, QPalette, QIcon, QFontDatabase, QPainter,
    QRadialGradient, QPen, QBrush, QMovie, QLinearGradient,
    QConicalGradient,
)
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from agent_runtime import AgentRuntime, new_session
from agents import Orchestrator
from llm import build_runtime_from_env
import voice_web

WORKSPACE_ROOT = Path.cwd().resolve()

try:
    import numpy as np
    import sounddevice as sd
    HAS_AUDIO_STACK = True
except Exception:
    HAS_AUDIO_STACK = False

try:
    import speech_recognition as sr
    HAS_SPEECH_RECOGNITION = True
except Exception:
    HAS_SPEECH_RECOGNITION = False


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
            reply = self.agent.process_user_text(
                user_text=self.user_text, messages=self.messages, interface="gui"
            )
            self.done.emit(reply or "(empty response)", "")
        except Exception as err:
            self.done.emit("", str(err))



class _OrchestratorWorker(QThread):
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


class _ContentRequestWorker(QThread):
    done = pyqtSignal(str, str)

    def __init__(self, orchestrator: Any, agent: AgentRuntime,
                 use_multi_agent: bool, suggested_prompt: str) -> None:
        super().__init__()
        self.orchestrator = orchestrator
        self.agent = agent
        self.use_multi_agent = use_multi_agent
        self.suggested_prompt = suggested_prompt

    def run(self) -> None:
        from agent_runtime import new_session as _new_session
        fresh_messages = _new_session()
        try:
            if self.use_multi_agent:
                reply = self.orchestrator.run(
                    user_text=self.suggested_prompt, messages=fresh_messages)
            else:
                reply = self.agent.process_user_text(
                    user_text=self.suggested_prompt, messages=fresh_messages)
            self.done.emit(reply or "(empty response)", "")
        except Exception as err:
            self.done.emit("", str(err))


class VoiceCallWorker(QThread):
    heard = pyqtSignal(str)
    replied = pyqtSignal(str)
    status = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, orchestrator: Any, messages: List[Dict[str, Any]],
                 api_key: str, lang_code: str):
        super().__init__()
        self.orchestrator = orchestrator
        self.messages = messages
        self.api_key = api_key
        self.lang_code = lang_code
        self.running = True
        self.sample_rate = int(os.getenv("VOICE_GUI_SAMPLE_RATE", "16000"))
        self.chunk_sec = float(os.getenv("VOICE_GUI_CHUNK_SEC", "4.0"))
        self.silence_rms = float(os.getenv("VOICE_GUI_SILENCE_RMS", "450"))
        self.stt_provider = os.getenv("VOICE_STT_PROVIDER", "speech_recognition").strip().lower()
        self.recognizer = sr.Recognizer() if HAS_SPEECH_RECOGNITION else None
        self._playback_stop = threading.Event()
        self._playback_proc = None

        # Resolve microphone device index
        # Priority: .env VOICE_GUI_DEVICE_INDEX > Realtek mic > OS default input
        idx_str = os.getenv("VOICE_GUI_DEVICE_INDEX", "").strip()
        if idx_str.isdigit():
            requested_idx = int(idx_str)
            # Validate the device actually exists and has input channels
            try:
                dev_info = sd.query_devices(requested_idx)
                if dev_info.get("max_input_channels", 0) >= 1:
                    self.device_index = requested_idx
                    self.mic_name = dev_info.get("name", f"Device #{requested_idx}")
                else:
                    # Device exists but is output-only  -- fall through to auto-detect
                    self.device_index = None
                    self.mic_name = "auto (device has no input channels)"
                    idx_str = ""  # Trigger auto-detect below
            except Exception:
                # Device index doesn't exist  -- warn and fall through to auto-detect
                self.device_index = None
                self.mic_name = "auto (device index invalid)"
                idx_str = ""  # Trigger auto-detect below
        else:
            # Try to find the real physical mic  -- prefer Realtek over virtual devices
            # Virtual/fake mics to skip
            VIRTUAL_KEYWORDS = {"splitcam", "droidcam", "iriun", "virtual", "mapper",
                                 "primary sound", "stereo mix", "midi", "output",
                                 "loopback", "wave out mix"}
            # Microsoft, Realtek, and Array mics are preferred over virtual/generic devices
            PREFERRED_KEYWORDS = {"realtek", "microphone array", "array", "microsoft",
                                   "hd audio", "usb audio", "headset", "built-in"}
            try:
                all_devices = sd.query_devices()
                best_idx = None
                best_name = ""
                fallback_idx = None
                fallback_name = ""
                for i, d in enumerate(all_devices):
                    if d["max_input_channels"] < 1:
                        continue
                    name_lower = d["name"].lower()
                    is_virtual = any(v in name_lower for v in VIRTUAL_KEYWORDS)
                    is_preferred = any(p in name_lower for p in PREFERRED_KEYWORDS)
                    if is_preferred and not is_virtual:
                        # Prefer higher sample rate variant (e.g. 48000 over 44100)
                        if best_idx is None or d["default_samplerate"] >= all_devices[best_idx]["default_samplerate"]:
                            best_idx = i
                            best_name = d["name"]
                    elif not is_virtual and fallback_idx is None:
                        fallback_idx = i
                        fallback_name = d["name"]

                if best_idx is not None:
                    self.device_index = best_idx
                    self.mic_name = best_name
                elif fallback_idx is not None:
                    self.device_index = fallback_idx
                    self.mic_name = fallback_name
                else:
                    # Last resort  -- use OS default even if virtual
                    default_in = sd.default.device[0]
                    self.device_index = default_in if (default_in is not None and default_in >= 0) else None
                    self.mic_name = sd.query_devices(self.device_index).get("name", "Default mic") if self.device_index is not None else "System default"
            except Exception:
                self.device_index = None
                self.mic_name = "System default mic"

    def stop(self) -> None:
        self.running = False
        self.interrupt_speaking()

    def interrupt_speaking(self) -> None:
        """Immediately stop current TTS playback (if any)."""
        self._playback_stop.set()
        if os.name == "nt":
            try:
                import winsound
                winsound.PlaySound(None, 0)
            except Exception:
                pass
            return
        proc = self._playback_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def _record_chunk_wav(self) -> bytes | None:
        frames = int(self.sample_rate * self.chunk_sec)
        try:
            audio = sd.rec(frames, samplerate=self.sample_rate, channels=1,
                           dtype="int16", device=self.device_index)
            sd.wait()
        except Exception as rec_err:
            # Device index became invalid at runtime (e.g. USB mic unplugged)
            # Fall back to system default and retry once
            if self.device_index is not None:
                self.device_index = None
                self.mic_name = "System default (fallback)"
                try:
                    audio = sd.rec(frames, samplerate=self.sample_rate, channels=1,
                                   dtype="int16", device=None)
                    sd.wait()
                except Exception:
                    return None
            else:
                return None
        rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float32)))))
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
            raise RuntimeError("speech_recognition not installed")
        with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
            audio = self.recognizer.record(source)
        try:
            return str(self.recognizer.recognize_google(audio, language=self.lang_code)).strip()
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as err:
            raise RuntimeError(f"STT request failed: {err}") from err

    def _play_wav_b64(self, audio_b64: str) -> None:
        raw = base64.b64decode(audio_b64)
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        self._playback_stop.clear()
        try:
            with open(path, "wb") as f:
                f.write(raw)
            if os.name == "nt":
                import winsound
                # Async playback allows interrupt_speaking() to cut speech instantly.
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                duration_sec = 0.0
                try:
                    with wave.open(io.BytesIO(raw), "rb") as wf:
                        rate = float(wf.getframerate() or 0)
                        frames = float(wf.getnframes() or 0)
                        if rate > 0:
                            duration_sec = frames / rate
                except Exception:
                    duration_sec = 0.0

                start = time.monotonic()
                while self.running and not self._playback_stop.is_set():
                    if duration_sec > 0 and (time.monotonic() - start) >= (duration_sec + 0.15):
                        break
                    time.sleep(0.05)
                try:
                    winsound.PlaySound(None, 0)
                except Exception:
                    pass
            else:
                self._playback_proc = subprocess.Popen(
                    ["afplay", path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                while self.running and not self._playback_stop.is_set():
                    if self._playback_proc.poll() is not None:
                        break
                    time.sleep(0.05)
                if self._playback_proc.poll() is None:
                    self._playback_proc.terminate()
                    try:
                        self._playback_proc.wait(timeout=0.6)
                    except Exception:
                        pass
        finally:
            self._playback_proc = None
            try:
                os.remove(path)
            except Exception:
                pass

    def run(self) -> None:
        if not HAS_AUDIO_STACK:
            self.error.emit("Voice deps missing: pip install numpy sounddevice")
            return
        
        print("[VoiceCallWorker] Starting voice loop...", flush=True)
        while self.running:
            try:
                self.status.emit("Listening...")
                wav_bytes = self._record_chunk_wav()
                if not self.running:
                    break
                if wav_bytes is None:
                    continue

                self.status.emit("Transcribing...")
                transcript = ""
                detected_lang = self.lang_code
                if self.stt_provider == "speech_recognition":
                    transcript = self._stt_speech_recognition(wav_bytes)
                else:
                    stt = voice_web._sarvam_stt(
                        api_key=self.api_key, audio_bytes=wav_bytes, mime="audio/wav")
                    transcript = str(stt.get("transcript", "")).strip()
                    detected_lang = str(stt.get("language_code", "")).strip() or self.lang_code

                if not transcript:
                    continue
                
                print(f"[VoiceCallWorker] Heard: {transcript}", flush=True)
                self.heard.emit(transcript)

                self.status.emit("Thinking...")
                reply_text = self.orchestrator.run(
                    user_text=transcript, messages=self.messages)
                
                if not reply_text:
                    print("[VoiceCallWorker] ⚠️ Empty reply from agent", flush=True)
                    self.error.emit("Agent returned empty response")
                    continue
                
                print(f"[VoiceCallWorker] Reply: {reply_text[:100]}...", flush=True)
                self.replied.emit(reply_text)

                self.status.emit("Speaking...")
                try:
                    tts = voice_web._sarvam_tts(
                        api_key=self.api_key, text=reply_text, lang_code=detected_lang)
                    audio_b64 = voice_web._extract_audio_b64(tts)
                    if audio_b64:
                        self._play_wav_b64(audio_b64)
                    else:
                        print("[VoiceCallWorker] ⚠️ No audio data from TTS", flush=True)
                except Exception as tts_err:
                    print(f"[VoiceCallWorker] TTS/playback error: {tts_err}", flush=True)
                    self.error.emit(f"TTS failed: {tts_err}")
                    # Continue listening even if TTS fails
            except requests.HTTPError as err:
                status = err.response.status_code if err.response is not None else "?"
                body = err.response.text[:400] if err.response is not None else str(err)
                print(f"[VoiceCallWorker] HTTP error {status}: {body}", flush=True)
                self.error.emit(f"HTTP {status}: {body}")
                time.sleep(0.8)
            except Exception as err:
                print(f"[VoiceCallWorker] Unexpected error: {err}", flush=True)
                import traceback
                traceback.print_exc()
                self.error.emit(str(err))
                time.sleep(0.5)
        
        print("[VoiceCallWorker] Voice loop ended.", flush=True)
        self.status.emit("Stopped.")


# ---------------------------------------------------------------------------
# Startup Worker — heavy init off the main thread so GUI never hangs
# ---------------------------------------------------------------------------

class _StartupWorker(QThread):
    """Runs ALL heavy backend initialization in a background thread.

    Emits progress strings for the loading overlay, then a dict of
    initialized objects when done, or an error string on failure.
    """
    progress = pyqtSignal(str)
    ready = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, runtime: Any) -> None:
        super().__init__()
        self._runtime = runtime

    def run(self) -> None:
        try:
            runtime = self._runtime

            self.progress.emit("Booting agent runtime...")
            agent = AgentRuntime(runtime=runtime, workspace_root=WORKSPACE_ROOT)

            self.progress.emit("Building orchestrator...")
            orchestrator = Orchestrator(runtime=runtime, workspace_root=WORKSPACE_ROOT)
            use_multi_agent = _env_bool("ANKITA_MULTI_AGENT", True)

            self.progress.emit("Connecting memory systems...")
            memory = None
            try:
                from memory import get_memory_manager
                memory = get_memory_manager(WORKSPACE_ROOT)
                memory.attach_runtime(runtime)
            except Exception as e:
                print(f"[Startup] Memory init warning: {e}", flush=True)

            self.progress.emit("Initializing feedback engine...")
            feedback_engine = None
            try:
                from tools.feedback_engine import FeedbackEngine
                feedback_engine = FeedbackEngine(WORKSPACE_ROOT, llm_runtime=runtime)
            except Exception as e:
                print(f"[Startup] FeedbackEngine init warning: {e}", flush=True)

            self.progress.emit("Systems online.")
            self.ready.emit({
                "runtime": runtime,
                "agent": agent,
                "orchestrator": orchestrator,
                "use_multi_agent": use_multi_agent,
                "memory": memory,
                "feedback_engine": feedback_engine,
            })

        except SystemExit as exc:
            self.failed.emit(f"LLM auth failed (exit {exc.code}). Check .env.")
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.failed.emit(str(exc))


# ---------------------------------------------------------------------------
# Jarvis Theme
# ---------------------------------------------------------------------------

_JARVIS_BG       = "#000000"
_JARVIS_SURFACE  = "#050505"
_JARVIS_CARD     = "#0a0a0a"
_JARVIS_BORDER   = "#141414"
_JARVIS_CYAN     = "#00d4ff"
_JARVIS_CYAN_DIM = "#061a24"
_JARVIS_GREEN    = "#00ff88"
_JARVIS_RED      = "#ff3355"
_JARVIS_AMBER    = "#ffaa00"
_JARVIS_TEXT     = "#8090a0"
_JARVIS_TEXT_DIM = "#2a3038"


def _resolve_ui_font_family() -> str:
    env_font = os.getenv("ANKITA_UI_FONT", "").strip()
    if env_font:
        return env_font
    try:
        return QFontDatabase.systemFont(QFontDatabase.FixedFont).family()
    except Exception:
        return "Monospace"


_UI_FONT_FAMILY = _resolve_ui_font_family()
_JARVIS_FONT = os.getenv("ANKITA_UI_FONT_STACK", _UI_FONT_FAMILY).strip()


def _ui_font(size: int) -> QFont:
    return QFont(_UI_FONT_FAMILY, size)

_MASTER_QSS = f"""
QMainWindow {{
    background: {_JARVIS_BG};
}}
QWidget#centralRoot {{
    background: {_JARVIS_BG};
}}

/* ---- Sidebar ---- */
QWidget#sidebar {{
    background: {_JARVIS_SURFACE};
    border-right: 1px solid {_JARVIS_BORDER};
}}
QPushButton.sideBtn {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 10px;
    color: {_JARVIS_TEXT_DIM};
    font-size: 18px;
}}
QPushButton.sideBtn:hover {{
    background: {_JARVIS_BORDER};
    color: {_JARVIS_CYAN};
}}
QPushButton.sideBtn:checked {{
    background: rgba(0, 212, 255, 0.08);
    color: {_JARVIS_CYAN};
    border-left: 2px solid {_JARVIS_CYAN};
}}

/* ---- Chat view ---- */
QTextBrowser#chatView {{
    background: transparent;
    color: {_JARVIS_TEXT};
    border: none;
    padding: 8px 4px;
    selection-background-color: {_JARVIS_CYAN_DIM};
}}
QTextBrowser#chatView QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    border-radius: 3px;
}}
QTextBrowser#chatView QScrollBar::handle:vertical {{
    background: {_JARVIS_CYAN_DIM};
    border-radius: 3px;
    min-height: 30px;
}}
QTextBrowser#chatView QScrollBar::add-line:vertical,
QTextBrowser#chatView QScrollBar::sub-line:vertical {{
    height: 0px;
}}

/* ---- Input field ---- */
QLineEdit#inputField {{
    background: {_JARVIS_SURFACE};
    color: {_JARVIS_TEXT};
    border: 1px solid {_JARVIS_BORDER};
    border-radius: 24px;
    padding: 12px 20px;
    font-size: 13px;
    font-family: {_JARVIS_FONT};
}}
QLineEdit#inputField:focus {{
    border: 1px solid {_JARVIS_CYAN};
}}
QLineEdit#inputField:disabled {{
    color: {_JARVIS_TEXT_DIM};
}}

/* ---- Status label ---- */
QLabel#statusLabel {{
    color: {_JARVIS_TEXT_DIM};
    font-size: 10px;
    padding: 0 8px;
    font-family: {_JARVIS_FONT};
    letter-spacing: 2px;
}}

/* ---- Right panel cards ---- */
QWidget#rightPanel {{
    background: {_JARVIS_SURFACE};
    border-left: 1px solid {_JARVIS_BORDER};
}}
QFrame.infoCard {{
    background: {_JARVIS_CARD};
    border: 1px solid {_JARVIS_BORDER};
    border-radius: 10px;
    padding: 14px;
}}
QLabel.cardTitle {{
    color: {_JARVIS_CYAN};
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 2px;
    font-family: {_JARVIS_FONT};
}}
QLabel.cardValue {{
    color: {_JARVIS_TEXT};
    font-size: 22px;
    font-weight: bold;
    font-family: {_JARVIS_FONT};
}}
QLabel.cardSub {{
    color: {_JARVIS_TEXT_DIM};
    font-size: 10px;
    font-family: {_JARVIS_FONT};
}}
QLabel.cardUnit {{
    color: {_JARVIS_GREEN};
    font-size: 11px;
    font-family: {_JARVIS_FONT};
}}
"""


def _btn_qss(accent: str, hover: str, text_color: str = "#e0e8f0") -> str:
    return (
        f"QPushButton {{ background: transparent; color: {text_color};"
        f" border: 1px solid {accent}; border-radius: 20px;"
        f" padding: 8px 20px; font-size: 11px; font-weight: bold;"
        f" font-family: {_JARVIS_FONT}; letter-spacing: 1px; }}"
        f"QPushButton:hover {{ background: {accent}; color: #fff; }}"
        f"QPushButton:pressed {{ background: {hover}; }}"
        f"QPushButton:disabled {{ border-color: #1a2744; color: #334; }}"
    )


def _chip_qss() -> str:
    return (
        f"QPushButton {{ background: transparent; color: {_JARVIS_TEXT_DIM};"
        f" border: 1px solid {_JARVIS_BORDER}; border-radius: 14px;"
        f" padding: 5px 14px; font-size: 10px;"
        f" font-family: {_JARVIS_FONT}; letter-spacing: 1px; }}"
        f"QPushButton:hover {{ color: {_JARVIS_CYAN}; border-color: {_JARVIS_CYAN_DIM}; }}"
    )


# ---------------------------------------------------------------------------
# Orb Widget — animated reactor core
# ---------------------------------------------------------------------------

class _OrbWidget(QWidget):
    """Central animated orb using the download.gif.

    Falls back to a QPainter-drawn pulsing orb if the GIF is missing.
    """

    def __init__(self, size: int = 280, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        gif_size = int(size * 0.92)
        margin = (size - gif_size) // 2
        self.setFixedSize(size, size + 20)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent; border: none;")
        self._state = "idle"  # idle | thinking | online | error | listening
        self._label_text = "AWAITING INPUT"

        gif_path = WORKSPACE_ROOT / "download.gif"
        self._movie: QMovie | None = None
        self._gif_label: QLabel | None = None

        if gif_path.exists():
            self._movie = QMovie(str(gif_path))
            self._movie.setScaledSize(QSize(gif_size, gif_size))

            self._gif_label = QLabel(self)
            self._gif_label.setMovie(self._movie)
            self._gif_label.setAlignment(Qt.AlignCenter)
            self._gif_label.setFixedSize(gif_size, gif_size)
            self._gif_label.move(margin, margin // 2)
            self._gif_label.setStyleSheet("background: transparent;")
            self._movie.start()

        # State text below orb
        self._state_label = QLabel(self._label_text, self)
        self._state_label.setAlignment(Qt.AlignCenter)
        self._state_label.setFixedWidth(size)
        self._state_label.move(0, size - 8)
        self._state_label.setStyleSheet(
            f"color: {_JARVIS_TEXT_DIM}; font-size: 11px;"
            f" font-family: {_JARVIS_FONT}; letter-spacing: 3px;"
            " background: transparent;"
        )

        # Fallback painter animation
        self._angle = 0.0
        self._pulse = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # ~30fps

    def set_state(self, state: str, text: str = "") -> None:
        self._state = state
        color_map = {
            "idle": _JARVIS_CYAN,
            "thinking": _JARVIS_AMBER,
            "online": _JARVIS_GREEN,
            "error": _JARVIS_RED,
            "listening": _JARVIS_CYAN,
        }
        color = color_map.get(state, _JARVIS_CYAN)
        # glow removed — color state tracked internally only

        label_map = {
            "idle": "AWAITING INPUT",
            "thinking": "PROCESSING",
            "online": "SYSTEMS ONLINE",
            "error": "OFFLINE",
            "listening": "LISTENING",
        }
        self._label_text = text or label_map.get(state, state.upper())
        self._state_label.setText(self._label_text)
        self._state_label.setStyleSheet(
            f"color: {color}; font-size: 11px;"
            f" font-family: {_JARVIS_FONT}; letter-spacing: 3px;"
            " background: transparent;"
        )

        # Adjust movie speed based on state
        if self._movie:
            speeds = {"idle": 100, "thinking": 60, "online": 100,
                      "error": 200, "listening": 80}
            self._movie.setSpeed(speeds.get(state, 100))

    def _tick(self) -> None:
        if not self._movie:
            self._angle = (self._angle + 1.2) % 360
            self._pulse = (self._pulse + 0.05) % 6.283
            self.update()

    def paintEvent(self, event) -> None:
        if self._movie:
            return  # GIF handles the visual
        # Fallback: painted orb
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self._size
        cx, cy, r = s // 2, s // 2 - 10, s // 4

        import math
        pulse = 0.5 + 0.5 * math.sin(self._pulse)

        # Outer glow
        grad = QRadialGradient(cx, cy, r + 40)
        col = QColor(_JARVIS_CYAN)
        col.setAlpha(int(30 + 25 * pulse))
        grad.setColorAt(0.0, col)
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), r + 40, r + 40)

        # Core ring
        pen = QPen(QColor(_JARVIS_CYAN))
        pen.setWidthF(2.0 + pulse)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Spinning arc
        pen2 = QPen(QColor(_JARVIS_CYAN))
        pen2.setWidthF(3.0)
        p.setPen(pen2)
        rect = QRectF(cx - r + 10, cy - r + 10, (r - 10) * 2, (r - 10) * 2)
        p.drawArc(rect, int(self._angle * 16), 90 * 16)

        p.end()


# ---------------------------------------------------------------------------
# Info Card helper
# ---------------------------------------------------------------------------

class _InfoCard(QFrame):
    """A rounded card for the right panel."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("class", "infoCard")
        self.setObjectName("infoCard")
        self.setStyleSheet(
            f"background: {_JARVIS_CARD}; border: 1px solid {_JARVIS_BORDER};"
            f" border-radius: 10px; padding: 14px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        head = QHBoxLayout()
        t = QLabel(title.upper())
        t.setStyleSheet(
            f"color: {_JARVIS_CYAN}; font-size: 11px; font-weight: bold;"
            f" letter-spacing: 2px; font-family: {_JARVIS_FONT};"
            " border: none; background: transparent; padding: 0;"
        )
        head.addWidget(t)
        head.addStretch()

        self._status_dot = QLabel()
        self._status_dot.setFixedSize(8, 8)
        self._status_dot.setStyleSheet(
            f"background: {_JARVIS_GREEN}; border-radius: 4px;"
            " border: none; padding: 0;"
        )
        head.addWidget(self._status_dot)
        layout.addLayout(head)

        self._body = QVBoxLayout()
        self._body.setSpacing(4)
        layout.addLayout(self._body)

    def add_metric(self, label: str, value: str, color: str = _JARVIS_TEXT) -> QLabel:
        row = QHBoxLayout()
        row.setSpacing(0)
        lbl = QLabel(label.upper())
        lbl.setStyleSheet(
            f"color: {_JARVIS_TEXT_DIM}; font-size: 10px;"
            f" font-family: {_JARVIS_FONT}; letter-spacing: 1px;"
            " border: none; background: transparent; padding: 0;"
        )
        row.addWidget(lbl)
        row.addStretch()
        val = QLabel(value)
        val.setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: bold;"
            f" font-family: {_JARVIS_FONT};"
            " border: none; background: transparent; padding: 0;"
        )
        row.addWidget(val)
        self._body.addLayout(row)
        return val

    def add_bar(self, fraction: float = 0.0, color: str = _JARVIS_GREEN) -> QFrame:
        bar_bg = QFrame()
        bar_bg.setFixedHeight(4)
        bar_bg.setStyleSheet(
            f"background: {_JARVIS_BORDER}; border-radius: 2px;"
            " border: none; padding: 0;"
        )
        # We fake the fill with a child widget
        bar_fill = QFrame(bar_bg)
        w = max(2, int(fraction * 200))
        bar_fill.setFixedHeight(4)
        bar_fill.setFixedWidth(w)
        bar_fill.setStyleSheet(
            f"background: {color}; border-radius: 2px;"
            " border: none; padding: 0;"
        )
        self._body.addWidget(bar_bg)
        self._bar_fill = bar_fill
        self._bar_bg = bar_bg
        return bar_bg

    def set_status(self, online: bool) -> None:
        c = _JARVIS_GREEN if online else _JARVIS_RED
        self._status_dot.setStyleSheet(
            f"background: {c}; border-radius: 4px; border: none; padding: 0;"
        )


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class AnkitaWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        load_dotenv()

        # ── PHASE 1: fast runtime build ──
        self._runtime = build_runtime_from_env()

        # Deferred backend placeholders
        self.agent: AgentRuntime | None = None
        self.orchestrator: Any = None
        self.use_multi_agent = True
        self.memory: Any = None
        self.feedback_engine: Any = None
        self._last_fb_iid: str = ""

        self.session_id = "gui-session"
        self.messages = new_session()

        self.worker: AskWorker | None = None
        self.voice_worker: Any = None
        self._content_worker: _ContentRequestWorker | None = None
        self._pending_user_text: str = ""
        self.voice_lang_code = os.getenv("VOICE_GUI_LANG", "en-IN")
        self._backend_ready = False
        self._chat_history: List[Dict[str, Any]] = []
        self._stream_timer = QTimer(self)
        self._stream_timer.timeout.connect(self._advance_stream)
        self._stream_message_index = -1
        self._stream_target_text = ""

        # ── PHASE 2: Build the Jarvis dashboard ──
        self.setWindowTitle("A.N.K.I.T.A")
        self.resize(1200, 740)
        self.setMinimumSize(800, 500)
        self.setStyleSheet(_MASTER_QSS)

        central = QWidget()
        central.setObjectName("centralRoot")
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ──────── LEFT SIDEBAR ────────
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(60)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(8, 16, 8, 16)
        sb_layout.setSpacing(4)

        # Logo
        logo = QLabel("A")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(40, 40)
        logo.setStyleSheet(
            f"background: {_JARVIS_CYAN_DIM}; color: {_JARVIS_CYAN};"
            f" border-radius: 20px; font-size: 16px; font-weight: bold;"
            f" font-family: {_JARVIS_FONT};"
        )
        glow = QGraphicsDropShadowEffect()
        glow.setBlurRadius(20)
        glow.setColor(QColor(_JARVIS_CYAN))
        glow.setOffset(0, 0)
        logo.setGraphicsEffect(glow)
        sb_layout.addWidget(logo, alignment=Qt.AlignCenter)
        sb_layout.addSpacing(20)

        # Nav buttons
        nav_icons = [
            ("\u2302", "Home"),     # ⌂
            ("\u2601", "Chat"),     # ☁ (message icon)
            ("\u2699", "Settings"), # ⚙
        ]
        self._nav_btns = []
        for i, (icon, tooltip) in enumerate(nav_icons):
            btn = QPushButton(icon)
            btn.setToolTip(tooltip)
            btn.setProperty("class", "sideBtn")
            btn.setFixedSize(40, 40)
            btn.setCheckable(True)
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; border: none;"
                f" border-radius: 8px; padding: 0; color: {_JARVIS_TEXT_DIM};"
                f" font-size: 18px; }}"
                f"QPushButton:hover {{ background: {_JARVIS_BORDER}; color: {_JARVIS_CYAN}; }}"
                f"QPushButton:checked {{ background: rgba(0,212,255,0.05);"
                f" color: {_JARVIS_CYAN}; border-left: 2px solid {_JARVIS_CYAN}; }}"
            )
            btn.clicked.connect(lambda checked, idx=i: self._on_nav_click(idx))
            sb_layout.addWidget(btn, alignment=Qt.AlignCenter)
            self._nav_btns.append(btn)
        self._nav_btns[0].setChecked(True)

        # Unread message indicator on chat button
        self._unread_count = 0
        self._chat_dot = QLabel(self._nav_btns[1])
        self._chat_dot.setFixedSize(8, 8)
        self._chat_dot.move(30, 4)
        self._chat_dot.setStyleSheet(
            f"background: {_JARVIS_RED}; border-radius: 4px; border: none;"
        )
        self._chat_dot.hide()

        sb_layout.addStretch()

        # Bottom sidebar icons
        settings_btn = QPushButton("\u2699")
        settings_btn.setFixedSize(32, 32)
        settings_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {_JARVIS_TEXT_DIM};"
            f" font-size: 16px; border-radius: 16px; }}"
            f"QPushButton:hover {{ color: {_JARVIS_CYAN}; }}"
        )
        sb_layout.addWidget(settings_btn, alignment=Qt.AlignCenter)

        root_layout.addWidget(sidebar)

        # ──────── CENTER PANEL (stacked: orb home / chat) ────────
        self._center_stack = QStackedWidget()
        self._center_stack.setStyleSheet(f"background: {_JARVIS_BG};")

        # ═══════════════ PAGE 0 : ORB HOME ═══════════════
        orb_page = QWidget()
        orb_page.setStyleSheet(f"background: {_JARVIS_BG};")
        orb_lay = QVBoxLayout(orb_page)
        orb_lay.setContentsMargins(24, 12, 24, 10)
        orb_lay.setSpacing(0)

        # Header row (shared look on both pages)
        header = QHBoxLayout()
        header.setSpacing(12)
        import datetime
        hour = datetime.datetime.now().hour
        greet = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")
        greet_label = QLabel(f"{greet}, System Ready.")
        greet_label.setStyleSheet(
            f"color: {_JARVIS_TEXT}; font-size: 18px; font-weight: bold;"
            f" font-family: {_JARVIS_FONT};"
        )
        header.addWidget(greet_label)
        header.addStretch()
        self._status_badge = QLabel("  BOOTING  ")
        self._status_badge.setStyleSheet(
            f"background: {_JARVIS_CYAN_DIM}; color: {_JARVIS_CYAN};"
            f" border-radius: 10px; padding: 4px 12px; font-size: 10px;"
            f" font-weight: bold; font-family: {_JARVIS_FONT}; letter-spacing: 1px;"
        )
        header.addWidget(self._status_badge)
        self._clock = QLabel()
        self._clock.setStyleSheet(
            f"color: {_JARVIS_TEXT_DIM}; font-size: 11px; font-family: {_JARVIS_FONT};"
        )
        self._update_clock()
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        header.addWidget(self._clock)
        orb_lay.addLayout(header)

        self._subtitle = QLabel("Neural networks initializing...")
        self._subtitle.setStyleSheet(
            f"color: {_JARVIS_TEXT_DIM}; font-size: 11px;"
            f" font-family: {_JARVIS_FONT}; padding-bottom: 4px;"
        )
        orb_lay.addWidget(self._subtitle)

        # Orb — large, dominant, centered
        orb_lay.addStretch(1)
        self._orb = _OrbWidget(size=400)
        orb_lay.addWidget(self._orb, alignment=Qt.AlignCenter)
        orb_lay.addStretch(1)

        # Input bar on orb page
        orb_input_container = QWidget()
        orb_input_container.setStyleSheet(
            f"background: {_JARVIS_SURFACE}; border-radius: 28px;"
            f" border: 1px solid {_JARVIS_BORDER};"
        )
        orb_input_inner = QHBoxLayout(orb_input_container)
        orb_input_inner.setContentsMargins(8, 6, 8, 6)
        orb_input_inner.setSpacing(8)
        self.voice_btn = QPushButton("MIC")
        self.voice_btn.setFixedSize(36, 36)
        self.voice_btn.clicked.connect(self.on_voice_toggle)
        self.voice_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none;"
            f" border-radius: 18px; font-size: 10px; font-weight: bold;"
            f" color: {_JARVIS_TEXT_DIM}; font-family: {_JARVIS_FONT}; letter-spacing: 1px; }}"
            f"QPushButton:hover {{ background: {_JARVIS_BORDER}; color: {_JARVIS_CYAN}; }}"
            f"QPushButton:disabled {{ color: #111; }}"
        )
        self.voice_btn.setDisabled(True)
        orb_input_inner.addWidget(self.voice_btn)
        self.input = QLineEdit()
        self.input.setObjectName("inputField")
        self.input.setPlaceholderText("Ask ANKITA anything...")
        self.input.setFont(_ui_font(12))
        self.input.returnPressed.connect(self.on_send)
        self.input.setDisabled(True)
        self.input.setStyleSheet(
            f"QLineEdit {{ background: transparent; color: {_JARVIS_TEXT};"
            f" border: none; padding: 8px 4px; font-size: 13px;"
            f" font-family: {_JARVIS_FONT}; }}"
            f"QLineEdit:disabled {{ color: {_JARVIS_TEXT_DIM}; }}"
        )
        orb_input_inner.addWidget(self.input, stretch=1)
        self.send_btn = QPushButton("\u27A4")  # ➤
        self.send_btn.setFixedSize(36, 36)
        self.send_btn.clicked.connect(self.on_send)
        self.send_btn.setStyleSheet(
            f"QPushButton {{ background: {_JARVIS_CYAN}; border: none;"
            f" border-radius: 18px; font-size: 16px; color: {_JARVIS_BG};"
            f" font-weight: bold; }}"
            f"QPushButton:hover {{ background: {_JARVIS_GREEN}; }}"
            f"QPushButton:disabled {{ background: {_JARVIS_BORDER}; color: #222; }}"
        )
        self.send_btn.setDisabled(True)
        orb_input_inner.addWidget(self.send_btn)
        orb_lay.addWidget(orb_input_container)
        orb_lay.addSpacing(6)

        # Quick action chips
        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)
        chips_row.addStretch()
        chip_labels = ["Generate Report", "System Diagnostics", "Schedule Task"]
        self._chips = []
        for label in chip_labels:
            chip = QPushButton(label)
            chip.setStyleSheet(_chip_qss())
            chip.clicked.connect(lambda checked, t=label: self._on_chip_click(t))
            chip.setDisabled(True)
            chips_row.addWidget(chip)
            self._chips.append(chip)
        chips_row.addStretch()
        orb_lay.addLayout(chips_row)
        orb_lay.addSpacing(4)

        # Status bar
        status_row = QHBoxLayout()
        self._reactor = QLabel()
        self._reactor.setFixedSize(6, 6)
        self._reactor.setStyleSheet(f"background: {_JARVIS_CYAN}; border-radius: 3px;")
        status_row.addWidget(self._reactor)
        status_row.addSpacing(4)
        self.status_label = QLabel("INITIALIZING SYSTEMS")
        self.status_label.setObjectName("statusLabel")
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        self._mode_label = QLabel("DIRECT ACCESS MODE")
        self._mode_label.setStyleSheet(
            f"color: {_JARVIS_TEXT_DIM}; font-size: 10px;"
            f" font-family: {_JARVIS_FONT}; letter-spacing: 2px;"
        )
        status_row.addWidget(self._mode_label)
        orb_lay.addLayout(status_row)

        self._center_stack.addWidget(orb_page)  # index 0

        # ═══════════════ PAGE 1 : CHAT ═══════════════
        chat_page = QWidget()
        chat_page.setStyleSheet(f"background: {_JARVIS_BG};")
        chat_lay = QVBoxLayout(chat_page)
        chat_lay.setContentsMargins(24, 12, 24, 10)
        chat_lay.setSpacing(4)

        # Chat header
        chat_header = QHBoxLayout()
        chat_title = QLabel("COMMUNICATIONS")
        chat_title.setStyleSheet(
            f"color: {_JARVIS_CYAN}; font-size: 13px; font-weight: bold;"
            f" font-family: {_JARVIS_FONT}; letter-spacing: 3px;"
        )
        chat_header.addWidget(chat_title)
        chat_header.addStretch()
        back_btn = QPushButton("< BACK")
        back_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none;"
            f" color: {_JARVIS_TEXT_DIM}; font-size: 10px;"
            f" font-family: {_JARVIS_FONT}; letter-spacing: 1px; }}"
            f"QPushButton:hover {{ color: {_JARVIS_CYAN}; }}"
        )
        back_btn.clicked.connect(lambda: self._on_nav_click(0))
        chat_header.addWidget(back_btn)
        chat_lay.addLayout(chat_header)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background: {_JARVIS_BORDER};")
        chat_lay.addWidget(sep2)

        # Chat browser
        self.chat = QTextBrowser()
        self.chat.setObjectName("chatView")
        self.chat.setReadOnly(True)
        self.chat.setOpenLinks(False)
        self.chat.anchorClicked.connect(self._on_feedback_link_clicked)
        self.chat.setFont(_ui_font(11))
        chat_lay.addWidget(self.chat, stretch=1)

        # Chat input bar (mirrors orb input but separate widget)
        chat_input_container = QWidget()
        chat_input_container.setStyleSheet(
            f"background: {_JARVIS_SURFACE}; border-radius: 28px;"
            f" border: 1px solid {_JARVIS_BORDER};"
        )
        chat_input_inner = QHBoxLayout(chat_input_container)
        chat_input_inner.setContentsMargins(8, 6, 8, 6)
        chat_input_inner.setSpacing(8)
        self._chat_input = QLineEdit()
        self._chat_input.setPlaceholderText("Type a message...")
        self._chat_input.setFont(_ui_font(12))
        self._chat_input.returnPressed.connect(self._on_chat_send)
        self._chat_input.setDisabled(True)
        self._chat_input.setStyleSheet(
            f"QLineEdit {{ background: transparent; color: {_JARVIS_TEXT};"
            f" border: none; padding: 8px 4px; font-size: 13px;"
            f" font-family: {_JARVIS_FONT}; }}"
        )
        chat_input_inner.addWidget(self._chat_input, stretch=1)
        chat_send = QPushButton("\u27A4")
        chat_send.setFixedSize(36, 36)
        chat_send.clicked.connect(self._on_chat_send)
        chat_send.setStyleSheet(
            f"QPushButton {{ background: {_JARVIS_CYAN}; border: none;"
            f" border-radius: 18px; font-size: 16px; color: {_JARVIS_BG};"
            f" font-weight: bold; }}"
            f"QPushButton:hover {{ background: {_JARVIS_GREEN}; }}"
        )
        chat_input_inner.addWidget(chat_send)
        chat_lay.addWidget(chat_input_container)

        self._center_stack.addWidget(chat_page)  # index 1

        root_layout.addWidget(self._center_stack, stretch=1)

        # ──────── RIGHT PANEL ────────
        right = QWidget()
        right.setObjectName("rightPanel")
        right.setFixedWidth(260)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 16, 12, 16)
        right_layout.setSpacing(12)

        # System Pulse card
        self._sys_card = _InfoCard("System Pulse")
        self._cpu_val = self._sys_card.add_metric("Neural Engine", "0%", _JARVIS_GREEN)
        self._sys_bar = self._sys_card.add_bar(0.0, _JARVIS_GREEN)
        self._mem_val = self._sys_card.add_metric("Memory Cluster", "0 GB", _JARVIS_CYAN)
        right_layout.addWidget(self._sys_card)

        # Runtime card
        self._runtime_card = _InfoCard("Runtime")
        self._runtime_card.set_status(False)
        self._runtime_status = self._runtime_card.add_metric("Status", "Offline", _JARVIS_TEXT_DIM)
        self._runtime_mode = self._runtime_card.add_metric("Mode", "Direct", _JARVIS_CYAN)
        right_layout.addWidget(self._runtime_card)

        # Context / recent activity card
        self._ctx_card = _InfoCard("Context")
        self._ctx_card.set_status(True)
        self._ctx_items: list[QLabel] = []
        for _ in range(3):
            lbl = QLabel("--")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"color: {_JARVIS_TEXT_DIM}; font-size: 10px;"
                f" font-family: {_JARVIS_FONT}; border: none;"
                " background: transparent; padding: 2px 0;"
            )
            self._ctx_card._body.addWidget(lbl)
            self._ctx_items.append(lbl)
        right_layout.addWidget(self._ctx_card)

        # Uptime card
        self._uptime_card = _InfoCard("Uptime")
        self._uptime_val = self._uptime_card.add_metric("Session", "0m", _JARVIS_GREEN)
        self._uptime_start = time.time()
        right_layout.addWidget(self._uptime_card)

        # Network card
        self._net_card = _InfoCard("Network")
        self._net_status = self._net_card.add_metric("Status", "Checking...", _JARVIS_TEXT_DIM)
        self._net_latency = self._net_card.add_metric("Latency", "--", _JARVIS_TEXT_DIM)
        right_layout.addWidget(self._net_card)

        # Voice card
        self._voice_card = _InfoCard("Voice Engine")
        self._voice_card.set_status(False)
        self._voice_status = self._voice_card.add_metric("Status", "Standby", _JARVIS_TEXT_DIM)
        self._voice_mic = self._voice_card.add_metric("Device", "Default", _JARVIS_TEXT_DIM)
        right_layout.addWidget(self._voice_card)

        # Scroll the right panel
        right_scroll = QScrollArea()
        right_scroll.setWidget(right)
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right_scroll.setStyleSheet(
            f"QScrollArea {{ background: {_JARVIS_SURFACE}; border: none; }}"
            f"QScrollBar:vertical {{ background: transparent; width: 4px; }}"
            f"QScrollBar::handle:vertical {{ background: {_JARVIS_BORDER}; border-radius: 2px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )
        right_scroll.setFixedWidth(264)

        # Connection info at bottom of right panel
        conn_label = QLabel(f"v5.0  JARVIS CORE")
        conn_label.setStyleSheet(
            f"color: {_JARVIS_TEXT_DIM}; font-size: 9px;"
            f" font-family: {_JARVIS_FONT}; letter-spacing: 1px;"
        )
        conn_label.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(conn_label)

        root_layout.addWidget(right_scroll)

        # Hidden reset btn (keyboard shortcut or command)
        self.reset_btn = QPushButton()
        self.reset_btn.setVisible(False)
        self.reset_btn.clicked.connect(self.on_reset)

        # ── System stats timer ──
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._update_system_stats)
        self._stats_timer.start(5000)
        self._update_system_stats()

        # ── PHASE 3: Background init ──
        self._startup_worker = _StartupWorker(self._runtime)
        self._startup_worker.progress.connect(self._on_startup_progress)
        self._startup_worker.ready.connect(self._on_startup_ready)
        self._startup_worker.failed.connect(self._on_startup_failed)
        self._startup_worker.start()

    # -----------------------------------------------------------------------
    # Clock / Stats helpers
    # -----------------------------------------------------------------------

    def _update_clock(self) -> None:
        import datetime
        now = datetime.datetime.now()
        self._clock.setText(now.strftime("%I:%M:%S %p"))

    def _update_system_stats(self) -> None:
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0)
            mem = psutil.virtual_memory()
            mem_used = mem.used / (1024 ** 3)
            mem_total = mem.total / (1024 ** 3)

            cpu_color = _JARVIS_GREEN if cpu < 60 else (_JARVIS_AMBER if cpu < 85 else _JARVIS_RED)
            self._cpu_val.setText(f"{cpu:.0f}%")
            self._cpu_val.setStyleSheet(
                f"color: {cpu_color}; font-size: 12px; font-weight: bold;"
                f" font-family: {_JARVIS_FONT};"
                " border: none; background: transparent; padding: 0;"
            )

            # Update bar
            frac = min(cpu / 100.0, 1.0)
            if hasattr(self._sys_card, "_bar_fill"):
                bar_w = max(2, int(frac * self._sys_card._bar_bg.width()))
                self._sys_card._bar_fill.setFixedWidth(bar_w)
                self._sys_card._bar_fill.setStyleSheet(
                    f"background: {cpu_color}; border-radius: 2px;"
                    " border: none; padding: 0;"
                )

            self._mem_val.setText(f"{mem_used:.1f}/{mem_total:.0f}GB")

            # Disk usage
            disk = psutil.disk_usage('/')
            disk_pct = disk.percent

            # Network — check connectivity
            net_io = psutil.net_io_counters()
            sent_mb = net_io.bytes_sent / (1024 ** 2)
            recv_mb = net_io.bytes_recv / (1024 ** 2)
            self._net_status.setText("Connected")
            self._net_status.setStyleSheet(
                f"color: {_JARVIS_GREEN}; font-size: 12px; font-weight: bold;"
                f" font-family: {_JARVIS_FONT};"
                " border: none; background: transparent; padding: 0;"
            )
            self._net_card.set_status(True)
            self._net_latency.setText(f"{recv_mb:.0f}MB rx")

        except ImportError:
            self._cpu_val.setText("N/A")
            self._mem_val.setText("psutil needed")
        except Exception:
            pass

        # Uptime
        try:
            elapsed = int(time.time() - self._uptime_start)
            hrs, rem = divmod(elapsed, 3600)
            mins, secs = divmod(rem, 60)
            if hrs > 0:
                self._uptime_val.setText(f"{hrs}h {mins}m")
            else:
                self._uptime_val.setText(f"{mins}m {secs}s")
        except Exception:
            pass

        # Voice engine status
        try:
            if self.voice_worker is not None and self.voice_worker.isRunning():
                self._voice_card.set_status(True)
                self._voice_status.setText("Active")
                self._voice_status.setStyleSheet(
                    f"color: {_JARVIS_GREEN}; font-size: 12px; font-weight: bold;"
                    f" font-family: {_JARVIS_FONT};"
                    " border: none; background: transparent; padding: 0;"
                )
            else:
                self._voice_card.set_status(False)
                self._voice_status.setText("Standby")
                self._voice_status.setStyleSheet(
                    f"color: {_JARVIS_TEXT_DIM}; font-size: 12px; font-weight: bold;"
                    f" font-family: {_JARVIS_FONT};"
                    " border: none; background: transparent; padding: 0;"
                )
        except Exception:
            pass

    def _on_chip_click(self, text: str) -> None:
        if not self._backend_ready:
            return
        self.input.setText(text)
        self.on_send()

    # -----------------------------------------------------------------------
    # Startup callbacks
    # -----------------------------------------------------------------------

    def _on_startup_progress(self, msg: str) -> None:
        self.status_label.setText(msg.upper())
        self._subtitle.setText(msg)
        self._orb.set_state("thinking", msg)

    def _on_startup_failed(self, error: str) -> None:
        self._orb.set_state("error")
        self._reactor.setStyleSheet(f"background: {_JARVIS_RED}; border-radius: 3px;")
        self._status_badge.setText("  OFFLINE  ")
        self._status_badge.setStyleSheet(
            f"background: rgba(255,51,85,0.15); color: {_JARVIS_RED};"
            f" border-radius: 10px; padding: 4px 12px; font-size: 10px;"
            f" font-weight: bold; font-family: {_JARVIS_FONT};"
        )
        self._subtitle.setText(f"Startup failed: {error}")
        self.status_label.setText("OFFLINE")
        QMessageBox.critical(self, "A.N.K.I.T.A - Startup Error", error)

    def _on_startup_ready(self, backends: dict) -> None:
        self.agent = backends["agent"]
        self.orchestrator = backends["orchestrator"]
        self.use_multi_agent = backends["use_multi_agent"]
        self.memory = backends["memory"]
        self.feedback_engine = backends["feedback_engine"]
        self._backend_ready = True

        # Enable UI
        self.input.setDisabled(False)
        self._chat_input.setDisabled(False)
        self.send_btn.setDisabled(False)
        self.voice_btn.setDisabled(False)
        for chip in self._chips:
            chip.setDisabled(False)
        self.input.setFocus()

        # Visual: online state
        self._orb.set_state("online")
        self._reactor.setStyleSheet(f"background: {_JARVIS_GREEN}; border-radius: 3px;")
        glow = QGraphicsDropShadowEffect()
        glow.setBlurRadius(12)
        glow.setColor(QColor(_JARVIS_GREEN))
        glow.setOffset(0, 0)
        self._reactor.setGraphicsEffect(glow)

        self._status_badge.setText("  LINKED  ")
        self._status_badge.setStyleSheet(
            f"background: rgba(0,255,136,0.1); color: {_JARVIS_GREEN};"
            f" border-radius: 10px; padding: 4px 12px; font-size: 10px;"
            f" font-weight: bold; font-family: {_JARVIS_FONT};"
            " letter-spacing: 1px;"
        )
        self._subtitle.setText("Neural networks idling at 98% efficiency.")
        self.status_label.setText("PROCESSOR READY")

        # Runtime card
        self._runtime_card.set_status(True)
        self._runtime_status.setText("Online")
        self._runtime_status.setStyleSheet(
            f"color: {_JARVIS_GREEN}; font-size: 12px; font-weight: bold;"
            f" font-family: {_JARVIS_FONT};"
            " border: none; background: transparent; padding: 0;"
        )
        self._runtime_mode.setText("Multi-Agent" if self.use_multi_agent else "Direct")

        if not HAS_AUDIO_STACK:
            self._append_system("Voice unavailable - pip install numpy sounddevice")

        # Proactive timer
        self._proactive_timer = QTimer(self)
        self._proactive_timer.timeout.connect(self._on_proactive_tick)
        self._proactive_timer.start(5000)

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _on_nav_click(self, idx: int) -> None:
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)
        if idx == 0:
            self._center_stack.setCurrentIndex(0)
        elif idx == 1:
            self._center_stack.setCurrentIndex(1)
            self._chat_input.setFocus()

    def _on_chat_send(self) -> None:
        text = self._chat_input.text().strip()
        if not text:
            return
        self._chat_input.clear()
        # Route through the main on_send by populating input field
        self.input.setText(text)
        self.on_send()

    def _switch_to_chat(self) -> None:
        self._center_stack.setCurrentIndex(1)
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == 1)
        self._unread_count = 0
        self._update_chat_badge()
        self._chat_input.setFocus()

    def _switch_to_orb(self) -> None:
        self._center_stack.setCurrentIndex(0)
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == 0)

    def _update_chat_badge(self) -> None:
        """Show/hide notification dot on chat nav button."""
        if self._unread_count > 0:
            self._chat_dot.show()
            self._nav_btns[1].setStyleSheet(
                f"QPushButton {{ background: transparent; border: none;"
                f" border-radius: 8px; padding: 0; color: {_JARVIS_CYAN};"
                f" font-size: 18px; }}"
                f"QPushButton:hover {{ background: {_JARVIS_BORDER}; }}"
                f"QPushButton:checked {{ background: rgba(0,212,255,0.05);"
                f" color: {_JARVIS_CYAN}; border-left: 2px solid {_JARVIS_CYAN}; }}"
            )
        else:
            self._chat_dot.hide()
            self._nav_btns[1].setStyleSheet(
                f"QPushButton {{ background: transparent; border: none;"
                f" border-radius: 8px; padding: 0; color: {_JARVIS_TEXT_DIM};"
                f" font-size: 18px; }}"
                f"QPushButton:hover {{ background: {_JARVIS_BORDER}; color: {_JARVIS_CYAN}; }}"
                f"QPushButton:checked {{ background: rgba(0,212,255,0.05);"
                f" color: {_JARVIS_CYAN}; border-left: 2px solid {_JARVIS_CYAN}; }}"
            )

    def _message_timestamp(self) -> str:
        try:
            import datetime
            return datetime.datetime.now().strftime("%H:%M")
        except Exception:
            return ""

    def _escape_chat_text(self, text: str) -> str:
        return html.escape((text or "").strip()).replace("\n", "<br>")

    def _scroll_chat_to_bottom(self) -> None:
        try:
            bar = self.chat.verticalScrollBar()
            bar.setValue(bar.maximum())
        except Exception:
            pass

    def _render_chat(self) -> None:
        blocks: List[str] = []
        for entry in self._chat_history:
            who = entry["who"]
            ts = entry["ts"]
            text_html = self._escape_chat_text(entry["text"])
            feedback_id = entry.get("feedback_id", "")
            if who in ("You", "You (voice)"):
                blocks.append(
                    f"<div style='text-align:right; margin: 8px 0;'>"
                    f"<div style='display:inline-block; max-width:72%; background:{_JARVIS_CYAN_DIM};"
                    f" color:{_JARVIS_TEXT}; border:1px solid {_JARVIS_BORDER};"
                    f" border-radius:14px 14px 4px 14px; padding:10px 14px; text-align:left;"
                    f" font-size:12px; line-height:1.55;'>{text_html}</div>"
                    f"<div style='color:{_JARVIS_TEXT_DIM}; font-size:9px; margin-top:3px;'>{ts}</div>"
                    f"</div>"
                )
            elif who in ("Assistant", "A.N.K.I.T.A"):
                feedback_html = ""
                if feedback_id:
                    feedback_html = (
                        f"<div style='margin-top:6px; font-size:11px;'>"
                        f"<a href='fb:thumbs_up:{feedback_id}' style='color:{_JARVIS_GREEN}; text-decoration:none;'>Good</a>"
                        f"&nbsp;&nbsp;&nbsp;"
                        f"<a href='fb:thumbs_down:{feedback_id}' style='color:{_JARVIS_AMBER}; text-decoration:none;'>Bad</a>"
                        f"</div>"
                    )
                blocks.append(
                    f"<div style='text-align:left; margin: 8px 0;'>"
                    f"<div style='color:{_JARVIS_CYAN}; font-size:10px; font-weight:bold; letter-spacing:1px;"
                    f" margin-bottom:3px;'>A.N.K.I.T.A <span style='color:{_JARVIS_TEXT_DIM}; font-weight:normal; font-size:9px;'>{ts}</span></div>"
                    f"<div style='display:inline-block; max-width:72%; background:{_JARVIS_SURFACE};"
                    f" color:{_JARVIS_TEXT}; border:1px solid {_JARVIS_BORDER};"
                    f" border-radius:14px 14px 14px 4px; padding:10px 14px; text-align:left;"
                    f" font-size:12px; line-height:1.6;'>{text_html}</div>"
                    f"{feedback_html}"
                    f"</div>"
                )
            else:
                blocks.append(
                    f"<div style='margin: 6px 0; text-align:center;'>"
                    f"<span style='color:{_JARVIS_TEXT_DIM}; font-size:10px; font-style:italic;'>{text_html}</span>"
                    f"</div>"
                )
        self.chat.setHtml(
            f"<div style='font-family:{_JARVIS_FONT}; padding:8px 10px 14px 10px;'>"
            + "".join(blocks)
            + "</div>"
        )
        QTimer.singleShot(0, self._scroll_chat_to_bottom)

    def _update_context_card(self, who: str, text: str) -> None:
        try:
            short = (text or "").strip().replace("\n", " ")[:60]
            if who in ("You", "You (voice)"):
                self._ctx_items[0].setText(f"You: {short}")
            elif who in ("Assistant", "A.N.K.I.T.A"):
                self._ctx_items[2].setText(self._ctx_items[1].text())
                self._ctx_items[1].setText(self._ctx_items[0].text())
                self._ctx_items[0].setText(f"ANKITA: {short}")
        except Exception:
            pass

    def _finish_streaming(self) -> None:
        if self._stream_timer.isActive():
            self._stream_timer.stop()
        if 0 <= self._stream_message_index < len(self._chat_history):
            self._chat_history[self._stream_message_index]["text"] = self._stream_target_text
        self._stream_message_index = -1
        self._stream_target_text = ""

    def _advance_stream(self) -> None:
        if self._stream_message_index < 0 or self._stream_message_index >= len(self._chat_history):
            self._finish_streaming()
            self._render_chat()
            return
        current = self._chat_history[self._stream_message_index]["text"]
        remaining = self._stream_target_text[len(current):]
        if not remaining:
            self._finish_streaming()
            self._render_chat()
            return
        chunk_size = 2 if remaining.startswith("\n") else min(8, max(3, len(remaining) // 18 or 3))
        self._chat_history[self._stream_message_index]["text"] = current + remaining[:chunk_size]
        self._render_chat()

    def _append(self, who: str, text: str, stream: bool = False, feedback_id: str = "") -> None:
        if self._center_stack.currentIndex() != 1:
            self._unread_count += 1
            self._update_chat_badge()

        self._finish_streaming()
        entry = {
            "who": who,
            "text": "" if stream and who in ("Assistant", "A.N.K.I.T.A") else (text or ""),
            "ts": self._message_timestamp(),
            "feedback_id": feedback_id,
        }
        self._chat_history.append(entry)
        self._update_context_card(who, text)
        if stream and who in ("Assistant", "A.N.K.I.T.A"):
            self._stream_message_index = len(self._chat_history) - 1
            self._stream_target_text = text or ""
            self._render_chat()
            self._stream_timer.start(18)
            return
        self._render_chat()

    def _append_system(self, text: str) -> None:
        self._append("System", text)

    def _set_busy(self, busy: bool) -> None:
        self.input.setDisabled(busy)
        self._chat_input.setDisabled(busy)
        self.send_btn.setDisabled(busy)
        if busy:
            self._orb.set_state("thinking")
            self.status_label.setText("PROCESSING QUERY")
            self._mode_label.setText("SYNTHESIS MODE")
        else:
            self._orb.set_state("online")
            self.status_label.setText("PROCESSOR READY")
            self._mode_label.setText("DIRECT ACCESS MODE")

    # -----------------------------------------------------------------------
    # Proactive tick
    # -----------------------------------------------------------------------

    _proactive_tts_busy: bool = False

    def _speak_proactive(self, text: str, max_chars: int = 220) -> None:
        api_key = os.getenv("SARVAM_API_KEY", "").strip()
        if not api_key or not text:
            return
        if self.__class__._proactive_tts_busy:
            return

        speak_text = text.strip()
        if len(speak_text) > max_chars:
            cut = speak_text[:max_chars]
            for sep in (".", "!", "?"):
                idx = cut.rfind(sep)
                if idx > max_chars // 2:
                    cut = cut[: idx + 1]
                    break
            speak_text = cut.strip()

        lang = getattr(self, "voice_lang_code", None) or "en-IN"

        def _do_tts(txt: str = speak_text, lng: str = lang) -> None:
            self.__class__._proactive_tts_busy = True
            try:
                tts_resp = voice_web._sarvam_tts(api_key=api_key, text=txt, lang_code=lng)
                audio_b64 = voice_web._extract_audio_b64(tts_resp)
                if not audio_b64:
                    return
                raw = base64.b64decode(audio_b64)
                fd, wav_path = tempfile.mkstemp(suffix=".wav")
                os.close(fd)
                try:
                    with open(wav_path, "wb") as f:
                        f.write(raw)
                    if os.name == "nt":
                        import winsound
                        winsound.PlaySound(wav_path, winsound.SND_FILENAME)
                    else:
                        os.system(f'afplay "{wav_path}" >/dev/null 2>&1 || true')
                finally:
                    try:
                        os.remove(wav_path)
                    except Exception:
                        pass
            except Exception as _tts_err:
                print(f"[GUI][ProactiveTTS] Error: {_tts_err}", flush=True)
            finally:
                self.__class__._proactive_tts_busy = False

        import threading as _pt
        _pt.Thread(target=_do_tts, daemon=True, name="ProactiveTTS").start()

    def _on_proactive_tick(self) -> None:
        return

    def on_send(self) -> None:
        if not self._backend_ready:
            return

        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()

        # Keep the chat page input in sync when send originates from the orb input.
        try:
            self._chat_input.clear()
        except Exception:
            pass

        self._append("You", text)

        if text.lower() == "/feedback stats":
            try:
                self._append("\U0001f4ca Feedback", self.feedback_engine.get_stats())
            except Exception as exc:
                self._append("\U0001f4ca Feedback", f"Error: {exc}")
            return

        if text.lower() in ("/reauth github", "/reauth-github"):
            import threading

            def _do_reauth() -> None:
                try:
                    from tools.auth_manager import get_github_token, github_token_status
                    self._append("GitHub", "Starting Device Flow...")
                    get_github_token(force_reauth=True)
                    self._append("GitHub", github_token_status())
                except Exception as exc:
                    self._append("GitHub", f"Re-auth failed: {exc}")

            threading.Thread(target=_do_reauth, daemon=True).start()
            return

        if text.lower() == "/github status":
            try:
                from tools.auth_manager import github_token_status
                self._append("GitHub", github_token_status())
            except Exception as exc:
                self._append("GitHub", f"Error: {exc}")
            return

        if self.memory:
            self.memory.save("user", text, "gui")
            self.memory.inject_into_messages(self.messages, user_query=text)

        self._pending_user_text = text

        self._set_busy(True)
        if self.worker is not None and self.worker.isRunning():
            return

        if self.use_multi_agent and self.orchestrator is not None:
            self.worker = _OrchestratorWorker(self.orchestrator, self.messages, text)
        else:
            self.worker = AskWorker(self.agent, self.messages, text)
        self.worker.done.connect(self._on_reply)
        self.worker.start()

    def _on_feedback_link_clicked(self, url) -> None:
        try:
            link = url.toString() if hasattr(url, 'toString') else str(url)
        except Exception:
            link = str(url)
        if not link.startswith("fb:"):
            import webbrowser
            webbrowser.open(link)
            return
        parts = link.split(":")
        if len(parts) < 3:
            return
        direction = parts[1]
        iid = parts[2]
        rating = "positive" if direction == "thumbs_up" else "negative"
        emoji = "\U0001f44d" if rating == "positive" else "\U0001f44e"
        try:
            self.feedback_engine.record_feedback(iid, rating)
            self._append("A.N.K.I.T.A", f"Thanks for the feedback {emoji}")
        except Exception as exc:
            self._append("A.N.K.I.T.A", f"Feedback error: {exc}")

    def _on_reply(self, reply: str, error: str) -> None:
        if error:
            self._append("Assistant [Error]", error)
        else:
            feedback_id = ""
            try:
                _iid = self.feedback_engine.new_interaction()
                self.feedback_engine.record_interaction(_iid, "", reply)
                self._last_fb_iid = _iid
                feedback_id = _iid
            except Exception:
                pass
            self._append("Assistant", reply, stream=True, feedback_id=feedback_id)
            if self.memory:
                self.memory.save("assistant", reply, "gui")
        self._pending_user_text = ""
        self._set_busy(False)
        self.input.setFocus()

    def on_reset(self) -> None:
        self.messages = new_session()
        self._finish_streaming()
        self._chat_history.clear()
        self._render_chat()
        self._switch_to_orb()
        self._orb.set_state("online")
        self._append_system("Conversation reset. Memory preserved.")

    # -----------------------------------------------------------------------
    # Voice actions
    # -----------------------------------------------------------------------

    def on_voice_toggle(self) -> None:
        if self.voice_worker is not None and self.voice_worker.isRunning():
            self.voice_worker.interrupt_speaking()
            self.voice_worker.stop()
            self.voice_worker.wait(1500)
            self.voice_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; border: none;"
                f" border-radius: 18px; font-size: 10px; font-weight: bold;"
                f" color: {_JARVIS_TEXT_DIM}; font-family: {_JARVIS_FONT}; letter-spacing: 1px; }}"
                f"QPushButton:hover {{ background: {_JARVIS_BORDER}; color: {_JARVIS_CYAN}; }}"
            )
            self.voice_btn.setText("MIC")
            self.voice_btn.setGraphicsEffect(None)
            self._orb.set_state("online")
            self.status_label.setText("PROCESSOR READY")
        else:
            if not HAS_AUDIO_STACK:
                QMessageBox.warning(self, "Voice unavailable",
                                    "Install: pip install numpy sounddevice")
                return
            api_key = os.getenv("SARVAM_API_KEY", "").strip()
            if not api_key:
                QMessageBox.warning(self, "Voice unavailable", "SARVAM_API_KEY not set in .env")
                return
            lang = self.voice_lang_code or "en-IN"
            self.voice_worker = VoiceCallWorker(
                self.orchestrator, self.messages, api_key=api_key, lang_code=lang)
            mic_label = self.voice_worker.mic_name
            if any(kw in mic_label for kw in ("invalid", "fallback", "auto (")):
                self._append("System", f"Mic fallback: {mic_label}")
            self.voice_worker.heard.connect(lambda t: self._append("You (voice)", t))
            self.voice_worker.replied.connect(lambda t: self._append("Assistant", t, stream=True))
            self.voice_worker.status.connect(lambda s: self.status_label.setText(s.upper()))
            self.voice_worker.error.connect(lambda e: self._append("Voice [Error]", e))
            self.voice_worker.finished.connect(self._on_voice_worker_finished)
            self.voice_worker.start()
            self.voice_btn.setStyleSheet(
                f"QPushButton {{ background: {_JARVIS_RED}; border: none;"
                f" border-radius: 18px; font-size: 10px; font-weight: bold;"
                f" color: #fff; font-family: {_JARVIS_FONT}; letter-spacing: 1px; }}"
                f"QPushButton:hover {{ background: #aa2244; }}"
            )
            self.voice_btn.setText("STOP")
            mic_glow = QGraphicsDropShadowEffect()
            mic_glow.setBlurRadius(20)
            mic_glow.setColor(QColor(_JARVIS_RED))
            mic_glow.setOffset(0, 0)
            self.voice_btn.setGraphicsEffect(mic_glow)
            self._orb.set_state("listening")
            self.status_label.setText(f"LISTENING ON {self.voice_worker.mic_name[:25].upper()}")

    def on_voice_stop(self) -> None:
        if self.voice_worker is not None and self.voice_worker.isRunning():
            self.on_voice_toggle()

    def _on_voice_worker_finished(self) -> None:
        print("[GUI] Voice worker finished", flush=True)
        self.voice_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none;"
            f" border-radius: 18px; font-size: 10px; font-weight: bold;"
            f" color: {_JARVIS_TEXT_DIM}; font-family: {_JARVIS_FONT}; letter-spacing: 1px; }}"
            f"QPushButton:hover {{ background: {_JARVIS_BORDER}; color: {_JARVIS_CYAN}; }}"
        )
        self.voice_btn.setText("MIC")
        self.voice_btn.setGraphicsEffect(None)
        self._orb.set_state("online")
        if self.status_label.text() not in ["PROCESSOR READY", "STOPPED"]:
            self.status_label.setText("VOICE STOPPED")

    def on_voice_start(self) -> None:
        if self.voice_worker is None or not self.voice_worker.isRunning():
            self.on_voice_toggle()

    # -----------------------------------------------------------------------
    # Cleanup
    # -----------------------------------------------------------------------

    def closeEvent(self, event: Any) -> None:
        if getattr(self, "_proactive_timer", None) is not None:
            self._proactive_timer.stop()
        self._finish_streaming()
        if self.worker is not None and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(1000)
        if self.voice_worker is not None and self.voice_worker.isRunning():
            self.voice_worker.stop()
            self.voice_worker.wait(1500)
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark palette for Fusion style
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(_JARVIS_BG))
    palette.setColor(QPalette.WindowText, QColor(_JARVIS_TEXT))
    palette.setColor(QPalette.Base, QColor(_JARVIS_SURFACE))
    palette.setColor(QPalette.AlternateBase, QColor(_JARVIS_CARD))
    palette.setColor(QPalette.Text, QColor(_JARVIS_TEXT))
    palette.setColor(QPalette.Button, QColor(_JARVIS_SURFACE))
    palette.setColor(QPalette.ButtonText, QColor(_JARVIS_TEXT))
    palette.setColor(QPalette.Highlight, QColor(_JARVIS_CYAN))
    palette.setColor(QPalette.HighlightedText, QColor("#000"))
    app.setPalette(palette)

    try:
        window = AnkitaWindow()
    except SystemExit as exc:
        QMessageBox.critical(None, "A.N.K.I.T.A - Startup Error",
                             "Failed to initialise LLM runtime.\n\n"
                             "Check your .env file (NVIDIA_API_KEY / COPILOT_GITHUB_TOKEN / GROQ_API_KEY).\n\n"
                             f"Exit code: {exc.code}")
        sys.exit(exc.code or 1)
    except Exception as exc:
        import traceback
        QMessageBox.critical(None, "A.N.K.I.T.A - Startup Error", traceback.format_exc())
        traceback.print_exc()
        sys.exit(1)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
