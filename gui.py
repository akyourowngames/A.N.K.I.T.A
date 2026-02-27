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
    QVBoxLayout,
    QWidget,
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
            reply = self.agent.process_user_text(user_text=self.user_text, messages=self.messages)
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

    def __init__(self, agent: AgentRuntime, messages: List[Dict[str, Any]],
                 api_key: str, lang_code: str):
        super().__init__()
        self.agent = agent
        self.messages = messages
        self.api_key = api_key
        self.lang_code = lang_code
        self.running = True
        self.sample_rate = int(os.getenv("VOICE_GUI_SAMPLE_RATE", "16000"))
        self.chunk_sec = float(os.getenv("VOICE_GUI_CHUNK_SEC", "4.0"))
        self.silence_rms = float(os.getenv("VOICE_GUI_SILENCE_RMS", "450"))
        self.stt_provider = os.getenv("VOICE_STT_PROVIDER", "speech_recognition").strip().lower()
        self.recognizer = sr.Recognizer() if HAS_SPEECH_RECOGNITION else None

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
                    # Device exists but is output-only — fall through to auto-detect
                    self.device_index = None
                    self.mic_name = "auto (device has no input channels)"
                    idx_str = ""  # Trigger auto-detect below
            except Exception:
                # Device index doesn't exist — warn and fall through to auto-detect
                self.device_index = None
                self.mic_name = "auto (device index invalid)"
                idx_str = ""  # Trigger auto-detect below
        else:
            # Try to find the real physical mic — prefer Realtek over virtual devices
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
                    # Last resort — use OS default even if virtual
                    default_in = sd.default.device[0]
                    self.device_index = default_in if (default_in is not None and default_in >= 0) else None
                    self.mic_name = sd.query_devices(self.device_index).get("name", "Default mic") if self.device_index is not None else "System default"
            except Exception:
                self.device_index = None
                self.mic_name = "System default mic"

    def stop(self) -> None:
        self.running = False

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
        try:
            with open(path, "wb") as f:
                f.write(raw)
            if os.name == "nt":
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME)
            else:
                os.system(f'afplay "{path}" >/dev/null 2>&1 || true')
        finally:
            try:
                os.remove(path)
            except Exception:
                pass

    def run(self) -> None:
        if not HAS_AUDIO_STACK:
            self.error.emit("Voice deps missing: pip install numpy sounddevice")
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
                self.heard.emit(transcript)

                self.status.emit("Thinking...")
                reply_text = self.agent.process_user_text(
                    user_text=transcript, messages=self.messages)
                self.replied.emit(reply_text)

                self.status.emit("Speaking...")
                tts = voice_web._sarvam_tts(
                    api_key=self.api_key, text=reply_text, lang_code=detected_lang)
                audio_b64 = voice_web._extract_audio_b64(tts)
                self._play_wav_b64(audio_b64)
            except requests.HTTPError as err:
                status = err.response.status_code if err.response is not None else "?"
                body = err.response.text[:400] if err.response is not None else str(err)
                self.error.emit(f"HTTP {status}: {body}")
                time.sleep(0.8)
            except Exception as err:
                self.error.emit(str(err))
                time.sleep(0.5)
        self.status.emit("Stopped.")


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class AnkitaWindow(QMainWindow):
    hotkey_toggle_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        load_dotenv()
        runtime = build_runtime_from_env()
        self.agent = AgentRuntime(runtime=runtime, workspace_root=WORKSPACE_ROOT)
        self.orchestrator = Orchestrator(runtime=runtime, workspace_root=WORKSPACE_ROOT)
        self.use_multi_agent = _env_bool("ANKITA_MULTI_AGENT", True)
        # MemoryStore (ChromaDB) crashes on Windows when Qt is running due to
        # SQLite C extension conflicts. Disabled in GUI mode.
        self.memory = MemoryStore.__new__(MemoryStore)
        self.memory.enabled = False
        self.memory._client = None
        self.memory._col = None
        self.session_id = "gui-session"
        self.messages = new_session()
        self.worker: AskWorker | None = None
        self.voice_worker: VoiceCallWorker | None = None
        self._content_worker: _ContentRequestWorker | None = None
        self._pending_user_text: str = ""
        self.hotkey_listener = None
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
        self.proactive.start()

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
        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
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
        self.voice_btn = QPushButton("🎙 Listen")
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
        if not HAS_AUDIO_STACK:
            self._append("System", "Voice unavailable — install numpy + sounddevice")

        self._setup_hotkey_listener()

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
    # Proactive tick
    # -----------------------------------------------------------------------

    def _on_proactive_tick(self) -> None:
        for event in self.proactive.get_pending_events():
            self._append("A.N.K.I.T.A", event.message)

            # ------------------------------------------------------------------
            # DreamState epiphany — auto-inject reply + TTS, no user input needed
            # ------------------------------------------------------------------
            if event.kind == "dream_epiphany":
                epiphany_text = event.data.get("text", event.message)
                if epiphany_text:
                    # Store in vector memory so ANKITA remembers she said this
                    try:
                        self.memory.add(self.session_id, "assistant", epiphany_text)
                    except Exception:
                        pass
                    # Speak via Sarvam TTS in a daemon thread
                    api_key = os.getenv("SARVAM_API_KEY", "").strip()
                    if api_key:
                        try:
                            lang = self.voice_lang_code or "en-IN"
                            tts = voice_web._sarvam_tts(
                                api_key=api_key, text=epiphany_text, lang_code=lang)
                            audio_b64 = voice_web._extract_audio_b64(tts)
                            import threading as _t
                            def _play_dream(b64: str = audio_b64) -> None:
                                raw = base64.b64decode(b64)
                                fd, path = tempfile.mkstemp(suffix=".wav")
                                os.close(fd)
                                try:
                                    with open(path, "wb") as f:
                                        f.write(raw)
                                    if os.name == "nt":
                                        import winsound
                                        winsound.PlaySound(path, winsound.SND_FILENAME)
                                    else:
                                        os.system(f'afplay "{path}" >/dev/null 2>&1 || true')
                                finally:
                                    try:
                                        os.remove(path)
                                    except Exception:
                                        pass
                            _t.Thread(target=_play_dream, daemon=True).start()
                        except Exception as tts_err:
                            self._append("System", f"[Dream TTS error: {tts_err}]")
                continue  # No further processing needed for dream_epiphany

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
                    api_key = os.getenv("SARVAM_API_KEY", "").strip()
                    if api_key:
                        try:
                            lang = self.voice_lang_code or "en-IN"
                            tts = voice_web._sarvam_tts(
                                api_key=api_key, text=reply, lang_code=lang)
                            audio_b64 = voice_web._extract_audio_b64(tts)
                            import threading
                            def _play() -> None:
                                import base64 as _b64, tempfile as _tf, os as _os
                                raw = _b64.b64decode(audio_b64)
                                fd, path = _tf.mkstemp(suffix=".wav")
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

        # Save user message to ChromaDB immediately so DreamAgent has memories
        self.memory.add(self.session_id, "user", text)
        self._pending_user_text = text  # store for _on_reply

        mem_context = self.memory.format_memory_context(text, n=4)
        if mem_context:
            self.messages.append({"role": "system", "content": mem_context})

        self._set_busy(True)
        if self.use_multi_agent:
            self.worker = _OrchestratorWorker(self.orchestrator, self.messages, text)
        else:
            self.worker = AskWorker(self.agent, self.messages, text)
        self.worker.done.connect(self._on_reply)
        self.worker.start()

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
        self._append("System", "Conversation reset.")

    # -----------------------------------------------------------------------
    # Voice actions
    # -----------------------------------------------------------------------

    def on_voice_toggle(self) -> None:
        if self.voice_worker is not None and self.voice_worker.isRunning():
            # Stop listening
            self.voice_worker.stop()
            self.voice_worker.wait(1500)
            self.voice_btn.setText("🎙 Listen")
            self.voice_btn.setStyleSheet(self._btn_style("#4a2a6a", "#5f3a8a"))
            self.status_label.setText("Ready.")
        else:
            # Start listening
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
                self.agent, self.messages, api_key=api_key, lang_code=lang)
            mic_label = self.voice_worker.mic_name
            if any(kw in mic_label for kw in ("invalid", "fallback", "auto (")):
                self._append("System", f"⚠️ Mic fallback: {mic_label}. Check VOICE_GUI_DEVICE_INDEX in .env")
            else:
                self._append("System", f"🎙 Mic: {mic_label}")
            self.voice_worker.heard.connect(lambda t: self._append("You (voice)", t))
            self.voice_worker.heard.connect(lambda _: self.proactive.set_last_interaction())
            self.voice_worker.replied.connect(lambda t: self._append("Assistant", t))
            self.voice_worker.status.connect(lambda s: self.status_label.setText(s))
            self.voice_worker.error.connect(lambda e: self._append("Voice [Error]", e))
            self.voice_worker.start()
            self.voice_btn.setText("⏹ Stop")
            self.voice_btn.setStyleSheet(self._btn_style("#6a2a2a", "#8a3a3a"))
            self.status_label.setText(f"Listening on {self.voice_worker.mic_name[:30]}...")

    def on_voice_stop(self) -> None:
        """Called internally (e.g. hotkey toggle)."""
        if self.voice_worker is not None and self.voice_worker.isRunning():
            self.on_voice_toggle()

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
        if self.corn_runner is not None:
            self.corn_runner.stop()
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
        # build_runtime_from_env calls sys.exit(1) on auth failure — surface it
        QMessageBox.critical(None, "A.N.K.I.T.A — Startup Error",
                             "Failed to initialise LLM runtime.\n\n"
                             "Check your .env file (COPILOT_GITHUB_TOKEN / GROQ_API_KEY).\n\n"
                             f"Exit code: {exc.code}")
        sys.exit(exc.code or 1)
    except Exception as exc:
        import traceback
        QMessageBox.critical(None, "A.N.K.I.T.A — Startup Error", traceback.format_exc())
        traceback.print_exc()
        sys.exit(1)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
