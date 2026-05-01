from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
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


class TextToSpeech(Protocol):
    def speak(self, text: str) -> None:
        ...


@dataclass(frozen=True)
class SpeechConfig:
    provider: str
    openai_api_key: str
    openai_base_url: str
    nvidia_api_key: str
    nvidia_asr_server: str
    nvidia_asr_function_id: str
    nvidia_asr_model: str
    nvidia_asr_language_code: str
    nvidia_asr_use_ssl: bool
    nvidia_asr_automatic_punctuation: bool
    nvidia_asr_file_streaming_chunk: int
    transcription_model: str
    language: str
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
    start_timeout_seconds: float
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
            nvidia_api_key=os.getenv("NVIDIA_API_KEY", "").strip(),
            nvidia_asr_server=os.getenv("STT_NVIDIA_SERVER", "grpc.nvcf.nvidia.com:443").strip(),
            nvidia_asr_function_id=os.getenv(
                "STT_NVIDIA_FUNCTION_ID",
                "d8dd4e9b-fbf5-4fb0-9dba-8cf436c8d965",
            ).strip(),
            nvidia_asr_model=os.getenv("STT_NVIDIA_MODEL", "").strip(),
            nvidia_asr_language_code=_nvidia_language_code_from_env(),
            nvidia_asr_use_ssl=_env_flag("STT_NVIDIA_USE_SSL", default=True),
            nvidia_asr_automatic_punctuation=_env_flag("STT_NVIDIA_AUTOMATIC_PUNCTUATION", default=True),
            nvidia_asr_file_streaming_chunk=int(os.getenv("STT_NVIDIA_FILE_STREAMING_CHUNK", "1600")),
            transcription_model=os.getenv("STT_MODEL", "gpt-4o-transcribe").strip(),
            language=_speech_language_from_env(),
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
            start_timeout_seconds=float(os.getenv("STT_START_TIMEOUT_SECONDS", "4")),
            silence_seconds=float(os.getenv("STT_SILENCE_SECONDS", "1.4")),
            calibration_seconds=float(os.getenv("STT_CALIBRATION_SECONDS", "0.6")),
            min_energy=float(os.getenv("STT_MIN_ENERGY", "80")),
            energy_multiplier=float(os.getenv("STT_ENERGY_MULTIPLIER", "1.6")),
        )

    def validate(self) -> None:
        if self.provider not in {"local", "faster_whisper", "openai", "nvidia", "nvidia_riva", "riva"}:
            raise ValueError("STT_PROVIDER must be local, faster_whisper, openai, nvidia, nvidia_riva, or riva.")
        if self.provider == "openai" and not self.openai_api_key:
            raise ValueError("Missing OPENAI_API_KEY. Add it to .env before using listening mode.")
        if self.provider == "openai" and not self.transcription_model:
            raise ValueError("Missing STT_MODEL.")
        if self.provider in {"nvidia", "nvidia_riva", "riva"} and not self.nvidia_api_key:
            raise ValueError("Missing NVIDIA_API_KEY. Add it to .env before using NVIDIA listening mode.")
        if self.provider in {"nvidia", "nvidia_riva", "riva"} and not self.nvidia_asr_server:
            raise ValueError("Missing STT_NVIDIA_SERVER.")
        if self.provider in {"nvidia", "nvidia_riva", "riva"} and not self.nvidia_asr_language_code:
            raise ValueError("Missing STT_NVIDIA_LANGUAGE_CODE.")
        if self.provider in {"local", "faster_whisper"} and not self.local_model:
            raise ValueError("Missing STT_LOCAL_MODEL.")
        if self.local_beam_size <= 0:
            raise ValueError("STT_LOCAL_BEAM_SIZE must be greater than 0.")
        if self.nvidia_asr_file_streaming_chunk <= 0:
            raise ValueError("STT_NVIDIA_FILE_STREAMING_CHUNK must be greater than 0.")
        if self.sample_rate <= 0:
            raise ValueError("STT_SAMPLE_RATE must be greater than 0.")
        if self.max_seconds <= 0:
            raise ValueError("STT_LISTEN_MAX_SECONDS must be greater than 0.")
        if self.min_seconds < 0:
            raise ValueError("STT_LISTEN_MIN_SECONDS must be zero or greater.")
        if self.start_timeout_seconds <= 0:
            raise ValueError("STT_START_TIMEOUT_SECONDS must be greater than 0.")
        if self.silence_seconds <= 0:
            raise ValueError("STT_SILENCE_SECONDS must be greater than 0.")
        if self.calibration_seconds < 0:
            raise ValueError("STT_CALIBRATION_SECONDS must be zero or greater.")


@dataclass(frozen=True)
class TTSConfig:
    enabled: bool
    provider: str
    voice: str
    rate: str
    volume: str
    pitch: str
    nvidia_api_key: str
    nvidia_tts_server: str
    nvidia_tts_function_id: str
    nvidia_tts_language_code: str
    nvidia_tts_use_ssl: bool
    nvidia_tts_sample_rate: int
    nvidia_tts_streaming: bool
    nvidia_tts_ssml: bool
    player: str

    @classmethod
    def from_env(cls, project_root: Path) -> "TTSConfig":
        load_dotenv(project_root / ".env")
        return cls(
            enabled=_env_flag("TTS_ENABLED", default=True),
            provider=os.getenv("TTS_PROVIDER", "nvidia").strip().lower(),
            voice=os.getenv("TTS_VOICE", "Magpie-Multilingual.EN-US.Jason").strip(),
            rate=os.getenv("TTS_RATE", "+24%").strip(),
            volume=os.getenv("TTS_VOLUME", "+80%").strip(),
            pitch=os.getenv("TTS_PITCH", "-8Hz").strip(),
            nvidia_api_key=os.getenv("NVIDIA_API_KEY", "").strip(),
            nvidia_tts_server=os.getenv("TTS_NVIDIA_SERVER", "grpc.nvcf.nvidia.com:443").strip(),
            nvidia_tts_function_id=os.getenv(
                "TTS_NVIDIA_FUNCTION_ID",
                "877104f7-e885-42b9-8de8-f6e4c6303969",
            ).strip(),
            nvidia_tts_language_code=os.getenv("TTS_NVIDIA_LANGUAGE_CODE", "en-US").strip(),
            nvidia_tts_use_ssl=_env_flag("TTS_NVIDIA_USE_SSL", default=True),
            nvidia_tts_sample_rate=int(os.getenv("TTS_NVIDIA_SAMPLE_RATE", "44100")),
            nvidia_tts_streaming=_env_flag("TTS_NVIDIA_STREAMING", default=True),
            nvidia_tts_ssml=_env_flag("TTS_NVIDIA_SSML", default=False),
            player=os.getenv("TTS_PLAYER", "auto").strip().lower(),
        )

    def validate(self) -> None:
        if self.provider not in {"nvidia", "nvidia_riva", "riva"}:
            raise ValueError("TTS_PROVIDER must be nvidia, nvidia_riva, or riva.")
        if not self.voice:
            raise ValueError("Missing TTS_VOICE.")
        if not self.nvidia_api_key:
            raise ValueError("Missing NVIDIA_API_KEY. Add it to .env before using NVIDIA voice output.")
        if not self.nvidia_tts_server:
            raise ValueError("Missing TTS_NVIDIA_SERVER.")
        if not self.nvidia_tts_function_id:
            raise ValueError("Missing TTS_NVIDIA_FUNCTION_ID.")
        if not self.nvidia_tts_language_code:
            raise ValueError("Missing TTS_NVIDIA_LANGUAGE_CODE.")
        if self.nvidia_tts_sample_rate <= 0:
            raise ValueError("TTS_NVIDIA_SAMPLE_RATE must be greater than 0.")


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
        start_timeout_chunks = max(1, int(self.config.start_timeout_seconds / 0.1))
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
                    elif index >= calibration_chunks + start_timeout_chunks:
                        break
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
        status = "speech" if speech_started else "no speech"
        print(
            f"Mic: {device_name} | {status} | peak {peak_rms:.0f} | "
            f"threshold {threshold:.0f} | captured {duration:.1f}s"
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
        if self.config.language:
            kwargs["language"] = self.config.language
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
        if self.config.language:
            fields["language"] = self.config.language
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


class NvidiaRivaSpeechToText:
    def __init__(self, config: SpeechConfig):
        config.validate()
        self.config = config
        try:
            import riva.client
        except ImportError as error:
            raise RuntimeError(
                "NVIDIA listening mode needs the Riva client. Install it with: "
                "python -m pip install nvidia-riva-client"
            ) from error

        self.riva_client = riva.client
        auth = self.riva_client.Auth(
            use_ssl=config.nvidia_asr_use_ssl,
            uri=config.nvidia_asr_server,
            metadata_args=_nvidia_metadata(config),
        )
        self.service = self.riva_client.ASRService(auth)

    def transcribe(self, audio_path: Path) -> str:
        config = self.riva_client.StreamingRecognitionConfig(
            config=self._recognition_config(),
            interim_results=False,
        )
        try:
            with self.riva_client.AudioChunkFileIterator(
                str(audio_path),
                self.config.nvidia_asr_file_streaming_chunk,
            ) as audio_chunks:
                responses = self.service.streaming_response_generator(
                    audio_chunks=audio_chunks,
                    streaming_config=config,
                )
                return _extract_nvidia_streaming_text(responses)
        except Exception as error:
            raise RuntimeError(f"NVIDIA speech request failed: {error}") from error

    def translate_audio_to_english(self, audio_path: Path) -> str:
        return self.transcribe(audio_path)

    def _recognition_config(self):
        kwargs = {
            "language_code": self.config.nvidia_asr_language_code,
            "max_alternatives": 1,
            "enable_automatic_punctuation": self.config.nvidia_asr_automatic_punctuation,
            "verbatim_transcripts": True,
        }
        if self.config.nvidia_asr_model:
            kwargs["model"] = self.config.nvidia_asr_model
        return self.riva_client.RecognitionConfig(**kwargs)


class NvidiaRivaTextToSpeech:
    def __init__(self, config: TTSConfig):
        config.validate()
        self.config = config
        try:
            import riva.client
        except ImportError as error:
            raise RuntimeError(
                "NVIDIA voice output needs the Riva client. Install it with: "
                "python -m pip install nvidia-riva-client"
            ) from error

        self.riva_client = riva.client
        auth = self.riva_client.Auth(
            use_ssl=config.nvidia_tts_use_ssl,
            uri=config.nvidia_tts_server,
            metadata_args=_nvidia_riva_metadata(config.nvidia_api_key, config.nvidia_tts_function_id),
        )
        self.service = self.riva_client.SpeechSynthesisService(auth)

    def speak(self, text: str) -> None:
        spoken_text = text_for_speech(text)
        if not spoken_text:
            return

        request_text = _nvidia_tts_text(spoken_text, self.config)
        volume = _volume_multiplier(self.config.volume)
        try:
            if self.config.nvidia_tts_streaming:
                responses = self.service.synthesize_online(
                    request_text,
                    voice_name=self.config.voice,
                    language_code=self.config.nvidia_tts_language_code,
                    encoding=self.riva_client.AudioEncoding.LINEAR_PCM,
                    sample_rate_hz=self.config.nvidia_tts_sample_rate,
                )
                play_pcm_stream(responses, self.config.nvidia_tts_sample_rate, self.config.player, volume=volume)
                return

            response = self.service.synthesize(
                request_text,
                voice_name=self.config.voice,
                language_code=self.config.nvidia_tts_language_code,
                encoding=self.riva_client.AudioEncoding.LINEAR_PCM,
                sample_rate_hz=self.config.nvidia_tts_sample_rate,
            )
            audio = bytes(getattr(response, "audio", b""))
            play_pcm_audio(audio, self.config.nvidia_tts_sample_rate, self.config.player, volume=volume)
        except Exception as error:
            raise RuntimeError(f"NVIDIA voice request failed: {error}") from error


def create_speech_to_text(config: SpeechConfig) -> SpeechToText:
    if config.provider in {"local", "faster_whisper"}:
        return FasterWhisperSpeechToText(config)
    if config.provider == "openai":
        return OpenAISpeechToText(config)
    if config.provider in {"nvidia", "nvidia_riva", "riva"}:
        return NvidiaRivaSpeechToText(config)
    config.validate()
    raise ValueError(f"Unsupported STT_PROVIDER: {config.provider}")


def create_text_to_speech(config: TTSConfig) -> TextToSpeech:
    if config.provider in {"nvidia", "nvidia_riva", "riva"}:
        return NvidiaRivaTextToSpeech(config)
    config.validate()
    raise ValueError(f"Unsupported TTS_PROVIDER: {config.provider}")


def text_for_speech(text: str, max_chars: int | None = None) -> str:
    # max_chars is kept for old call sites; NVIDIA streaming now speaks the full cleaned reply.
    _ = max_chars
    return clean_text_for_speech(text)


def clean_text_for_speech(text: str) -> str:
    cleaned = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    cleaned = re.sub(r"(?m)^\s*[-*+]\s+", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*\d+\.\s+", "", cleaned)
    cleaned = re.sub(r"[*_>#|~]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _nvidia_tts_text(text: str, config: TTSConfig) -> str:
    if not config.nvidia_tts_ssml:
        return text
    prosody: list[str] = []
    if config.rate:
        prosody.append(f'rate="{_xml_attr(config.rate)}"')
    if config.volume:
        prosody.append(f'volume="{_xml_attr(config.volume)}"')
    if config.pitch:
        prosody.append(f'pitch="{_xml_attr(config.pitch)}"')
    escaped = _xml_text(text)
    if not prosody:
        return escaped
    return f"<speak><prosody {' '.join(prosody)}>{escaped}</prosody></speak>"


def _xml_text(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _xml_attr(value: str) -> str:
    return _xml_text(value).replace('"', "&quot;")


def _volume_multiplier(value: str) -> float:
    cleaned = value.strip()
    if not cleaned:
        return 1.0
    try:
        if cleaned.endswith("%"):
            return max(0.0, 1.0 + float(cleaned.removesuffix("%")) / 100.0)
        return max(0.0, float(cleaned))
    except ValueError:
        return 1.0


def _scale_pcm16(audio: bytes, volume: float) -> bytes:
    if not audio or abs(volume - 1.0) < 0.01:
        return audio
    try:
        import numpy as np
    except ImportError:
        return audio
    samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32)
    samples *= volume
    samples = np.clip(samples, -32768, 32767).astype(np.int16)
    return samples.tobytes()


def play_pcm_stream(
    responses: Iterable[object],
    sample_rate: int,
    player: str = "auto",
    *,
    volume: float = 1.0,
) -> None:
    try:
        import sounddevice as sd
    except ImportError:
        audio = b"".join(bytes(getattr(response, "audio", b"")) for response in responses)
        play_pcm_audio(audio, sample_rate, player, volume=volume)
        return

    with sd.RawOutputStream(samplerate=sample_rate, channels=1, dtype="int16") as stream:
        for response in responses:
            audio = bytes(getattr(response, "audio", b""))
            if audio:
                stream.write(_scale_pcm16(audio, volume))


def play_pcm_audio(audio: bytes, sample_rate: int, player: str = "auto", *, volume: float = 1.0) -> None:
    if not audio:
        return
    audio = _scale_pcm16(audio, volume)
    try:
        import sounddevice as sd
    except ImportError:
        handle = tempfile.NamedTemporaryFile(prefix="voice-", suffix=".wav", delete=False)
        audio_path = Path(handle.name)
        handle.close()
        try:
            with wave.open(str(audio_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(audio)
            play_audio_file(audio_path, player)
        finally:
            audio_path.unlink(missing_ok=True)
        return

    with sd.RawOutputStream(samplerate=sample_rate, channels=1, dtype="int16") as stream:
        stream.write(audio)


def play_audio_file(audio_path: Path, player: str = "auto") -> None:
    if player not in {"auto", "powershell", "ffplay", "afplay"}:
        raise ValueError("TTS_PLAYER must be auto, powershell, ffplay, or afplay.")
    if os.name == "nt" and player in {"auto", "powershell"}:
        _play_audio_with_powershell(audio_path)
        return

    if player in {"auto", "ffplay"}:
        ffplay = shutil.which("ffplay")
        if ffplay:
            subprocess.run(
                [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", str(audio_path)],
                check=True,
            )
            return

    if player in {"auto", "afplay"}:
        afplay = shutil.which("afplay")
        if afplay:
            subprocess.run([afplay, str(audio_path)], check=True)
            return

    raise RuntimeError("No supported audio player found for TTS playback.")


def _play_audio_with_powershell(audio_path: Path) -> None:
    script = (
        "Add-Type -AssemblyName presentationCore; "
        f"$path = {_powershell_quote(str(audio_path))}; "
        "$player = New-Object System.Windows.Media.MediaPlayer; "
        "$player.Open([System.Uri]::new($path)); "
        "for ($i = 0; $i -lt 100 -and -not $player.NaturalDuration.HasTimeSpan; $i++) { "
        "Start-Sleep -Milliseconds 50 }; "
        "$player.Play(); "
        "if ($player.NaturalDuration.HasTimeSpan) { "
        "Start-Sleep -Milliseconds ([int]$player.NaturalDuration.TimeSpan.TotalMilliseconds + 250) "
        "} else { Start-Sleep -Seconds 8 }; "
        "$player.Close()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Sta", "-Command", script],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _speech_language_from_env() -> str:
    value = os.getenv("STT_LANGUAGE", "").strip() or os.getenv("STT_SPEECH_RECOGNITION_LANGUAGE", "").strip()
    return _normalize_speech_language(value)


def _nvidia_language_code_from_env() -> str:
    explicit = os.getenv("STT_NVIDIA_LANGUAGE_CODE", "").strip()
    if explicit:
        return explicit

    language = _speech_language_from_env()
    if not language:
        return "en-US"
    mapping = {
        "en": "en-US",
        "hi": "hi-IN",
        "es": "es-US",
        "fr": "fr-FR",
        "de": "de-DE",
    }
    return mapping.get(language, language)


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _nvidia_metadata(config: SpeechConfig) -> list[list[str]]:
    return _nvidia_riva_metadata(config.nvidia_api_key, config.nvidia_asr_function_id)


def _nvidia_riva_metadata(api_key: str, function_id: str) -> list[list[str]]:
    metadata = [["authorization", f"Bearer {api_key}"]]
    if function_id:
        metadata.insert(0, ["function-id", function_id])
    return metadata


def _extract_nvidia_streaming_text(responses: Iterable[object]) -> str:
    final_texts: list[str] = []
    partial_text = ""
    for response in responses:
        for result in getattr(response, "results", []):
            alternatives = getattr(result, "alternatives", [])
            if not alternatives:
                continue
            transcript = str(getattr(alternatives[0], "transcript", "")).strip()
            if not transcript:
                continue
            if getattr(result, "is_final", False):
                final_texts.append(transcript)
            else:
                partial_text = transcript
    if final_texts:
        return " ".join(final_texts).strip()
    return partial_text


def _normalize_speech_language(value: str) -> str:
    cleaned = value.strip().lower().replace("_", "-")
    if not cleaned or cleaned in {"auto", "detect", "default", "none", "false"}:
        return ""
    aliases = {
        "english": "en",
        "hindi": "hi",
        "urdu": "ur",
        "spanish": "es",
        "french": "fr",
        "german": "de",
    }
    cleaned = aliases.get(cleaned, cleaned)
    if "-" in cleaned:
        cleaned = cleaned.split("-", 1)[0]
    return cleaned


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
