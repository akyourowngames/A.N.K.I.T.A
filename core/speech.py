from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
import wave
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol
import urllib.error
import urllib.request

from core.llm_service import load_dotenv

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


class ChatService(Protocol):
    def chat(self, messages: list[dict[str, str]]) -> str:
        ...


class SpeechToText(Protocol):
    def transcribe(self, audio_path: Path) -> str:
        ...

    def translate_audio_to_english(self, audio_path: Path) -> str:
        ...


@dataclass(frozen=True)
class SpeechConfig:
    provider: str
    openai_api_key: str
    openai_base_url: str
    transcription_model: str
    english_conversion: str
    translation_model: str
    local_model: str
    local_device: str
    local_compute_type: str
    local_beam_size: int
    input_device: str
    sample_rate: int
    max_seconds: float
    min_seconds: float
    silence_seconds: float
    calibration_seconds: float
    min_energy: float
    energy_multiplier: float

    @classmethod
    def from_env(cls, project_root: Path) -> "SpeechConfig":
        load_dotenv(project_root / ".env")
        return cls(
            provider=os.getenv("STT_PROVIDER", "local").strip().lower(),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            transcription_model=os.getenv("STT_MODEL", "gpt-4o-transcribe").strip(),
            english_conversion=os.getenv("STT_ENGLISH_CONVERSION", "auto").strip().lower(),
            translation_model=os.getenv("STT_TRANSLATION_MODEL", "whisper-1").strip(),
            local_model=os.getenv("STT_LOCAL_MODEL", "small").strip(),
            local_device=os.getenv("STT_LOCAL_DEVICE", "auto").strip(),
            local_compute_type=os.getenv("STT_LOCAL_COMPUTE_TYPE", "int8").strip(),
            local_beam_size=int(os.getenv("STT_LOCAL_BEAM_SIZE", "5")),
            input_device=os.getenv("STT_INPUT_DEVICE", "").strip(),
            sample_rate=int(os.getenv("STT_SAMPLE_RATE", "16000")),
            max_seconds=float(os.getenv("STT_LISTEN_MAX_SECONDS", "20")),
            min_seconds=float(os.getenv("STT_LISTEN_MIN_SECONDS", "0.8")),
            silence_seconds=float(os.getenv("STT_SILENCE_SECONDS", "1.4")),
            calibration_seconds=float(os.getenv("STT_CALIBRATION_SECONDS", "0.6")),
            min_energy=float(os.getenv("STT_MIN_ENERGY", "80")),
            energy_multiplier=float(os.getenv("STT_ENERGY_MULTIPLIER", "1.6")),
        )

    def validate(self) -> None:
        if self.provider not in {"local", "faster_whisper", "openai"}:
            raise ValueError("STT_PROVIDER must be local, faster_whisper, or openai.")
        if self.provider == "openai" and not self.openai_api_key:
            raise ValueError("Missing OPENAI_API_KEY. Add it to .env before using listening mode.")
        if self.provider == "openai" and not self.transcription_model:
            raise ValueError("Missing STT_MODEL.")
        if self.provider in {"local", "faster_whisper"} and not self.local_model:
            raise ValueError("Missing STT_LOCAL_MODEL.")
        if self.local_beam_size <= 0:
            raise ValueError("STT_LOCAL_BEAM_SIZE must be greater than 0.")
        if self.sample_rate <= 0:
            raise ValueError("STT_SAMPLE_RATE must be greater than 0.")
        if self.max_seconds <= 0:
            raise ValueError("STT_LISTEN_MAX_SECONDS must be greater than 0.")


class MicrophoneListener:
    def __init__(self, config: SpeechConfig):
        self.config = config

    def listen_to_wav(self) -> Path:
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as error:
            raise RuntimeError(
                "Listening mode needs microphone packages. Install them with: "
                "python -m pip install sounddevice numpy"
            ) from error

        sample_rate = self.config.sample_rate
        chunk_size = max(1, int(sample_rate * 0.1))
        channels = 1
        pre_roll_chunks = max(1, int(0.35 / 0.1))
        silence_chunks_needed = max(1, int(self.config.silence_seconds / 0.1))
        max_chunks = max(1, int(self.config.max_seconds / 0.1))
        min_chunks = max(1, int(self.config.min_seconds / 0.1))
        calibration_chunks = max(1, int(self.config.calibration_seconds / 0.1))
        device = _sounddevice_device(self.config.input_device)

        frames: list[bytes] = []
        full_frames: list[bytes] = []
        pre_roll: deque[bytes] = deque(maxlen=pre_roll_chunks)
        noise_samples: list[float] = []
        threshold = self.config.min_energy
        speech_started = False
        silent_chunks = 0
        peak_rms = 0.0
        input_device = sd.query_devices(device=device, kind="input") if device is not None else sd.query_devices(kind="input")
        device_name = str(input_device.get("name", "default microphone"))

        with sd.InputStream(samplerate=sample_rate, channels=channels, dtype="int16", device=device) as stream:
            for index in range(max_chunks):
                chunk, _ = stream.read(chunk_size)
                chunk_bytes = chunk.tobytes()
                rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
                peak_rms = max(peak_rms, rms)
                full_frames.append(chunk_bytes)

                if index < calibration_chunks:
                    noise_samples.append(rms)
                    pre_roll.append(chunk_bytes)
                    if index == calibration_chunks - 1:
                        ambient = sum(noise_samples) / len(noise_samples)
                        threshold = max(self.config.min_energy, ambient * self.config.energy_multiplier)
                    continue

                is_speech = rms >= threshold
                if not speech_started:
                    pre_roll.append(chunk_bytes)
                    if is_speech:
                        speech_started = True
                        frames.extend(pre_roll)
                    continue

                frames.append(chunk_bytes)
                if is_speech:
                    silent_chunks = 0
                else:
                    silent_chunks += 1

                if len(frames) >= min_chunks and silent_chunks >= silence_chunks_needed:
                    break

        if not frames:
            frames.extend(full_frames)

        duration = len(frames) * chunk_size / sample_rate
        print(
            f"Mic: {device_name} | peak {peak_rms:.0f} | threshold {threshold:.0f} | captured {duration:.1f}s"
        )
        if peak_rms < max(12, threshold * 0.25):
            print("Mic level is very low. Check Windows input device, microphone permission, or STT_INPUT_DEVICE.")
        handle = tempfile.NamedTemporaryFile(prefix="speech-", suffix=".wav", delete=False)
        path = Path(handle.name)
        handle.close()
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b"".join(frames))
        return path


class FasterWhisperSpeechToText:
    def __init__(self, config: SpeechConfig):
        config.validate()
        self.config = config
        logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError(
                "Local listening mode needs faster-whisper. Install it with: "
                "python -m pip install faster-whisper sounddevice numpy"
            ) from error

        self.model = WhisperModel(
            config.local_model,
            device=config.local_device,
            compute_type=config.local_compute_type,
        )

    def transcribe(self, audio_path: Path) -> str:
        return self._run(audio_path, task="transcribe")

    def translate_audio_to_english(self, audio_path: Path) -> str:
        return self._run(audio_path, task="translate")

    def _run(self, audio_path: Path, task: str) -> str:
        text = self._transcribe_segments(audio_path, task, vad_filter=True)
        if text:
            return text
        return self._transcribe_segments(audio_path, task, vad_filter=False)

    def _transcribe_segments(self, audio_path: Path, task: str, vad_filter: bool) -> str:
        kwargs = {
            "task": task,
            "beam_size": self.config.local_beam_size,
            "vad_filter": vad_filter,
            "condition_on_previous_text": False,
        }
        try:
            segments, _ = self.model.transcribe(
                str(audio_path),
                vad_parameters={"min_silence_duration_ms": 500},
                **kwargs,
            )
        except TypeError:
            segments, _ = self.model.transcribe(str(audio_path), **kwargs)

        text = _join_segments(segments)
        return text.strip()


class OpenAISpeechToText:
    def __init__(self, config: SpeechConfig):
        config.validate()
        self.config = config

    def transcribe(self, audio_path: Path) -> str:
        fields = {
            "model": self.config.transcription_model,
            "response_format": "json",
        }
        body, content_type = _multipart_body(
            fields=fields,
            file_field="file",
            file_path=audio_path,
            file_content_type="audio/wav",
        )
        response = self._post("/audio/transcriptions", body, content_type)
        return self._extract_text(response)

    def translate_audio_to_english(self, audio_path: Path) -> str:
        fields = {
            "model": self.config.translation_model,
            "response_format": "json",
        }
        body, content_type = _multipart_body(
            fields=fields,
            file_field="file",
            file_path=audio_path,
            file_content_type="audio/wav",
        )
        response = self._post("/audio/translations", body, content_type)
        return self._extract_text(response)

    def _post(self, endpoint: str, body: bytes, content_type: str) -> dict[str, object]:
        request = urllib.request.Request(
            f"{self.config.openai_base_url}{endpoint}",
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.openai_api_key}",
                "Content-Type": content_type,
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI speech request failed: {error.code} {details}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Could not reach OpenAI speech API: {error.reason}") from error

    @staticmethod
    def _extract_text(body: dict[str, object]) -> str:
        text = body.get("text")
        if isinstance(text, str):
            return text.strip()
        raise RuntimeError(f"Unexpected OpenAI speech response: {body}")


def create_speech_to_text(config: SpeechConfig) -> SpeechToText:
    if config.provider in {"local", "faster_whisper"}:
        return FasterWhisperSpeechToText(config)
    if config.provider == "openai":
        return OpenAISpeechToText(config)
    config.validate()
    raise ValueError(f"Unsupported STT_PROVIDER: {config.provider}")


def _join_segments(segments: Iterable[object]) -> str:
    return " ".join(
        str(getattr(segment, "text", "")).strip()
        for segment in segments
        if str(getattr(segment, "text", "")).strip()
    )


def _sounddevice_device(value: str) -> int | str | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def list_input_devices() -> list[str]:
    try:
        import sounddevice as sd
    except ImportError as error:
        raise RuntimeError("Install microphone support with: python -m pip install sounddevice numpy") from error

    devices = sd.query_devices()
    lines: list[str] = []
    for index, device in enumerate(devices):
        if int(device.get("max_input_channels", 0)) <= 0:
            continue
        name = device.get("name", "Unknown input")
        channels = device.get("max_input_channels", 0)
        default_marker = " (default)" if index == sd.default.device[0] else ""
        lines.append(f"{index}: {name} [{channels} input channels]{default_marker}")
    return lines


def convert_to_english(text: str, llm: ChatService) -> str:
    source = text.strip()
    if not source:
        return ""

    messages = [
        {
            "role": "system",
            "content": (
                "Convert the user's speech transcript to clear natural English. "
                "If it is already English, return it unchanged. Preserve names, code, "
                "commands, numbers, and intent. Return only the converted user message."
            ),
        },
        {"role": "user", "content": source},
    ]
    converted = llm.chat(messages).strip()
    return converted or source


def speech_to_english(audio_path: Path, speech: SpeechToText, llm: ChatService, config: SpeechConfig) -> str:
    if config.english_conversion == "auto" and config.provider in {"local", "faster_whisper"}:
        translated = speech.translate_audio_to_english(audio_path)
        if translated:
            return translated
        transcript = speech.transcribe(audio_path)
        return convert_to_english(transcript, llm) if transcript else ""
    if config.english_conversion in {"local_translate", "translate", "openai_translation"}:
        return speech.translate_audio_to_english(audio_path)

    transcript = speech.transcribe(audio_path)
    if config.english_conversion in {"off", "none", "false"}:
        return transcript
    if config.english_conversion not in {"auto", "llm"}:
        raise ValueError("STT_ENGLISH_CONVERSION must be auto, local_translate, llm, or off.")
    return convert_to_english(transcript, llm)


def _multipart_body(
    fields: dict[str, str],
    file_field: str,
    file_path: Path,
    file_content_type: str,
) -> tuple[bytes, str]:
    boundary = f"----codex-speech-{uuid.uuid4().hex}"
    lines: list[bytes] = []

    for name, value in fields.items():
        lines.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                f"{value}\r\n".encode("utf-8"),
            ]
        )

    filename = file_path.name
    lines.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{filename}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {file_content_type}\r\n\r\n".encode("utf-8"),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return b"".join(lines), f"multipart/form-data; boundary={boundary}"
