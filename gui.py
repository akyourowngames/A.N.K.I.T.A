import base64
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
import difflib
import io
import json
import os
import re
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests
from dotenv import load_dotenv
from PyQt5.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedLayout,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView  # type: ignore
    HAS_WEB_ENGINE = True
except Exception:
    QWebEngineView = None  # type: ignore
    HAS_WEB_ENGINE = False

from agent_runtime import AgentRuntime, new_session
from corn import CornRunner
from llm import build_runtime_from_env
from tools import instagram_ops
import voice_web
from services import github_auth_service
from services import tool_settings_service

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


class GitHubDeviceCodeWorker(QThread):
    done = pyqtSignal(dict, str)

    def __init__(self, scope: str):
        super().__init__()
        self.scope = scope

    def run(self) -> None:
        try:
            payload = github_auth_service.start_device_login(scope=self.scope)
            self.done.emit(payload, "")
        except Exception as err:
            self.done.emit({}, str(err))


class GitHubDevicePollWorker(QThread):
    done = pyqtSignal(dict, str)

    def __init__(self, device_code: str, interval: int, expires_in: int):
        super().__init__()
        self.device_code = device_code
        self.interval = interval
        self.expires_in = expires_in

    def run(self) -> None:
        try:
            out = github_auth_service.wait_for_device_login(
                device_code=self.device_code,
                interval=self.interval,
                expires_in=self.expires_in,
            )
            self.done.emit(out, "")
        except Exception as err:
            self.done.emit({}, str(err))


class InstaToolWorker(QThread):
    done = pyqtSignal(dict, str)

    def __init__(self, workspace_root: Path, action: str, username: str, password: str, otp_code: str, limit: int = 30):
        super().__init__()
        self.workspace_root = workspace_root
        self.action = action
        self.username = username
        self.password = password
        self.otp_code = otp_code
        self.limit = limit

    def run(self) -> None:
        try:
            payload = instagram_ops.instagram_monitor_action(
                workspace_root=self.workspace_root,
                action=self.action,
                username=self.username or None,
                password=self.password or None,
                otp_code=self.otp_code or None,
                limit=self.limit,
            )
            self.done.emit(payload, "")
        except Exception as err:
            self.done.emit({}, str(err))


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
        self.chunk_sec = float(os.getenv("VOICE_GUI_CHUNK_SEC", "0.8"))
        self.silence_rms = float(os.getenv("VOICE_GUI_SILENCE_RMS", "450"))
        self.min_silence_rms = float(os.getenv("VOICE_GUI_MIN_SILENCE_RMS", "180"))
        self.silence_multiplier = float(os.getenv("VOICE_GUI_SILENCE_MULTIPLIER", "1.8"))
        self.local_stt_timeout_sec = float(os.getenv("VOICE_LOCAL_STT_TIMEOUT_SEC", "5"))
        self.partial_merge_window_sec = float(os.getenv("VOICE_PARTIAL_MERGE_WINDOW_SEC", "1.0"))
        self.stt_provider = (os.getenv("VOICE_STT_PROVIDER", "sarvam").strip().lower() or "sarvam")
        self.min_active_ratio = float(os.getenv("VOICE_GUI_MIN_ACTIVE_RATIO", "0.005"))
        self.end_silence_chunks = max(1, int(os.getenv("VOICE_GUI_END_SILENCE_CHUNKS", "2")))
        self.max_phrase_sec = float(os.getenv("VOICE_GUI_MAX_PHRASE_SEC", "4.0"))
        self.output_device = (os.getenv("VOICE_OUTPUT_DEVICE", "").strip() or None)
        self.output_fallback_scan = _env_bool("VOICE_OUTPUT_FALLBACK_SCAN", False)
        self.post_tts_cooldown_sec = float(os.getenv("VOICE_POST_TTS_COOLDOWN_SEC", "1.2"))
        self.echo_guard_window_sec = float(os.getenv("VOICE_ECHO_GUARD_WINDOW_SEC", "2.0"))
        self.echo_similarity_threshold = float(os.getenv("VOICE_ECHO_SIMILARITY_THRESHOLD", "0.96"))
        self.duplicate_transcript_window_sec = float(os.getenv("VOICE_DUPLICATE_TRANSCRIPT_WINDOW_SEC", "1.2"))
        gain_raw = os.getenv("VOICE_PLAYBACK_GAIN", "").strip()
        peak_raw = os.getenv("VOICE_PLAYBACK_PEAK_LIMIT", "").strip()
        self.playback_gain = float(gain_raw) if gain_raw else None
        self.playback_peak_limit = float(peak_raw) if peak_raw else None
        self.recognizer = sr.Recognizer() if HAS_SPEECH_RECOGNITION else None
        self.noise_rms_ema: float | None = None
        self.partial_buffer = ""
        self.partial_ts = 0.0
        self.preferred_output_device: Any = None
        self.mic_resume_at = 0.0
        self.last_spoken_norm = ""
        self.last_spoken_ts = 0.0
        self.last_transcript_norm = ""
        self.last_transcript_ts = 0.0

    def stop(self) -> None:
        self.running = False

    def _record_chunk_pcm(self) -> np.ndarray | None:
        frames = int(self.sample_rate * self.chunk_sec)
        audio = sd.rec(frames, samplerate=self.sample_rate, channels=1, dtype="int16")
        sd.wait()
        rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float32)))))
        if self.noise_rms_ema is None:
            self.noise_rms_ema = min(rms, self.silence_rms)
        if rms < self.silence_rms:
            self.noise_rms_ema = (0.9 * float(self.noise_rms_ema)) + (0.1 * rms)
        dynamic_thresh = max(self.min_silence_rms, min(self.silence_rms, float(self.noise_rms_ema) * self.silence_multiplier))
        if rms < dynamic_thresh:
            return None

        abs_audio = np.abs(audio.astype(np.int32))
        active_thresh = max(dynamic_thresh * 0.4, self.min_silence_rms + 4)
        active_ratio = float(np.mean(abs_audio >= active_thresh))
        strong_rms = rms >= (dynamic_thresh * 1.0)
        if (active_ratio < self.min_active_ratio) and (not strong_rms):
            return None
        return audio

    def _pcm_to_wav(self, pcm: bytes) -> bytes:
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

    def _stt_sarvam(self, wav_bytes: bytes) -> Tuple[str, str]:
        stt = voice_web._sarvam_stt(api_key=self.api_key, audio_bytes=wav_bytes, mime="audio/wav")
        transcript = str(stt.get("transcript", "")).strip()
        detected_lang = str(stt.get("language_code", "")).strip() or self.lang_code
        return transcript, detected_lang

    def _run_with_timeout(self, fn: Any, timeout_sec: float, label: str) -> Any:
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(fn)
            try:
                return fut.result(timeout=max(1.0, timeout_sec))
            except FuturesTimeout as err:
                raise RuntimeError(f"{label} timed out") from err

    def _merge_partial_transcript(self, text: str) -> str:
        if self.partial_merge_window_sec <= 0:
            self.partial_buffer = ""
            self.partial_ts = 0.0
            return str(text or "").strip()
        now = time.time()
        words = [w for w in str(text or "").strip().split() if w]
        if not words:
            return ""
        if len(words) <= 2:
            if self.partial_buffer and (now - self.partial_ts) <= self.partial_merge_window_sec:
                combo = f"{self.partial_buffer} {text}".strip()
                self.partial_buffer = ""
                self.partial_ts = 0.0
                return combo
            self.partial_buffer = str(text).strip()
            self.partial_ts = now
            return ""
        if self.partial_buffer and (now - self.partial_ts) <= self.partial_merge_window_sec:
            combo = f"{self.partial_buffer} {text}".strip()
            self.partial_buffer = ""
            self.partial_ts = 0.0
            return combo
        self.partial_buffer = ""
        self.partial_ts = 0.0
        return str(text).strip()

    def _norm_text(self, text: str) -> str:
        t = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", str(text or "").lower())).strip()
        return t

    def _is_echo_or_duplicate(self, transcript: str) -> bool:
        now = time.time()
        tr = self._norm_text(transcript)
        if len(tr) < 3:
            return True
        if self.last_transcript_norm and tr == self.last_transcript_norm and (now - self.last_transcript_ts) <= self.duplicate_transcript_window_sec:
            return True
        if self.last_spoken_norm and (now - self.last_spoken_ts) <= self.echo_guard_window_sec:
            tr_words = tr.split()
            sp_words = self.last_spoken_norm.split()
            if len(tr_words) >= 10 and len(sp_words) >= 10:
                if tr in self.last_spoken_norm or self.last_spoken_norm in tr:
                    return True
            sim = difflib.SequenceMatcher(a=tr, b=self.last_spoken_norm).ratio()
            if sim >= self.echo_similarity_threshold:
                return True
        self.last_transcript_norm = tr
        self.last_transcript_ts = now
        return False

    def _play_wav_b64(self, audio_b64: str) -> None:
        raw = base64.b64decode(audio_b64)
        try:
            with wave.open(io.BytesIO(raw), "rb") as wf:
                channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                sample_rate = wf.getframerate()
                pcm = wf.readframes(wf.getnframes())

            if sample_width == 1:
                data = np.frombuffer(pcm, dtype=np.uint8).astype(np.float32)
                data = (data - 128.0) / 128.0
            elif sample_width == 2:
                data = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            elif sample_width == 4:
                data = np.frombuffer(pcm, dtype=np.int32).astype(np.float32) / 2147483648.0
            else:
                raise RuntimeError(f"Unsupported WAV sample width: {sample_width}")

            if channels > 1:
                data = data.reshape(-1, channels)

            if self.playback_gain is not None:
                gain = max(0.0, min(1.5, float(self.playback_gain)))
                if gain != 1.0:
                    data = data * gain
            if self.playback_peak_limit is not None:
                peak_limit = max(0.2, min(1.0, float(self.playback_peak_limit)))
                peak = float(np.max(np.abs(data))) if data.size else 0.0
                if peak > peak_limit:
                    data = data * (peak_limit / peak)

            configured: Any = self.output_device
            if isinstance(configured, str) and configured.isdigit():
                configured = int(configured)

            tried = []
            candidates: List[Any] = []
            if configured is not None:
                candidates.append(configured)

            # Try current default output from PortAudio.
            try:
                default_pair = sd.default.device
                if isinstance(default_pair, (list, tuple)) and len(default_pair) > 1:
                    candidates.append(int(default_pair[1]))
            except Exception:
                pass

            # Optional broad device scan fallback. Disabled by default so playback follows
            # the active Windows default output/mixer path.
            if self.output_fallback_scan:
                try:
                    for idx, dev in enumerate(sd.query_devices()):
                        if int(dev.get("max_output_channels", 0)) > 0:
                            candidates.append(idx)
                except Exception:
                    pass

            seen = set()
            for device in candidates:
                key = str(device)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    sd.play(data, samplerate=sample_rate, device=device, blocking=True)
                    sd.wait()
                    return
                except Exception as play_err:
                    tried.append(f"{device}: {play_err}")

            # Last attempt: let sounddevice choose current default implicitly.
            try:
                sd.play(data, samplerate=sample_rate, blocking=True)
                sd.wait()
                return
            except Exception as play_err:
                tried.append(f"default: {play_err}")
                raise RuntimeError("Audio playback failed after device fallback. " + " | ".join(tried))
        except Exception:
            fd, path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            try:
                with open(path, "wb") as f:
                    f.write(raw)
                if os.name == "nt":
                    import winsound

                    winsound.PlaySound(path, winsound.SND_FILENAME)
                    return
                else:
                    # best-effort fallback for non-Windows
                    os.system(f'afplay "{path}" >/dev/null 2>&1 || true')
                    return
            finally:
                try:
                    os.remove(path)
                except Exception:
                    pass

    def run(self) -> None:
        if not HAS_AUDIO_STACK:
            self.error.emit("Voice dependencies missing. Install: pip install numpy sounddevice")
            return
        speech_chunks: List[np.ndarray] = []
        silent_after_speech = 0
        while self.running:
            try:
                now = time.time()
                if now < self.mic_resume_at:
                    self.status.emit("Listening...")
                    time.sleep(min(0.15, self.mic_resume_at - now))
                    continue
                self.status.emit("Listening...")
                chunk_pcm = self._record_chunk_pcm()
                if not self.running:
                    break
                wav_bytes: bytes | None = None
                if chunk_pcm is None:
                    if not speech_chunks:
                        continue
                    silent_after_speech += 1
                    if silent_after_speech < self.end_silence_chunks:
                        continue
                    joined = b"".join(c.tobytes() for c in speech_chunks)
                    wav_bytes = self._pcm_to_wav(joined)
                    speech_chunks = []
                    silent_after_speech = 0
                else:
                    speech_chunks.append(chunk_pcm)
                    silent_after_speech = 0
                    total_frames = sum(int(c.shape[0]) for c in speech_chunks)
                    total_sec = float(total_frames) / float(self.sample_rate)
                    if total_sec < self.max_phrase_sec:
                        continue
                    joined = b"".join(c.tobytes() for c in speech_chunks)
                    wav_bytes = self._pcm_to_wav(joined)
                    speech_chunks = []
                if not wav_bytes:
                    continue

                self.status.emit("Transcribing...")
                detected_lang = self.lang_code
                transcript = ""
                if self.stt_provider == "speech_recognition":
                    try:
                        transcript = str(
                            self._run_with_timeout(
                                lambda: self._stt_speech_recognition(wav_bytes),
                                self.local_stt_timeout_sec,
                                "local transcription",
                            )
                        ).strip()
                    except Exception:
                        self.status.emit("Transcribing (fallback)...")
                        transcript, detected_lang = self._stt_sarvam(wav_bytes)
                else:
                    transcript, detected_lang = self._stt_sarvam(wav_bytes)
                transcript = self._merge_partial_transcript(transcript)
                if not transcript:
                    continue
                if self._is_echo_or_duplicate(transcript):
                    continue
                self.heard.emit(transcript)

                self.status.emit("Thinking...")
                reply_text = self.agent.process_user_text(user_text=transcript, messages=self.messages)
                self.replied.emit(reply_text)

                self.status.emit("Speaking...")
                spoken_text = voice_web.prepare_tts_text(reply_text)
                self.last_spoken_norm = self._norm_text(spoken_text)
                self.last_spoken_ts = time.time()
                tts = voice_web._sarvam_tts(api_key=self.api_key, text=spoken_text, lang_code=detected_lang)
                audio_b64 = voice_web._extract_audio_b64(tts)
                self._play_wav_b64(audio_b64)
                self.mic_resume_at = time.time() + max(0.0, self.post_tts_cooldown_sec)
            except requests.HTTPError as err:
                speech_chunks = []
                silent_after_speech = 0
                status = err.response.status_code if err.response is not None else "?"
                body = err.response.text[:800] if err.response is not None else str(err)
                self.error.emit(f"Sarvam HTTP {status}: {body}")
                time.sleep(0.8)
            except Exception as err:
                speech_chunks = []
                silent_after_speech = 0
                self.error.emit(str(err))
                time.sleep(0.5)
        self.status.emit("Voice call stopped.")


class MapHudWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ANKITA NAV HUD")
        self.resize(1180, 760)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.map_url = ""
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        stack = QFrame()
        stack.setObjectName("stackRoot")
        root_layout.addWidget(stack)

        # Base layer: live map canvas.
        self.map_view = QWebEngineView() if HAS_WEB_ENGINE and QWebEngineView is not None else None
        if self.map_view is None:
            fallback = QLabel(
                "Live map engine is not installed.\nInstall PyQtWebEngine and restart ANKITA GUI for embedded navigation."
            )
            fallback.setAlignment(Qt.AlignCenter)
            fallback.setObjectName("fallbackMap")
            map_layer = fallback
        else:
            map_layer = self.map_view

        # Overlay layer: translucent JARVIS controls on top of map.
        overlay = QWidget()
        overlay.setAttribute(Qt.WA_StyledBackground, True)
        overlay_layout = QVBoxLayout(overlay)
        overlay_layout.setContentsMargins(18, 18, 18, 18)
        overlay_layout.setSpacing(10)
        overlay_layout.setAlignment(Qt.AlignTop)

        header = QFrame()
        header.setObjectName("glassPanel")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(4)
        title = QLabel("ANKITA Navigation")
        title.setObjectName("hudTitle")
        subtitle = QLabel("Live route overlay")
        subtitle.setObjectName("hudSubtitle")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setObjectName("hudSummary")
        header_layout.addWidget(self.summary)
        self.route_meta = QLabel("")
        self.route_meta.setWordWrap(True)
        self.route_meta.setObjectName("hudMeta")
        header_layout.addWidget(self.route_meta)
        overlay_layout.addWidget(header)

        stat_row = QHBoxLayout()
        self.distance_card = self._make_card("Distance", "--")
        self.eta_card = self._make_card("ETA", "--")
        self.mode_card = self._make_card("Mode", "--")
        stat_row.addWidget(self.distance_card)
        stat_row.addWidget(self.eta_card)
        stat_row.addWidget(self.mode_card)
        overlay_layout.addLayout(stat_row)

        steps_frame = QFrame()
        steps_frame.setObjectName("stepsFrame")
        steps_layout = QVBoxLayout(steps_frame)
        steps_layout.setContentsMargins(12, 12, 12, 12)
        steps_layout.setSpacing(8)
        steps_label = QLabel("Turn-by-turn")
        steps_label.setObjectName("stepsTitle")
        self.steps_box = QTextEdit()
        self.steps_box.setReadOnly(True)
        self.steps_box.setFixedHeight(230)
        steps_layout.addWidget(steps_label)
        steps_layout.addWidget(self.steps_box)
        overlay_layout.addWidget(steps_frame)

        btn_row = QHBoxLayout()
        self.open_map_btn = QPushButton("Open in Browser")
        self.open_map_btn.clicked.connect(self._open_map)
        btn_row.addWidget(self.open_map_btn)

        self.copy_btn = QPushButton("Copy Summary")
        self.copy_btn.clicked.connect(self._copy_summary)
        btn_row.addWidget(self.copy_btn)

        self.close_btn = QPushButton("Close Overlay")
        self.close_btn.clicked.connect(self.hide)
        btn_row.addWidget(self.close_btn)
        overlay_layout.addLayout(btn_row)
        overlay_layout.addStretch(1)

        stack_layout = QStackedLayout(stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        stack_layout.setStackingMode(QStackedLayout.StackAll)
        stack_layout.addWidget(map_layer)
        stack_layout.addWidget(overlay)

        self.setCentralWidget(root)
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #030b14;
            }
            QLabel#fallbackMap {
                color: #d9f5ff;
                font-size: 18px;
                background: #081523;
            }
            QFrame#glassPanel {
                border: 1px solid rgba(110, 197, 240, 0.55);
                border-radius: 12px;
                background: rgba(6, 16, 28, 0.68);
            }
            QLabel#hudTitle {
                color: #7cf8ff;
                font-size: 29px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QLabel#hudSubtitle {
                color: #a8c9de;
                font-size: 13px;
            }
            QLabel#hudSummary {
                color: #dff6ff;
                font-size: 15px;
                padding: 3px 2px;
            }
            QFrame#hudCard {
                border: 1px solid rgba(95, 174, 222, 0.45);
                border-radius: 10px;
                background: rgba(6, 16, 28, 0.66);
            }
            QLabel#cardTitle {
                color: #9fc6e4;
                font-size: 12px;
                padding-top: 8px;
                padding-left: 10px;
            }
            QLabel#cardValue {
                color: #dff6ff;
                font-size: 18px;
                font-weight: 600;
                padding-left: 10px;
                padding-bottom: 10px;
            }
            QLabel#hudMeta {
                color: #b9d5ea;
                font-size: 13px;
                padding: 2px 2px;
            }
            QFrame#stepsFrame {
                border: 1px solid rgba(95, 174, 222, 0.45);
                border-radius: 12px;
                background: rgba(4, 13, 22, 0.7);
            }
            QLabel#stepsTitle {
                color: #7cf8ff;
                font-size: 15px;
                font-weight: 600;
            }
            QTextEdit {
                color: #dff6ff;
                background: rgba(4, 11, 19, 0.74);
                border: 1px solid rgba(76, 140, 181, 0.5);
                border-radius: 8px;
                font-size: 14px;
            }
            QPushButton {
                background-color: rgba(10, 27, 43, 0.74);
                color: #dff6ff;
                border: 1px solid rgba(74, 136, 171, 0.75);
                border-radius: 8px;
                padding: 8px 12px;
            }
            QPushButton:hover {
                background-color: rgba(19, 52, 79, 0.85);
                border: 1px solid #63b5df;
            }
            """
        )

    def _make_card(self, title: str, value: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("hudCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        value_label = QLabel(value)
        value_label.setObjectName("cardValue")
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        frame._value_label = value_label  # type: ignore[attr-defined]
        return frame

    def _set_card_value(self, card: QFrame, value: str) -> None:
        label = getattr(card, "_value_label", None)
        if isinstance(label, QLabel):
            label.setText(value or "--")

    def _open_map(self) -> None:
        if not self.map_url:
            return
        QDesktopServices.openUrl(QUrl(self.map_url))

    def _copy_summary(self) -> None:
        payload = self.summary.text().strip()
        if self.route_meta.text().strip():
            payload = f"{payload}\n{self.route_meta.text().strip()}"
        if self.map_url:
            payload = f"{payload}\nMap: {self.map_url}"
        QApplication.clipboard().setText(payload.strip())

    def _set_map_url(self, url: str) -> None:
        clean = str(url or "").strip()
        if not clean:
            return
        if self.map_view is not None:
            self.map_view.setUrl(QUrl(clean))

    def render_route(self, route: Dict[str, Any]) -> None:
        origin = str(route.get("origin", "")).strip()
        destination = str(route.get("destination", "")).strip()
        distance = str(route.get("distance", "")).strip()
        duration = str(route.get("duration", "")).strip()
        mode = str(route.get("mode", "")).strip() or "driving"
        traffic = str(route.get("duration_in_traffic", "")).strip()
        via = str(route.get("summary", "")).strip()
        route_id = str(route.get("route_id", "")).strip()
        self.map_url = str(route.get("map_url", "")).strip()
        self._set_map_url(self.map_url)

        self.summary.setText(f"Route ready: {origin} -> {destination}.")
        self._set_card_value(self.distance_card, distance or "--")
        self._set_card_value(self.eta_card, duration or "--")
        self._set_card_value(self.mode_card, mode.title())

        meta_parts: List[str] = []
        if traffic:
            meta_parts.append(f"Traffic ETA: {traffic}")
        if via:
            meta_parts.append(f"Via: {via}")
        if route_id:
            meta_parts.append(f"Route ID: {route_id}")
        self.route_meta.setText(" | ".join(meta_parts))

        steps = route.get("steps", [])
        rows: List[str] = []
        if isinstance(steps, list):
            for i, step in enumerate(steps[:20], 1):
                if not isinstance(step, dict):
                    continue
                inst = str(step.get("instruction", "")).strip()
                dist = str(step.get("distance", "")).strip()
                dur = str(step.get("duration", "")).strip()
                suffix = ", ".join(x for x in [dist, dur] if x)
                rows.append(f"{i}. {inst}" + (f" ({suffix})" if suffix else ""))
        self.steps_box.setPlainText("\n".join(rows) if rows else "No turn-by-turn steps available.")
        self.open_map_btn.setEnabled(bool(self.map_url))

        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()


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
        self.github_code_worker: GitHubDeviceCodeWorker | None = None
        self.github_poll_worker: GitHubDevicePollWorker | None = None
        self.github_pending_device: Dict[str, Any] | None = None
        self.insta_worker: InstaToolWorker | None = None
        self.tool_settings = tool_settings_service.load_tool_settings()
        self.gui_inbox_path = WORKSPACE_ROOT / ".ankita" / "gui" / "inbox.jsonl"
        self.gui_inbox_offset = 0
        self.map_hud = MapHudWindow(self)
        self.map_hud.hide()
        self._last_map_hud_key = ""
        self.gui_inbox_timer = QTimer(self)
        self.gui_inbox_timer.setInterval(max(1000, int(float(os.getenv("GUI_INBOX_POLL_SEC", "2")) * 1000)))
        self.gui_inbox_timer.timeout.connect(self._poll_gui_inbox)

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

        tools_box = QGroupBox("Tools")
        tools_layout = QVBoxLayout(tools_box)

        self.github_enabled = QCheckBox("Enable GitHub Repo Tool")
        self.github_enabled.setChecked(bool(self.tool_settings.get("github_repo_enabled", True)))
        tools_layout.addWidget(self.github_enabled)

        limit_row = QHBoxLayout()
        limit_row.addWidget(QLabel("Default Repo List Limit"))
        self.github_repo_limit = QSpinBox()
        self.github_repo_limit.setRange(1, 200)
        self.github_repo_limit.setValue(int(self.tool_settings.get("github_default_repo_list_limit", 100)))
        limit_row.addWidget(self.github_repo_limit)
        tools_layout.addLayout(limit_row)

        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("GitHub Device Scope"))
        self.github_scope = QLineEdit(str(self.tool_settings.get("github_device_scope", "repo read:user")))
        self.github_scope.setPlaceholderText("repo read:user")
        scope_row.addWidget(self.github_scope)
        tools_layout.addLayout(scope_row)

        gh_btn_row = QHBoxLayout()
        self.github_generate_btn = QPushButton("Generate GitHub Code")
        self.github_generate_btn.clicked.connect(self.on_github_generate_code)
        gh_btn_row.addWidget(self.github_generate_btn)

        self.github_open_btn = QPushButton("Open GitHub Page")
        self.github_open_btn.clicked.connect(self.on_github_open_page)
        self.github_open_btn.setEnabled(False)
        gh_btn_row.addWidget(self.github_open_btn)

        self.github_complete_btn = QPushButton("Complete Access")
        self.github_complete_btn.clicked.connect(self.on_github_complete_access)
        self.github_complete_btn.setEnabled(False)
        gh_btn_row.addWidget(self.github_complete_btn)

        self.github_disconnect_btn = QPushButton("Disconnect")
        self.github_disconnect_btn.clicked.connect(self.on_github_disconnect)
        gh_btn_row.addWidget(self.github_disconnect_btn)

        self.tools_save_btn = QPushButton("Save Tool Settings")
        self.tools_save_btn.clicked.connect(self.on_tools_save_settings)
        gh_btn_row.addWidget(self.tools_save_btn)
        tools_layout.addLayout(gh_btn_row)

        self.github_status = QLabel("GitHub: checking status...")
        tools_layout.addWidget(self.github_status)
        self.github_code_display = QLabel("")
        self.github_code_display.setWordWrap(True)
        tools_layout.addWidget(self.github_code_display)

        tools_layout.addWidget(QLabel("Instagram Monitor"))
        insta_user_row = QHBoxLayout()
        insta_user_row.addWidget(QLabel("Instagram Username"))
        self.insta_username = QLineEdit(os.getenv("INSTAGRAM_USERNAME", ""))
        self.insta_username.setPlaceholderText("instagram username")
        insta_user_row.addWidget(self.insta_username)
        tools_layout.addLayout(insta_user_row)

        insta_pass_row = QHBoxLayout()
        insta_pass_row.addWidget(QLabel("Instagram Password"))
        self.insta_password = QLineEdit(os.getenv("INSTAGRAM_PASSWORD", ""))
        self.insta_password.setEchoMode(QLineEdit.Password)
        self.insta_password.setPlaceholderText("instagram password")
        insta_pass_row.addWidget(self.insta_password)
        tools_layout.addLayout(insta_pass_row)

        insta_otp_row = QHBoxLayout()
        insta_otp_row.addWidget(QLabel("Instagram 2FA Code"))
        self.insta_otp = QLineEdit(os.getenv("INSTAGRAM_2FA_CODE", ""))
        self.insta_otp.setPlaceholderText("6-digit code (if required)")
        insta_otp_row.addWidget(self.insta_otp)
        tools_layout.addLayout(insta_otp_row)

        insta_sid_row = QHBoxLayout()
        insta_sid_row.addWidget(QLabel("Instagram Session ID"))
        self.insta_session_id = QLineEdit(os.getenv("INSTAGRAM_SESSIONID", ""))
        self.insta_session_id.setPlaceholderText("sessionid cookie (optional, recommended)")
        insta_sid_row.addWidget(self.insta_session_id)
        tools_layout.addLayout(insta_sid_row)

        insta_btn_row = QHBoxLayout()
        self.insta_login_btn = QPushButton("Instagram Login")
        self.insta_login_btn.clicked.connect(self.on_insta_login)
        insta_btn_row.addWidget(self.insta_login_btn)

        self.insta_check_btn = QPushButton("Check Now")
        self.insta_check_btn.clicked.connect(self.on_insta_check)
        insta_btn_row.addWidget(self.insta_check_btn)

        self.insta_events_btn = QPushButton("Show Events")
        self.insta_events_btn.clicked.connect(self.on_insta_events)
        insta_btn_row.addWidget(self.insta_events_btn)

        self.insta_clear_btn = QPushButton("Clear Session")
        self.insta_clear_btn.clicked.connect(self.on_insta_clear_session)
        insta_btn_row.addWidget(self.insta_clear_btn)
        tools_layout.addLayout(insta_btn_row)

        self.insta_status = QLabel("Instagram: checking status...")
        tools_layout.addWidget(self.insta_status)

        layout.addWidget(tools_box)
        self.setCentralWidget(root)
        self.hotkey_toggle_requested.connect(self._toggle_voice_by_hotkey)

        self._append("System", "ANKITA GUI ready.")
        if not HAS_AUDIO_STACK:
            self._append("System", "Voice deps missing: install numpy + sounddevice for continuous call.")
        if not HAS_SPEECH_RECOGNITION:
            self._append("System", "SpeechRecognition not installed. STT will fallback to Sarvam when VOICE_STT_PROVIDER=sarvam.")
        self._refresh_github_status()
        self._refresh_insta_status()
        self._setup_hotkey_listener()
        self.gui_inbox_timer.start()

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

    def _extract_route_from_tool_messages(self) -> Dict[str, Any] | None:
        for msg in reversed(self.messages):
            if not isinstance(msg, dict) or msg.get("role") != "tool":
                continue
            raw = msg.get("content")
            if not isinstance(raw, str) or not raw.strip():
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            kind = str(payload.get("kind", "")).strip()
            if kind == "maps_route":
                return payload
            if kind == "maps_reroute":
                best = payload.get("best", {})
                if isinstance(best, dict):
                    return {
                        "kind": "maps_route",
                        "origin": best.get("origin", ""),
                        "destination": best.get("destination", ""),
                        "mode": best.get("mode", ""),
                        "distance": best.get("distance", ""),
                        "duration": best.get("duration", ""),
                        "duration_in_traffic": best.get("duration_in_traffic", ""),
                        "summary": best.get("summary", ""),
                        "map_url": best.get("map_url", ""),
                        "route_id": payload.get("route_id", ""),
                        "steps": [],
                    }
        return None

    def _extract_route_from_text(self, text: str) -> Dict[str, Any] | None:
        raw = str(text or "")
        lower_raw = raw.lower()
        has_map_hint = any(
            token in lower_raw
            for token in [
                "openstreetmap.org/directions",
                "google.com/maps/dir",
                "google.com/maps/search",
                "map_url",
                "route",
                "navigate",
                "navigation",
                "directions",
                "मार्ग",
                "रूट",
                "दिशा",
                "नक्शा",
            ]
        )
        if not has_map_hint:
            return None

        def _pick(label: str) -> str:
            m = re.search(rf"^{re.escape(label)}\s*(.+)$", raw, flags=re.IGNORECASE | re.MULTILINE)
            return str(m.group(1)).strip() if m else ""

        map_url = ""
        for m in re.finditer(r"https?://\S+", raw):
            cand = str(m.group(0)).strip().rstrip(").,;")
            lc = cand.lower()
            if any(
                k in lc
                for k in [
                    "openstreetmap.org/directions",
                    "google.com/maps/dir",
                    "google.com/maps/search",
                    "maps.app.goo.gl",
                    "goo.gl/maps",
                ]
            ):
                map_url = cand
                break

        steps: List[Dict[str, str]] = []
        for line in raw.splitlines():
            match = re.match(r"^\s*(\d+)\.\s+(.+)$", line.strip())
            if not match:
                continue
            steps.append({"instruction": match.group(2).strip(), "distance": "", "duration": ""})

        distance = _pick("Distance:")
        duration = _pick("ETA:")
        if not duration:
            md = re.search(r"Distance:\s*([^|]+)\|\s*ETA:\s*([^\n]+)", raw, flags=re.IGNORECASE)
            if md:
                distance = md.group(1).strip()
                duration = md.group(2).strip()

        if not map_url:
            return None
        return {
            "kind": "maps_route",
            "origin": _pick("From:"),
            "destination": _pick("To:"),
            "mode": _pick("Mode:"),
            "distance": distance,
            "duration": duration,
            "duration_in_traffic": _pick("In traffic:"),
            "summary": _pick("Via:"),
            "route_id": _pick("Route ID:"),
            "map_url": map_url,
            "steps": steps,
        }

    def _maybe_show_map_hud(self, reply_text: str) -> None:
        payload = self._extract_route_from_tool_messages()
        if payload is None:
            payload = self._extract_route_from_text(reply_text)
        if payload is None:
            return
        key = "|".join(
            [
                str(payload.get("route_id", "")),
                str(payload.get("origin", "")),
                str(payload.get("destination", "")),
                str(payload.get("duration", "")),
                str(payload.get("map_url", "")),
            ]
        )
        if key and key == self._last_map_hud_key:
            return
        self._last_map_hud_key = key
        self.map_hud.render_route(payload)

    def _poll_gui_inbox(self) -> None:
        try:
            if not self.gui_inbox_path.exists():
                lines = []
            else:
                lines = self.gui_inbox_path.read_text(encoding="utf-8").splitlines()
            if self.gui_inbox_offset < len(lines):
                new_rows = lines[self.gui_inbox_offset :]
                self.gui_inbox_offset = len(lines)
                for raw in new_rows[-50:]:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        row = json.loads(raw)
                    except Exception:
                        continue
                    if not isinstance(row, dict):
                        continue
                    text = str(row.get("text", "")).strip()
                    if not text:
                        continue
                    self._append("Assistant", text)
        except Exception:
            return

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
            self._maybe_show_map_hud(reply)
        self._set_busy(False)
        self.input.setFocus()

    def _on_voice_reply(self, reply: str) -> None:
        self._append("Assistant", reply)
        self._maybe_show_map_hud(reply)

    def on_reset(self) -> None:
        self.messages = new_session()
        self.chat.clear()

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
        self.voice_worker.replied.connect(self._on_voice_reply)
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

    def _refresh_github_status(self) -> None:
        meta = github_auth_service.cached_token_meta()
        if meta.get("connected"):
            updated_at = meta.get("updated_at")
            if isinstance(updated_at, int):
                self.github_status.setText(f"GitHub: connected (updated_at={updated_at})")
            else:
                self.github_status.setText("GitHub: connected")
        else:
            self.github_status.setText("GitHub: not connected")

    def on_tools_save_settings(self) -> None:
        self.tool_settings = tool_settings_service.save_tool_settings(
            {
                "github_repo_enabled": self.github_enabled.isChecked(),
                "github_default_repo_list_limit": int(self.github_repo_limit.value()),
                "github_device_scope": self.github_scope.text().strip() or "repo read:user",
            }
        )
        self._append("System", "Tools settings saved.")

    def on_github_generate_code(self) -> None:
        if self.github_code_worker is not None and self.github_code_worker.isRunning():
            return
        self.on_tools_save_settings()
        scope = self.github_scope.text().strip() or "repo read:user"
        self.github_status.setText("GitHub: generating device code...")
        self.github_code_display.setText("")
        self.github_generate_btn.setEnabled(False)
        self.github_code_worker = GitHubDeviceCodeWorker(scope=scope)
        self.github_code_worker.done.connect(self._on_github_code_generated)
        self.github_code_worker.start()

    def _on_github_code_generated(self, payload: Dict[str, Any], error: str) -> None:
        self.github_generate_btn.setEnabled(True)
        if error:
            self.github_status.setText("GitHub: code generation failed")
            self._append("System", f"GitHub code error: {error}")
            QMessageBox.critical(self, "GitHub Login Error", error)
            return
        self.github_pending_device = payload
        user_code = str(payload.get("user_code", "")).strip()
        uri = str(payload.get("verification_uri", "")).strip()
        self.github_code_display.setText(f"Code: {user_code}\nURL: {uri}\nPaste this code on GitHub to authorize.")
        self.github_status.setText("GitHub: code generated, waiting for authorization")
        self.github_open_btn.setEnabled(bool(uri))
        self.github_complete_btn.setEnabled(True)
        if uri:
            github_auth_service.open_verification_uri(uri)

    def on_github_open_page(self) -> None:
        if not isinstance(self.github_pending_device, dict):
            return
        uri = str(self.github_pending_device.get("verification_uri", "")).strip()
        if uri:
            github_auth_service.open_verification_uri(uri)

    def on_github_complete_access(self) -> None:
        if not isinstance(self.github_pending_device, dict):
            QMessageBox.warning(self, "GitHub Login", "Generate a device code first.")
            return
        if self.github_poll_worker is not None and self.github_poll_worker.isRunning():
            return
        device_code = str(self.github_pending_device.get("device_code", "")).strip()
        interval = int(self.github_pending_device.get("interval", 5))
        expires_in = int(self.github_pending_device.get("expires_in", 900))
        if not device_code:
            QMessageBox.warning(self, "GitHub Login", "Invalid device code. Generate a new code.")
            return
        self.github_status.setText("GitHub: waiting for authorization confirmation...")
        self.github_complete_btn.setEnabled(False)
        self.github_poll_worker = GitHubDevicePollWorker(device_code=device_code, interval=interval, expires_in=expires_in)
        self.github_poll_worker.done.connect(self._on_github_access_completed)
        self.github_poll_worker.start()

    def _on_github_access_completed(self, payload: Dict[str, Any], error: str) -> None:
        self.github_complete_btn.setEnabled(True)
        if error:
            self.github_status.setText("GitHub: authorization failed")
            self._append("System", f"GitHub authorization error: {error}")
            QMessageBox.critical(self, "GitHub Authorization Error", error)
            return
        if bool(payload.get("ok")):
            self.github_status.setText("GitHub: connected successfully")
            self.github_code_display.setText("Access granted. You can now use GitHub tools repeatedly.")
            self.github_pending_device = None
            self.github_open_btn.setEnabled(False)
            self.github_complete_btn.setEnabled(False)
            self._append("System", "GitHub connected for tools.")
        self._refresh_github_status()

    def on_github_disconnect(self) -> None:
        github_auth_service.clear_cached_token()
        self.github_pending_device = None
        self.github_code_display.setText("")
        self.github_open_btn.setEnabled(False)
        self.github_complete_btn.setEnabled(False)
        self.github_status.setText("GitHub: disconnected")
        self._append("System", "GitHub access removed from local cache.")

    def _insta_error_text(self, raw: str) -> str:
        text = str(raw or "").strip()
        lower = text.lower()
        if "467" in lower and "direct_v2/inbox" in lower:
            if "web_fallback_error" in lower:
                return (
                    "Instagram DM API is restricted. Web fallback also failed on this machine/profile. "
                    "Keep session ID valid and retry; stories/events can still be monitored."
                )
            return "Instagram DM endpoint is temporarily restricted by Instagram. A web fallback was attempted."
        if "blacklist" in lower or "ip address" in lower:
            return (
                "Instagram blocked this network/IP temporarily. "
                "Please verify account in official app, wait for cooldown, and retry from a normal residential network."
            )
        if "challenge" in lower:
            return "Instagram requested account challenge verification. Complete challenge in official app/browser first."
        if "2fa" in lower or "two-factor" in lower or "verification code" in lower or "security code" in lower:
            return "Instagram requires 2FA. Enter a fresh 2FA code in Tools and click Instagram Login."
        return text or "Instagram operation failed."

    def _set_insta_busy(self, busy: bool) -> None:
        self.insta_login_btn.setEnabled(not busy)
        self.insta_check_btn.setEnabled(not busy)
        self.insta_events_btn.setEnabled(not busy)
        self.insta_clear_btn.setEnabled(not busy)

    def _run_insta_action(self, action: str, limit: int = 30) -> None:
        if self.insta_worker is not None and self.insta_worker.isRunning():
            return
        # Keep runtime env in sync with Tools fields for immediate use.
        os.environ["INSTAGRAM_USERNAME"] = self.insta_username.text().strip()
        os.environ["INSTAGRAM_PASSWORD"] = self.insta_password.text().strip()
        os.environ["INSTAGRAM_2FA_CODE"] = self.insta_otp.text().strip()
        os.environ["INSTAGRAM_SESSIONID"] = self.insta_session_id.text().strip()
        self._set_insta_busy(True)
        self.insta_status.setText(f"Instagram: running {action}...")
        self.insta_worker = InstaToolWorker(
            workspace_root=WORKSPACE_ROOT,
            action=action,
            username=self.insta_username.text().strip(),
            password=self.insta_password.text().strip(),
            otp_code=self.insta_otp.text().strip(),
            limit=limit,
        )
        self.insta_worker.done.connect(self._on_insta_action_done)
        self.insta_worker.start()

    def _refresh_insta_status(self) -> None:
        try:
            payload = instagram_ops.instagram_monitor_action(workspace_root=WORKSPACE_ROOT, action="auth_status")
            status = str(payload.get("last_status", "unknown"))
            needs_2fa = bool(payload.get("needs_2fa", False))
            session_exists = bool(payload.get("session_exists", False))
            if status == "ok":
                self.insta_status.setText(f"Instagram: connected (session={session_exists})")
            elif needs_2fa:
                self.insta_status.setText("Instagram: needs 2FA code")
            else:
                self.insta_status.setText(f"Instagram: {status} (session={session_exists})")
        except Exception as err:
            self.insta_status.setText(f"Instagram: status error ({self._insta_error_text(str(err))})")

    def on_insta_login(self) -> None:
        self._run_insta_action("auth_login")

    def on_insta_check(self) -> None:
        self._run_insta_action("poll_once")

    def on_insta_events(self) -> None:
        self._run_insta_action("events", limit=40)

    def on_insta_clear_session(self) -> None:
        self._run_insta_action("clear_session")

    def _on_insta_action_done(self, payload: Dict[str, Any], error: str) -> None:
        self._set_insta_busy(False)
        if error:
            msg = self._insta_error_text(error)
            self.insta_status.setText("Instagram: error")
            self._append("System", f"Instagram error: {msg}")
            QMessageBox.warning(self, "Instagram Tools", msg)
            return

        action = str(payload.get("action", "")).strip()
        ok = bool(payload.get("ok", False))
        if action == "auth_status":
            self._refresh_insta_status()
            return
        if action == "auth_login":
            if ok:
                self.insta_status.setText("Instagram: login successful")
                self._append("System", "Instagram login successful. Session cached.")
            elif bool(payload.get("needs_2fa")):
                self.insta_status.setText("Instagram: 2FA required")
                self._append("System", "Instagram needs 2FA. Enter code in Tools > Instagram 2FA Code and click Instagram Login.")
            else:
                msg = self._insta_error_text(str(payload.get("error", "")))
                self.insta_status.setText("Instagram: login failed")
                self._append("System", f"Instagram login failed: {msg}")
            return
        if action == "poll_once":
            if ok:
                dm = int(payload.get("new_dm_messages", 0) or 0)
                st = int(payload.get("new_stories", 0) or 0)
                if bool(payload.get("degraded_mode")):
                    self.insta_status.setText("Instagram: check complete (degraded mode)")
                else:
                    self.insta_status.setText(f"Instagram: check complete (dm={dm}, stories={st})")
                self._append("System", f"Instagram check done. New DM: {dm}, New Stories: {st}.")
                if payload.get("warning"):
                    self._append("System", f"Instagram warning: {payload.get('warning')}")
                if payload.get("dm_error"):
                    self._append("System", f"Instagram DM endpoint: {self._insta_error_text(str(payload.get('dm_error')))}")
                if payload.get("story_error"):
                    self._append("System", f"Instagram Stories endpoint: {self._insta_error_text(str(payload.get('story_error')))}")
            elif bool(payload.get("needs_2fa")):
                self.insta_status.setText("Instagram: 2FA required")
                self._append("System", "Instagram check blocked by 2FA. Enter code in Tools and login again.")
            else:
                combined = str(payload.get("error", "")).strip()
                if not combined:
                    de = str(payload.get("dm_error", "")).strip()
                    se = str(payload.get("story_error", "")).strip()
                    ae = str(payload.get("account_error", "")).strip()
                    combined = " | ".join(x for x in [de, se, ae] if x)
                msg = self._insta_error_text(combined)
                self.insta_status.setText("Instagram: check failed")
                self._append("System", f"Instagram check failed: {msg}")
            return
        if action == "list_events":
            rows = payload.get("events", [])
            if isinstance(rows, list) and rows:
                self.insta_status.setText(f"Instagram: showing {len(rows)} events")
                shown = 0
                for row in rows[:15]:
                    if not isinstance(row, dict):
                        continue
                    typ = str(row.get("type", "")).strip()
                    if typ == "dm_new_message":
                        who = ", ".join(row.get("participants", [])[:2]) if isinstance(row.get("participants"), list) else ""
                        txt = str(row.get("text", "")).strip()
                        self._append("Instagram", f"DM from {who}: {txt[:120]}")
                    elif typ == "story_new_item":
                        self._append("Instagram", f"New story by {row.get('username', '')}")
                    else:
                        self._append("Instagram", typ or "event")
                    shown += 1
                if len(rows) > shown:
                    self._append("Instagram", f"... and {len(rows) - shown} more events")
            else:
                self.insta_status.setText("Instagram: no events")
                self._append("System", "No recent Instagram events.")
            return
        if action == "clear_session":
            self.insta_status.setText("Instagram: session cleared")
            self._append("System", "Instagram session cleared.")
            return
        self._refresh_insta_status()

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
        if self.github_code_worker is not None and self.github_code_worker.isRunning():
            self.github_code_worker.quit()
            self.github_code_worker.wait(1000)
        if self.github_poll_worker is not None and self.github_poll_worker.isRunning():
            self.github_poll_worker.quit()
            self.github_poll_worker.wait(1000)
        if self.insta_worker is not None and self.insta_worker.isRunning():
            self.insta_worker.quit()
            self.insta_worker.wait(1000)
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    window = AnkitaWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
