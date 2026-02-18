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
from PyQt5.QtCore import QThread, pyqtSignal
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
from corn import CornRunner
from llm import build_runtime_from_env
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
        self.stt_provider = (os.getenv("VOICE_STT_PROVIDER", "speech_recognition").strip().lower() or "speech_recognition")
        self.recognizer = sr.Recognizer() if HAS_SPEECH_RECOGNITION else None

    def stop(self) -> None:
        self.running = False

    def _record_chunk_wav(self) -> bytes | None:
        frames = int(self.sample_rate * self.chunk_sec)
        audio = sd.rec(frames, samplerate=self.sample_rate, channels=1, dtype="int16")
        sd.wait()
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
                    stt = voice_web._sarvam_stt(api_key=self.api_key, audio_bytes=wav_bytes, mime="audio/wav")
                    transcript = str(stt.get("transcript", "")).strip()
                    detected_lang = str(stt.get("language_code", "")).strip() or self.lang_code
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


class AnkitaWindow(QMainWindow):
    hotkey_toggle_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        load_dotenv()
        runtime = build_runtime_from_env()
        self.agent = AgentRuntime(runtime=runtime, workspace_root=WORKSPACE_ROOT)
        self.messages = new_session()
        self.worker: AskWorker | None = None
        self.voice_worker: VoiceCallWorker | None = None
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

        self.setWindowTitle("ANKITA GUI")
        self.resize(960, 700)

        root = QWidget()
        layout = QVBoxLayout(root)
        self.info = QLabel(
            f"Provider: {runtime.provider} | Model: {runtime.model} | Workspace: {WORKSPACE_ROOT}"
        )
        layout.addWidget(self.info)

        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setPlaceholderText("Conversation will appear here...")
        layout.addWidget(self.chat)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type your message...")
        self.input.returnPressed.connect(self.on_send)
        row.addWidget(self.input)

        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.on_send)
        row.addWidget(self.send_btn)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.on_reset)
        row.addWidget(self.reset_btn)

        layout.addLayout(row)

        vrow = QHBoxLayout()
        self.voice_lang = QLineEdit(os.getenv("VOICE_GUI_LANG", "en-IN"))
        self.voice_lang.setPlaceholderText("Voice lang code (e.g., en-IN, hi-IN)")
        vrow.addWidget(self.voice_lang)

        self.voice_start_btn = QPushButton("Start Voice Call")
        self.voice_start_btn.clicked.connect(self.on_voice_start)
        vrow.addWidget(self.voice_start_btn)

        self.voice_stop_btn = QPushButton("Stop Voice")
        self.voice_stop_btn.clicked.connect(self.on_voice_stop)
        self.voice_stop_btn.setEnabled(False)
        vrow.addWidget(self.voice_stop_btn)

        self.voice_status = QLabel("Voice: idle")
        vrow.addWidget(self.voice_status)

        layout.addLayout(vrow)
        self.setCentralWidget(root)
        self.hotkey_toggle_requested.connect(self._toggle_voice_by_hotkey)

        self._append("System", "ANKITA GUI ready.")
        if not HAS_AUDIO_STACK:
            self._append("System", "Voice deps missing: install numpy + sounddevice for continuous call.")
        if not HAS_SPEECH_RECOGNITION:
            self._append("System", "SpeechRecognition not installed. STT will fallback to Sarvam when VOICE_STT_PROVIDER=sarvam.")
        self._setup_hotkey_listener()

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
        safe = text.replace("\r\n", "\n").strip()
        self.chat.append(f"{who}: {safe}\n")

    def _set_busy(self, busy: bool) -> None:
        self.input.setDisabled(busy)
        self.send_btn.setDisabled(busy)
        self.reset_btn.setDisabled(busy)

    def on_send(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._append("You", text)
        self._set_busy(True)
        self.worker = AskWorker(self.agent, self.messages, text)
        self.worker.done.connect(self._on_reply)
        self.worker.start()

    def _on_reply(self, reply: str, error: str) -> None:
        if error:
            self._append("Assistant [Error]", error)
            QMessageBox.critical(self, "ANKITA Error", error)
        else:
            self._append("Assistant", reply)
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
        self.voice_worker.heard.connect(lambda t: self._append("You (voice)", t))
        self.voice_worker.replied.connect(lambda t: self._append("Assistant", t))
        self.voice_worker.status.connect(lambda s: self.voice_status.setText(f"Voice: {s}"))
        self.voice_worker.error.connect(lambda e: self._append("Voice [Error]", e))
        self.voice_worker.start()
        self.voice_start_btn.setEnabled(False)
        self.voice_stop_btn.setEnabled(True)
        self.voice_status.setText("Voice: starting...")

    def on_voice_stop(self) -> None:
        if self.voice_worker is None:
            return
        self.voice_worker.stop()
        self.voice_worker.wait(1500)
        self.voice_start_btn.setEnabled(True)
        self.voice_stop_btn.setEnabled(False)
        self.voice_status.setText("Voice: stopped")

    def closeEvent(self, event) -> None:  # type: ignore[override]
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
    app = QApplication(sys.argv)
    window = AnkitaWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
