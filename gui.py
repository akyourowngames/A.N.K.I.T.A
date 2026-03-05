import base64
import asyncio
import audioop
import io
import os
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from agent_runtime import AgentRuntime, new_session
from agents import Orchestrator
from agents.hive import HiveMind
from corn import CornRunner
from llm import build_runtime_from_env
from proactive import ProactiveEngine
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

try:
    from pynput import keyboard as pynput_keyboard
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


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

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
                    # Device exists but is output-only â€” fall through to auto-detect
                    self.device_index = None
                    self.mic_name = "auto (device has no input channels)"
                    idx_str = ""  # Trigger auto-detect below
            except Exception:
                # Device index doesn't exist â€” warn and fall through to auto-detect
                self.device_index = None
                self.mic_name = "auto (device index invalid)"
                idx_str = ""  # Trigger auto-detect below
        else:
            # Try to find the real physical mic â€” prefer Realtek over virtual devices
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
                    # Last resort â€” use OS default even if virtual
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
# Wake Word Listener â€” always-on background speech recogniser
# ---------------------------------------------------------------------------

class WakeWordListener(QThread):
    """Continuously listens in the background using speech_recognition.

    Emits:
        wake_detected  â€” user said "hi ankita" / "hey ankita"
        stop_detected  â€” user said "stop" (while voice worker is active)
    """
    wake_detected = pyqtSignal()
    stop_detected = pyqtSignal()

    # Words that count as the wake phrase (any substring match, lowercase)
    WAKE_PHRASES = {
        # English variants
        "hi ankita", "hey ankita", "hello ankita",
        "hi, ankita", "hey, ankita", "hello, ankita",
        "okay ankita", "ok ankita", "oi ankita",
        "wake up ankita", "ankita wake up",
        # Common speech-recognition misheards
        "hi ankit", "hey ankit", "hello ankit",
        "hi ankitha", "hey ankitha", "hello ankitha",
        "hi an kita", "hey an kita",
        "ankita listen", "ankita start",
        # Hindi/mixed
        "ankita suno", "ankita sun",
        "hello ankita ji", "hi ankita ji",
    }
    # Words that trigger a stop
    STOP_PHRASES = {
        "stop", "stop it", "stop now", "cancel",
        "bas", "bas karo", "ruko", "quiet", "silence",
        "shut up", "enough", "pause",
    }

    def __init__(self, voice_active_flag, lang_code: str = "en-IN"):
        super().__init__()
        self._flag = voice_active_flag   # threading.Event â€” set while VoiceCallWorker records
        self._running = True
        self._lang = lang_code
        self.recognizer = sr.Recognizer() if HAS_SPEECH_RECOGNITION else None

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        print("[WakeWord] Thread started.", flush=True)
        if not HAS_SPEECH_RECOGNITION:
            print("[WakeWord] speech_recognition not available â€” thread exiting.", flush=True)
            return
        r = self.recognizer
        # Lower energy threshold â€” we only need short phrases
        r.dynamic_energy_threshold = True
        r.energy_threshold = 300
        r.pause_threshold = 0.6

        print(f"[WakeWord] Listening for wake phrases. Lang={self._lang}", flush=True)
        loop_count = 0
        while self._running:
            # Back off while VoiceCallWorker is actively recording â€” avoids mic contention
            if self._flag.is_set():
                import time as _t
                _t.sleep(0.3)
                continue

            loop_count += 1
            if loop_count % 10 == 1:
                print(f"[WakeWord] Loop #{loop_count} â€” waiting for speech...", flush=True)

            try:
                with sr.Microphone() as source:
                    # Adjust once per open
                    r.adjust_for_ambient_noise(source, duration=0.3)
                    try:
                        audio = r.listen(source, timeout=2, phrase_time_limit=4)
                    except sr.WaitTimeoutError:
                        continue
                try:
                    text = r.recognize_google(audio, language=self._lang).lower().strip()
                    print(f"[WakeWord] Heard: '{text}'", flush=True)
                except sr.UnknownValueError:
                    print("[WakeWord] Could not understand audio.", flush=True)
                    continue
                except sr.RequestError as e:
                    print(f"[WakeWord] Google STT error: {e}", flush=True)
                    continue

                # --- Wake word check ---
                if any(phrase in text for phrase in self.WAKE_PHRASES):
                    print(f"[WakeWord] WAKE WORD matched! text='{text}'", flush=True)
                    if not self._flag.is_set():   # only wake if not already listening
                        self.wake_detected.emit()
                    continue

                # --- Stop command check ---
                if any(phrase in text for phrase in self.STOP_PHRASES):
                    print(f"[WakeWord] STOP COMMAND matched! text='{text}'", flush=True)
                    if self._flag.is_set():        # only stop if currently listening
                        self.stop_detected.emit()
                    continue

            except OSError as e:
                print(f"[WakeWord] OSError (mic unavailable?): {e}", flush=True)
                import time as _t
                _t.sleep(1.0)
            except Exception as e:
                print(f"[WakeWord] Unexpected error: {e}", flush=True)
                import time as _t
                _t.sleep(0.5)

        print("[WakeWord] Thread stopped.", flush=True)


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class AnkitaWindow(QMainWindow):
    hotkey_toggle_requested = pyqtSignal()
    # Signal for safely delivering drone replies from background threads to Qt UI
    drone_reply_ready = pyqtSignal(str)  # emitted by drone thread, received by main thread

    def __init__(self) -> None:
        super().__init__()
        load_dotenv()
        runtime = build_runtime_from_env()
        self.agent = AgentRuntime(runtime=runtime, workspace_root=WORKSPACE_ROOT)
        self.orchestrator = Orchestrator(runtime=runtime, workspace_root=WORKSPACE_ROOT)
        self.use_multi_agent = _env_bool("ANKITA_MULTI_AGENT", True)

        self.session_id = "gui-session"

        self.messages = new_session()

        # Attach MemoryManager runtime so fact extraction works from GUI
        try:
            from memory import get_memory_manager
            get_memory_manager(WORKSPACE_ROOT).attach_runtime(runtime)
        except Exception:
            pass

        self.worker: AskWorker | None = None
        self.voice_worker: Any = None
        self._content_worker: _ContentRequestWorker | None = None
        self._pending_user_text: str = ""
        self.hotkey_listener = None
        # Threading event: set while VoiceCallWorker is actively recording
        # so WakeWordListener backs off and avoids mic contention
        self._voice_active_flag = threading.Event()
        self.wake_word_listener: WakeWordListener | None = None
        self.hotkey_key = os.getenv("VOICE_HOTKEY_KEY", "f8").strip().lower() or "f8"
        self.hotkey_window_ms = max(120, int(os.getenv("VOICE_HOTKEY_DOUBLE_PRESS_MS", "400")))
        self.hotkey_last_press_ts = 0.0

        # Cron runner
        self.corn_runner: CornRunner | None = None
        if _env_bool("CORN_AUTO_RUN", True):
            self.corn_runner = CornRunner(
                workspace_root=WORKSPACE_ROOT,
                poll_interval_sec=float(os.getenv("CORN_POLL_INTERVAL_SEC", "5")),
                max_jobs_per_tick=int(os.getenv("CORN_MAX_JOBS_PER_TICK", "5")),
            )
            self.corn_runner.start()

        # Proactive engine (starts without memory; memory injected after lazy init)
        self.proactive = ProactiveEngine(workspace_root=WORKSPACE_ROOT)
        self.proactive.attach_runtime(runtime)  # Required for Sentinel screen-watch to function
        self.proactive.start()

        from tools.notification_router import NotificationRouter
        self.notification_router = NotificationRouter(WORKSPACE_ROOT)

        # Watchdog system â€” always-on 24/7 monitoring
        from watchdog_manager import WatchdogManager
        self.watchdog_mgr = WatchdogManager(workspace_root=WORKSPACE_ROOT, proactive=self.proactive)
        self.watchdog_mgr.load_config()
        self.watchdog_mgr.start_all()

        # Hive Mind â€” async background task manager
        self.hive = HiveMind(
            orchestrator=self.orchestrator,
            agent_runtime=self.agent,
            use_multi_agent=self.use_multi_agent,
        )
        # Connect drone reply signal to UI handler (thread-safe Qt signal-slot)
        self.drone_reply_ready.connect(self._on_drone_reply)

        # --- Window setup ---
        self.setWindowTitle("A.N.K.I.T.A")
        self.resize(700, 520)

        root = QWidget()
        self.setCentralWidget(root)
        root.setStyleSheet("background: #111; color: #eee;")

        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(6)

        # Chat display
        self.chat = QTextBrowser()
        self.chat.setReadOnly(True)
        self.chat.setOpenLinks(False)
        self.chat.anchorClicked.connect(self._on_feedback_link_clicked)
        self.chat.setFont(QFont("Consolas", 12))
        self.chat.setStyleSheet(
            "background: #1a1a1a; color: #ddd; border: 1px solid #333;"
            " border-radius: 4px; padding: 8px;"
        )
        main_layout.addWidget(self.chat, stretch=1)

        # Input row
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a message and press Enter...")
        self.input.setFont(QFont("Consolas", 12))
        self.input.setStyleSheet(
            "background: #1a1a1a; color: #eee; border: 1px solid #444;"
            " border-radius: 4px; padding: 6px 10px;"
        )
        self.input.returnPressed.connect(self.on_send)
        input_row.addWidget(self.input, stretch=1)

        self.send_btn = QPushButton("Send")
        self.send_btn.setFixedWidth(70)
        self.send_btn.clicked.connect(self.on_send)
        self.send_btn.setStyleSheet(self._btn_style("#2a7a2a", "#3a9a3a"))
        input_row.addWidget(self.send_btn)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setFixedWidth(70)
        self.reset_btn.clicked.connect(self.on_reset)
        self.reset_btn.setStyleSheet(self._btn_style("#555", "#666"))
        input_row.addWidget(self.reset_btn)

        # Listen toggle button (single button, toggles start/stop)
        self.voice_btn = QPushButton("🎤 Listen")
        self.voice_btn.setFixedWidth(90)
        self.voice_btn.clicked.connect(self.on_voice_toggle)
        self.voice_btn.setStyleSheet(self._btn_style("#4a2a6a", "#5f3a8a"))
        input_row.addWidget(self.voice_btn)

        main_layout.addLayout(input_row)

        # Hidden lang field (still reads from .env, no visible widget)
        self.voice_lang_code = os.getenv("VOICE_GUI_LANG", "en-IN")

        # Status bar at very bottom
        self.status_label = QLabel("Ready.")
        self.status_label.setStyleSheet("color: #555; font-size: 10px;")
        main_layout.addWidget(self.status_label)

        # Connect hotkey signal
        self.hotkey_toggle_requested.connect(self._toggle_voice_by_hotkey)

        # Startup messages
        self._append("System", "ANKITA ready.")
        self._append("System", "Voice backend: sarvam")
        if not HAS_AUDIO_STACK:
            self._append("System", "Voice unavailable — install numpy + sounddevice")

        self._setup_hotkey_listener()

        # Wake word listener â€” always-on background speech recogniser
        print(f"[WakeWord] HAS_SPEECH_RECOGNITION={HAS_SPEECH_RECOGNITION}", flush=True)
        if HAS_SPEECH_RECOGNITION:
            self.wake_word_listener = WakeWordListener(
                voice_active_flag=self._voice_active_flag,
                lang_code=self.voice_lang_code or "en-IN",
            )
            self.wake_word_listener.wake_detected.connect(self._on_wake_word)
            self.wake_word_listener.stop_detected.connect(self._on_stop_command)
            self.wake_word_listener.start()
            print(f"[WakeWord] Listener started. isRunning={self.wake_word_listener.isRunning()}", flush=True)
        else:
            print("[WakeWord] NOT started â€” speech_recognition not installed.", flush=True)

        # Proactive polling timer
        self._proactive_timer = QTimer(self)
        self._proactive_timer.timeout.connect(self._on_proactive_tick)
        self._proactive_timer.start(5000)


    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _btn_style(self, bg: str, hover: str) -> str:
        return (
            f"QPushButton {{ background: {bg}; color: #eee; border: none;"
            f" border-radius: 4px; padding: 6px 12px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
            f"QPushButton:disabled {{ background: #333; color: #555; }}"
        )

    def _append(self, who: str, text: str) -> None:
        text = text.replace("\n", "<br>").strip()
        if who in ("You", "You (voice)"):
            color = "#7ec87e"
        elif who == "Assistant":
            color = "#7ec8e3"
        else:
            color = "#888"
        self.chat.append(
            f"<span style='color:{color};font-weight:bold;'>{who}:</span> "
            f"<span style='color:#ddd;'>{text}</span>"
        )

    def _set_busy(self, busy: bool) -> None:
        self.input.setDisabled(busy)
        self.send_btn.setDisabled(busy)
        self.reset_btn.setDisabled(busy)
        self.status_label.setText("Thinking..." if busy else "Ready.")

    # -----------------------------------------------------------------------
    # Hotkey
    # -----------------------------------------------------------------------

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
        if not _env_bool("VOICE_HOTKEY_ENABLED", True):
            return
        if not HAS_PYNPUT:
            return
        try:
            self.hotkey_listener = pynput_keyboard.Listener(
                on_press=self._on_global_key_press)
            self.hotkey_listener.daemon = True
            self.hotkey_listener.start()
        except Exception:
            pass

    def _toggle_voice_by_hotkey(self) -> None:
        if self.voice_worker is not None and self.voice_worker.isRunning():
            self.on_voice_stop()
        else:
            self.on_voice_start()

    # -----------------------------------------------------------------------
    # Wake word / stop command handlers
    # -----------------------------------------------------------------------

    def _on_wake_word(self) -> None:
        """Called on Qt main thread when wake word 'hi ankita' is detected."""
        print("[WakeWord] _on_wake_word() called on main thread.", flush=True)
        if self.voice_worker is not None and self.voice_worker.isRunning():
            print("[WakeWord] Already listening â€” ignoring wake.", flush=True)
            return  # Already listening â€” ignore duplicate wake
        self._append("System", "Wake word 'Hi Ankita' detected - starting voice listener...")
        self.on_voice_start()

    def _on_stop_command(self) -> None:
        """Called on Qt main thread when 'stop' is detected during active listening."""
        print("[WakeWord] _on_stop_command() called on main thread.", flush=True)
        if self.voice_worker is None or not self.voice_worker.isRunning():
            print("[WakeWord] Voice not running â€” ignoring stop.", flush=True)
            return
        self._append("System", "Stop command heard - stopping voice listener.")
        self.on_voice_stop()

    # -----------------------------------------------------------------------
    # Proactive tick
    # -----------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Sarvam TTS helper for proactive events (speaks without user input)
    # ------------------------------------------------------------------

    # Busy flag: only one proactive TTS plays at a time
    _proactive_tts_busy: bool = False

    def _speak_proactive(self, text: str, max_chars: int = 220) -> None:
        """
        Speak a proactive message via Sarvam TTS without any user input.

        Only one proactive speech plays at a time (_proactive_tts_busy guard).
        If ANKITA is already speaking a proactive message the new one is dropped
        so notifications don't queue up and play one after another for minutes.

        Smart truncation cuts at the nearest sentence boundary within max_chars.
        """
        api_key = os.getenv("SARVAM_API_KEY", "").strip()
        if not api_key or not text:
            return
        # Drop if already speaking — avoid TTS pile-up on notification floods
        if self.__class__._proactive_tts_busy:
            print(f"[GUI][ProactiveTTS] Busy — dropping: {text[:60]}", flush=True)
            return

        # Smart truncation: cut at last sentence boundary within max_chars
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
        # Drain Hive Mind drone completion notifications
        if self.hive is not None:
            for note in self.hive.check_notifications():
                self._append("🐝 Hive", note)

        for event in self.proactive.get_pending_events():
            result = self.notification_router.route_notification(event)
            if not result.get("delivered") or "gui" not in result.get("channels", []):
                continue
            formatted = result.get("formatted_messages", {}).get("gui", event.message)

            # ------------------------------------------------------------------
            # Sentinel — idle screen-watch alert
            # ------------------------------------------------------------------
            if event.kind == "sentinel":
                sentinel_text = event.data.get("text", event.message)
                idle_label = event.data.get("idle_label", "a while")
                if sentinel_text:
                    self._append("🧠 Sentinel", f"You've been away for {idle_label}:\n\n{sentinel_text}")
                    self._speak_proactive(sentinel_text)  # 🔊 auto-speak
                continue

            # ------------------------------------------------------------------
            # Morning briefing — longer TTS allowance for more content
            # ------------------------------------------------------------------
            if event.kind == "morning_briefing":
                briefing_text = event.data.get("text", event.message)
                if briefing_text:
                    self._append("☀️ Morning", briefing_text)
                    self._speak_proactive(briefing_text, max_chars=300)  # 🔊 auto-speak
                continue

            # Display the formatted message in chat for all remaining kinds
            self._append("A.N.K.I.T.A", formatted)

            # ------------------------------------------------------------------
            # Per-kind TTS — ANKITA speaks all proactive events automatically
            # ------------------------------------------------------------------
            if event.kind == "dream_epiphany":
                epiphany_text = event.data.get("text", event.message)
                if epiphany_text:
                    self._speak_proactive(epiphany_text)  # 🔊
                continue

            if event.kind == "system":
                # Battery / CPU / RAM alert — speak immediately (high urgency)
                self._speak_proactive(event.message)
                continue

            if event.kind == "auto_action":
                # AutoExecutor Class B events (battery low, stale downloads, health reminder)
                self._speak_proactive(event.message)
                continue

            if event.kind == "insight":
                # InsightSynthesizer 12h insights — ANKITA proactively shares them
                self._speak_proactive(event.message)
                continue

            if event.kind == "cron":
                # Overdue cron job alert
                self._speak_proactive(event.message)
                continue

            if event.kind == "drop_file":
                # User dropped an idea file — announce it
                self._speak_proactive(event.message)
                continue

            if event.kind == "content_request":
                suggested_prompt = event.data.get("suggested_prompt", "")
                if not suggested_prompt:
                    continue
                if self._content_worker is not None and self._content_worker.isRunning():
                    continue
                worker = _ContentRequestWorker(
                    orchestrator=self.orchestrator,
                    agent=self.agent,
                    use_multi_agent=self.use_multi_agent,
                    suggested_prompt=suggested_prompt,
                )

                def _on_content_done(reply: str, error: str) -> None:
                    if error:
                        self._append("A.N.K.I.T.A [Error]", error)
                        return
                    self._append("A.N.K.I.T.A", reply)
                    self.memory.add(self.session_id, "assistant", reply)
                    self._speak_proactive(reply)  # 🔊 speak auto-generated content too

                worker.done.connect(_on_content_done)
                worker.start()
                self._content_worker = worker
                continue

            # Generic fallback — speak any unrecognised proactive event kind
            self._speak_proactive(formatted)



    # -----------------------------------------------------------------------
    # Chat actions
    # -----------------------------------------------------------------------

    def on_send(self) -> None:
        # Record user interaction so the idle/dream tracker resets
        self.proactive.set_last_interaction()
        if self.worker is not None and self.worker.isRunning():
            return
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._append("You", text)

        # --- Hive Mind commands ---
        if text.lower() == "/hive":
            self._append("ðŸ Hive", self.hive.list_tasks())
            return
        # --- Watchdog status command ---
        if text.lower() == "/watchdogs":
            mgr = getattr(self, "watchdog_mgr", None)
            status = mgr.status() if mgr else "[Watchdog] WatchdogManager not running."
            self._append("Watchdogs", status)
            return

        # --- Implicit feedback detection (👍/👎 or "good"/"bad") ---
        _impl_fb = None
        try:
            _impl_fb = self.feedback_engine.detect_implicit_feedback(text, self._last_fb_iid)
        except Exception:
            pass
        if _impl_fb is not None:
            _emoji = "👍" if _impl_fb == "positive" else "👎"
            self._append("A.N.K.I.T.A", f"Thanks for the feedback {_emoji}")
            return

        # --- Feedback stats ---
        if text.lower() == "/feedback stats":
            try:
                self._append("📊 Feedback", self.feedback_engine.get_stats())
            except Exception as exc:
                self._append("📊 Feedback", f"Error: {exc}")
            return

        # --- GitHub re-authorization command ---
        if text.lower() in ("/reauth github", "/reauth-github"):
            import threading
            def _do_reauth():
                try:
                    from tools.auth_manager import get_github_token, github_token_status
                    self._append("GitHub", "Starting Device Flow... check the browser and enter the code shown.")
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

        if text.lower().startswith("show "):
            task_id = text[5:].strip()
            self._append("ðŸ Hive", self.hive.get_result(task_id))
            return

        # Save user message to ChromaDB immediately so DreamAgent has memories
        self.memory.add(self.session_id, "user", text)
        self._pending_user_text = text  # store for _on_reply

        # â”€â”€ Save to session vault â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        self.session.add_message("user", text)

        mem_context = self.memory.format_memory_context(text, n=4)
        if mem_context:
            self.messages.append({"role": "system", "content": mem_context})

        # Route ALL messages through HiveMind â€” fully async, never blocks UI
        # Reply arrives via Qt signal (thread-safe) from the drone thread
        def _gui_reply(reply_text: str) -> None:
            # Called from background drone thread â€” MUST use signal, not direct UI call
            if reply_text:
                self.drone_reply_ready.emit(reply_text)

        self._set_busy(True)
        ack = self.hive.delegate(text, self.messages, send_fn=_gui_reply)
        if ack:
            # Heavy task â€” show "Started ðŸ" acknowledgement immediately
            self._append("A.N.K.I.T.A", ack)
            self._set_busy(False)  # unblock UI â€” drone runs in background

    def _on_drone_reply(self, reply: str) -> None:
        """Slot called safely on the main Qt thread when a drone finishes."""
        if not reply:
            return
        self._append("A.N.K.I.T.A", reply)

        # FeedbackEngine: track this response for implicit/explicit feedback
        try:
            _iid = self.feedback_engine.new_interaction()
            self.feedback_engine.record_interaction(_iid, "", reply)
            self._last_fb_iid = _iid
            # Append thumbs up/down HTML after the response
            self.chat.append(
                f"<span style='color:#888;font-size:11px;'>"
                f"  <a href='fb:thumbs_up:{_iid}' style='color:#5f5;text-decoration:none;'>👍 Good</a>"
                f"  &nbsp;&nbsp;"
                f"  <a href='fb:thumbs_down:{_iid}' style='color:#f55;text-decoration:none;'>👎 Bad</a>"
                f"</span>"
            )
        except Exception:
            pass

        self.memory.add(self.session_id, "assistant", reply)
        # ── Save assistant reply to session vault + compress if needed ──────────
        self.session.add_message("assistant", reply)
        import threading as _t
        _t.Thread(target=self.session.compress_if_needed, daemon=True,
                  name="SessionCompressor").start()
        self._set_busy(False)
        self.input.setFocus()

    def _on_feedback_link_clicked(self, url) -> None:
        """Handle thumbs up/down anchor clicks in the chat QTextBrowser."""
        try:
            link = url.toString() if hasattr(url, 'toString') else str(url)
        except Exception:
            link = str(url)
        if not link.startswith("fb:"):
            # Let external links open normally
            import webbrowser
            webbrowser.open(link)
            return
        parts = link.split(":")
        if len(parts) < 3:
            return
        direction = parts[1]   # thumbs_up or thumbs_down
        iid = parts[2]         # interaction_id
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
            self._append("Assistant", reply)
            # Save assistant reply to ChromaDB (user message already saved in on_send)
            self.memory.add(self.session_id, "assistant", reply)
        self._pending_user_text = ""
        self._set_busy(False)
        self.input.setFocus()

    def on_reset(self) -> None:
        self.messages = new_session()
        self.session.clear()
        self._append("System", "Conversation reset.")

    # -----------------------------------------------------------------------
    # Voice actions
    # -----------------------------------------------------------------------

    def on_voice_toggle(self) -> None:
        if self.voice_worker is not None and self.voice_worker.isRunning():
            # Stop listening â€” clear the flag so WakeWordListener can resume
            self.voice_worker.interrupt_speaking()
            self.voice_worker.stop()
            self.voice_worker.wait(1500)
            self._voice_active_flag.clear()
            self.voice_btn.setText("🎤 Listen")
            self.voice_btn.setStyleSheet(self._btn_style("#4a2a6a", "#5f3a8a"))
            self.status_label.setText("Ready.")
        else:
            # Start listening with Sarvam backend
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
                self._append("System", f"⚠️ Mic fallback: {mic_label}. Check VOICE_GUI_DEVICE_INDEX in .env")
            else:
                self._append("System", f"ðŸŽ™ Mic: {mic_label}")
            self.voice_worker.heard.connect(lambda t: self._append("You (voice)", t))
            self.voice_worker.heard.connect(lambda _: self.proactive.set_last_interaction())
            self.voice_worker.replied.connect(lambda t: self._append("Assistant", t))
            self.voice_worker.status.connect(lambda s: self.status_label.setText(s))
            self.voice_worker.error.connect(lambda e: self._append("Voice [Error]", e))
            self.voice_worker.finished.connect(self._on_voice_worker_finished)
            # Set flag so WakeWordListener backs off while VoiceCallWorker holds the mic
            self._voice_active_flag.set()
            self.voice_worker.start()
            self.voice_btn.setText("⏹️ Stop")
            self.voice_btn.setStyleSheet(self._btn_style("#6a2a2a", "#8a3a3a"))
            self.status_label.setText(f"Listening on {self.voice_worker.mic_name[:30]}...")

    def on_voice_stop(self) -> None:
        """Called internally (e.g. hotkey toggle)."""
        if self.voice_worker is not None and self.voice_worker.isRunning():
            self.on_voice_toggle()
    
    def _on_voice_worker_finished(self) -> None:
        """Called when voice worker thread finishes (normally or due to crash)."""
        print("[GUI] Voice worker finished", flush=True)
        self._voice_active_flag.clear()
        self.voice_btn.setText("🎤 Listen")
        self.voice_btn.setStyleSheet(self._btn_style("#4a2a6a", "#5f3a8a"))
        if self.status_label.text() not in ["Ready.", "Stopped."]:
            self.status_label.setText("Voice stopped.")

    def on_voice_start(self) -> None:
        """Called internally (e.g. hotkey toggle)."""
        if self.voice_worker is None or not self.voice_worker.isRunning():
            self.on_voice_toggle()

    # -----------------------------------------------------------------------
    # Cleanup
    # -----------------------------------------------------------------------

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
        if self.wake_word_listener is not None and self.wake_word_listener.isRunning():
            self.wake_word_listener.stop()
            self.wake_word_listener.wait(2000)
        if self.corn_runner is not None:
            self.corn_runner.stop()
        if hasattr(self, "watchdog_mgr"):
            self.watchdog_mgr.stop_all()
        if self.hotkey_listener is not None:
            try:
                self.hotkey_listener.stop()
            except Exception:
                pass
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    try:
        window = AnkitaWindow()
    except SystemExit as exc:
        # build_runtime_from_env calls sys.exit(1) on auth failure â€” surface it
        QMessageBox.critical(None, "A.N.K.I.T.A â€” Startup Error",
                             "Failed to initialise LLM runtime.\n\n"
                             "Check your .env file (COPILOT_GITHUB_TOKEN / GROQ_API_KEY).\n\n"
                             f"Exit code: {exc.code}")
        sys.exit(exc.code or 1)
    except Exception as exc:
        import traceback
        QMessageBox.critical(None, "A.N.K.I.T.A â€” Startup Error", traceback.format_exc())
        traceback.print_exc()
        sys.exit(1)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()


