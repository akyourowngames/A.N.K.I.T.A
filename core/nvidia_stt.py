from __future__ import annotations

import os
import sys
import io
import tempfile
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol, Sequence

from core.llm_service import load_dotenv


@dataclass(frozen=True)
class NvidiaSTTConfig:
    provider: str
    api_key: str
    server: str
    function_id: str
    model: str
    language_code: str
    language_codes: tuple[str, ...]
    web_language_codes: tuple[str, ...]
    web_fallback: bool
    use_ssl: bool
    automatic_punctuation: bool
    file_streaming_chunk: int
    sample_rate: int
    input_device: str
    listen_timeout_seconds: float
    phrase_time_limit_seconds: float
    adjust_for_ambient_noise_seconds: float
    energy_threshold: int
    dynamic_energy_threshold: bool
    input_gain: float
    pause_threshold: float
    non_speaking_duration: float

    @classmethod
    def from_env(cls, project_root: Path) -> "NvidiaSTTConfig":
        load_dotenv(project_root / ".env")
        language_codes = _language_codes_from_env()
        web_language_codes = _web_language_codes_from_env(language_codes)
        return cls(
            provider=os.getenv("STT_PROVIDER", "nvidia").strip().lower(),
            api_key=os.getenv("NVIDIA_API_KEY", "").strip(),
            server=os.getenv("STT_NVIDIA_SERVER", "grpc.nvcf.nvidia.com:443").strip(),
            function_id=os.getenv(
                "STT_NVIDIA_FUNCTION_ID",
                "d8dd4e9b-fbf5-4fb0-9dba-8cf436c8d965",
            ).strip(),
            model=os.getenv("STT_NVIDIA_MODEL", "").strip(),
            language_code=language_codes[0] if language_codes else "",
            language_codes=language_codes,
            web_language_codes=web_language_codes,
            web_fallback=_env_flag("STT_WEB_FALLBACK", default=True),
            use_ssl=_env_flag("STT_NVIDIA_USE_SSL", default=True),
            automatic_punctuation=_env_flag("STT_NVIDIA_AUTOMATIC_PUNCTUATION", default=True),
            file_streaming_chunk=int(os.getenv("STT_NVIDIA_FILE_STREAMING_CHUNK", "1600")),
            sample_rate=int(os.getenv("STT_SAMPLE_RATE", "16000")),
            input_device=os.getenv("STT_INPUT_DEVICE", "").strip(),
            listen_timeout_seconds=_env_float("STT_LISTEN_TIMEOUT_SECONDS", "STT_START_TIMEOUT_SECONDS", default=5),
            phrase_time_limit_seconds=_env_positive_float(
                "STT_PHRASE_TIME_LIMIT_SECONDS",
                "STT_LISTEN_MAX_SECONDS",
                default=20,
            ),
            adjust_for_ambient_noise_seconds=_env_float(
                "STT_ADJUST_FOR_AMBIENT_NOISE_SECONDS",
                "STT_CALIBRATION_SECONDS",
                default=0.6,
            ),
            energy_threshold=int(_env_float("STT_ENERGY_THRESHOLD", "STT_MIN_ENERGY", default=120)),
            dynamic_energy_threshold=_env_flag("STT_DYNAMIC_ENERGY_THRESHOLD", default=True),
            input_gain=_env_positive_float("STT_INPUT_GAIN", "STT_VOLUME_GAIN", default=1.0),
            pause_threshold=_env_float("STT_PAUSE_THRESHOLD", "STT_SILENCE_SECONDS", default=0.8),
            non_speaking_duration=float(os.getenv("STT_NON_SPEAKING_DURATION", "0.5")),
        )

    def validate(self) -> None:
        if self.provider not in {"nvidia", "nvidia_riva", "riva", "web", "speech_recognition"}:
            raise ValueError("STT_PROVIDER must be nvidia, nvidia_riva, riva, web, or speech_recognition.")
        if self.provider in {"nvidia", "nvidia_riva", "riva"} and not self.api_key:
            raise ValueError("Missing NVIDIA_API_KEY. Add it to .env before using listening mode.")
        if self.provider in {"nvidia", "nvidia_riva", "riva"} and not self.server:
            raise ValueError("Missing STT_NVIDIA_SERVER.")
        if not self.language_code:
            raise ValueError("Missing STT_NVIDIA_LANGUAGE_CODE.")
        if not self.language_codes:
            raise ValueError("Missing STT_NVIDIA_LANGUAGE_CODES.")
        if self.provider in {"web", "speech_recognition"} and not self.web_language_codes:
            raise ValueError("Missing STT_WEB_LANGUAGE_CODES.")
        if self.file_streaming_chunk <= 0:
            raise ValueError("STT_NVIDIA_FILE_STREAMING_CHUNK must be greater than 0.")
        if self.sample_rate <= 0:
            raise ValueError("STT_SAMPLE_RATE must be greater than 0.")
        if self.listen_timeout_seconds <= 0:
            raise ValueError("STT_LISTEN_TIMEOUT_SECONDS must be greater than 0.")
        if self.phrase_time_limit_seconds <= 0:
            raise ValueError("STT_PHRASE_TIME_LIMIT_SECONDS must be greater than 0.")
        if self.adjust_for_ambient_noise_seconds < 0:
            raise ValueError("STT_ADJUST_FOR_AMBIENT_NOISE_SECONDS must be zero or greater.")
        if self.energy_threshold <= 0:
            raise ValueError("STT_ENERGY_THRESHOLD must be greater than 0.")
        if self.input_gain <= 0:
            raise ValueError("STT_INPUT_GAIN must be greater than 0.")
        if self.pause_threshold <= 0:
            raise ValueError("STT_PAUSE_THRESHOLD must be greater than 0.")
        if self.non_speaking_duration < 0:
            raise ValueError("STT_NON_SPEAKING_DURATION must be zero or greater.")


class SpeechToText(Protocol):
    def transcribe(self, audio_path: Path) -> str:
        ...

    def transcribe_file(self, audio_path: Path) -> str:
        ...


class SpeechRecognitionMicrophone:
    def __init__(self, config: NvidiaSTTConfig):
        self.config = config
        try:
            import speech_recognition as sr
        except ImportError as error:
            raise RuntimeError(
                "CLI listening needs SpeechRecognition and PyAudio. Install them with: "
                "python -m pip install SpeechRecognition PyAudio"
            ) from error

        self.sr = sr
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = config.energy_threshold
        self.recognizer.dynamic_energy_threshold = config.dynamic_energy_threshold
        self.recognizer.pause_threshold = config.pause_threshold
        self.recognizer.non_speaking_duration = config.non_speaking_duration

    def listen_to_wav(self) -> Path | None:
        devices = _microphone_devices(self.sr)
        device_index = _microphone_device_index(self.config.input_device, devices)
        microphone = self.sr.Microphone(device_index=device_index, sample_rate=self.config.sample_rate)

        with microphone as source:
            if self.config.adjust_for_ambient_noise_seconds > 0:
                self.recognizer.adjust_for_ambient_noise(
                    source,
                    duration=self.config.adjust_for_ambient_noise_seconds,
                )
            try:
                audio = self.recognizer.listen(
                    source,
                    timeout=self.config.listen_timeout_seconds,
                    phrase_time_limit=self.config.phrase_time_limit_seconds,
                )
            except self.sr.WaitTimeoutError:
                return None

        handle = tempfile.NamedTemporaryFile(prefix="speech-", suffix=".wav", delete=False)
        path = Path(handle.name)
        handle.close()
        path.write_bytes(_wav_bytes(audio, self.config.sample_rate, self.config.input_gain))
        return path


class NvidiaRivaSpeechToText:
    def __init__(self, config: NvidiaSTTConfig):
        config.validate()
        self.config = config
        self._web_fallback: SpeechRecognitionWebSpeechToText | None = None
        self._unavailable_language_codes: set[str] = set()
        try:
            import riva.client
        except ImportError as error:
            raise RuntimeError(
                "NVIDIA listening mode needs the Riva client. Install it with: "
                "python -m pip install nvidia-riva-client"
            ) from error

        self.riva_client = riva.client
        auth = self.riva_client.Auth(
            use_ssl=config.use_ssl,
            uri=config.server,
            metadata_args=_nvidia_metadata(config),
        )
        self.service = self.riva_client.ASRService(auth)

    def transcribe(self, audio_path: Path) -> str:
        return self.transcribe_file(audio_path)

    def transcribe_file(self, audio_path: Path) -> str:
        language_codes = self.config.language_codes or (self.config.language_code,)
        if len(language_codes) == 1:
            try:
                return self._transcribe_file_once(audio_path, language_codes[0])
            except Exception as error:
                if not self.config.web_fallback:
                    raise RuntimeError(f"NVIDIA speech request failed: {error}") from error
                fallback_text = self._transcribe_with_web_fallback(audio_path)
                if fallback_text:
                    return fallback_text
                raise RuntimeError(f"NVIDIA speech request failed: {error}") from error

        errors: list[str] = []
        for language_code in language_codes:
            if language_code in self._unavailable_language_codes:
                continue
            try:
                transcript = self._transcribe_file_once(audio_path, language_code)
            except Exception as error:
                if _is_unavailable_language_error(error):
                    self._unavailable_language_codes.add(language_code)
                errors.append(f"{language_code}: {error}")
                continue
            if transcript:
                return transcript
        if self.config.web_fallback:
            fallback_text = self._transcribe_with_web_fallback(audio_path)
            if fallback_text:
                return fallback_text
        if errors:
            details = "; ".join(errors)
            raise RuntimeError(f"NVIDIA speech request failed for configured languages: {details}")
        return ""

    def _transcribe_with_web_fallback(self, audio_path: Path) -> str:
        if self._web_fallback is None:
            self._web_fallback = SpeechRecognitionWebSpeechToText(self.config)
        return self._web_fallback.transcribe_file(audio_path)

    def _transcribe_file_once(self, audio_path: Path, language_code: str) -> str:
        config = self.riva_client.StreamingRecognitionConfig(
            config=self._recognition_config(language_code),
            interim_results=False,
        )
        with self.riva_client.AudioChunkFileIterator(
            str(audio_path),
            self.config.file_streaming_chunk,
        ) as audio_chunks:
            responses = self.service.streaming_response_generator(
                audio_chunks=audio_chunks,
                streaming_config=config,
            )
            return _extract_nvidia_streaming_text(responses)

    def translate_audio_to_english(self, audio_path: Path) -> str:
        return self.transcribe_file(audio_path)

    def _recognition_config(self, language_code: str):
        kwargs = {
            "language_code": language_code,
            "max_alternatives": 1,
            "enable_automatic_punctuation": self.config.automatic_punctuation,
            "verbatim_transcripts": True,
        }
        if self.config.model:
            kwargs["model"] = self.config.model

        audio_encoding = getattr(getattr(self.riva_client, "AudioEncoding", None), "LINEAR_PCM", None)
        if audio_encoding is not None:
            kwargs["encoding"] = audio_encoding
        kwargs["sample_rate_hertz"] = self.config.sample_rate
        kwargs["audio_channel_count"] = 1

        try:
            return self.riva_client.RecognitionConfig(**kwargs)
        except TypeError:
            kwargs.pop("encoding", None)
            kwargs.pop("sample_rate_hertz", None)
            kwargs.pop("audio_channel_count", None)
            return self.riva_client.RecognitionConfig(**kwargs)


class SpeechRecognitionWebSpeechToText:
    def __init__(self, config: NvidiaSTTConfig):
        config.validate()
        self.config = config
        try:
            import speech_recognition as sr
        except ImportError as error:
            raise RuntimeError(
                "Web listening needs SpeechRecognition. Install it with: "
                "python -m pip install SpeechRecognition"
            ) from error

        self.sr = sr
        self.recognizer = sr.Recognizer()

    def transcribe(self, audio_path: Path) -> str:
        return self.transcribe_file(audio_path)

    def transcribe_file(self, audio_path: Path) -> str:
        with self.sr.AudioFile(str(audio_path)) as source:
            audio = self.recognizer.record(source)

        language_codes = self.config.web_language_codes or self.config.language_codes
        errors: list[str] = []
        for language_code in language_codes:
            try:
                transcript = str(self.recognizer.recognize_google(audio, language=language_code)).strip()
            except self.sr.UnknownValueError:
                continue
            except self.sr.RequestError as error:
                errors.append(f"{language_code}: {error}")
                continue
            if transcript:
                return transcript
        if errors:
            details = "; ".join(errors)
            raise RuntimeError(f"Web speech request failed for configured languages: {details}")
        return ""


def create_speech_to_text(config: NvidiaSTTConfig) -> SpeechToText:
    if config.provider in {"web", "speech_recognition"}:
        return SpeechRecognitionWebSpeechToText(config)
    return NvidiaRivaSpeechToText(config)


def list_input_devices() -> list[str]:
    try:
        import speech_recognition as sr
    except ImportError as error:
        raise RuntimeError(
            "CLI listening needs SpeechRecognition and PyAudio. Install them with: "
            "python -m pip install SpeechRecognition PyAudio"
        ) from error

    return [f"{index}: {name}" for index, name in _microphone_devices(sr)]


def _microphone_devices(sr_module) -> list[tuple[int, str]]:
    pyaudio = sr_module.Microphone.get_pyaudio()
    audio = pyaudio.PyAudio()
    try:
        devices: list[tuple[int, str]] = []
        for index in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(index)
            if int(info.get("maxInputChannels", 0)) <= 0:
                continue
            devices.append((index, str(info.get("name", "Unknown input"))))
        return devices
    finally:
        audio.terminate()


def _microphone_device_index(value: str, names: Sequence[str | tuple[int, str]] | None = None) -> int | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        pass

    microphone_names = _microphone_choices(names or [])
    lowered = cleaned.lower()
    for index, name in microphone_names:
        if lowered in name.lower():
            return index
    available = ", ".join(f"{index}: {name}" for index, name in microphone_names) or "none"
    raise ValueError(f"STT_INPUT_DEVICE did not match a microphone. Available microphones: {available}")


def _microphone_choices(names: Sequence[str | tuple[int, str]]) -> list[tuple[int, str]]:
    choices: list[tuple[int, str]] = []
    for fallback_index, item in enumerate(names):
        if isinstance(item, tuple):
            index, name = item
            choices.append((int(index), str(name)))
        else:
            choices.append((fallback_index, str(item)))
    return choices


def _wav_bytes(audio, sample_rate: int, input_gain: float) -> bytes:
    if input_gain <= 1.01:
        return audio.get_wav_data(convert_rate=sample_rate, convert_width=2)

    pcm = audio.get_raw_data(convert_rate=sample_rate, convert_width=2)
    boosted = _gain_pcm16(pcm, input_gain)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(boosted)
    return buffer.getvalue()


def _gain_pcm16(pcm: bytes, gain: float) -> bytes:
    if not pcm or abs(gain - 1.0) < 0.01:
        return pcm
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    for index, sample in enumerate(samples):
        value = int(round(sample * gain))
        samples[index] = min(32767, max(-32768, value))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def _language_codes_from_env() -> tuple[str, ...]:
    explicit = os.getenv("STT_NVIDIA_LANGUAGE_CODES", "").strip()
    if explicit:
        return _language_codes_from_text(explicit) or (_language_code_from_env(),)
    return (_language_code_from_env(),)


def _web_language_codes_from_env(fallback_codes: tuple[str, ...]) -> tuple[str, ...]:
    explicit = os.getenv("STT_WEB_LANGUAGE_CODES", "").strip()
    if explicit:
        return _language_codes_from_text(explicit)
    return fallback_codes


def _language_codes_from_text(text: str) -> tuple[str, ...]:
    codes: list[str] = []
    for raw_code in text.replace(";", ",").split(","):
        code = _normalize_language_code(raw_code)
        if code and code not in codes:
            codes.append(code)
    return tuple(codes)


def _language_code_from_env() -> str:
    explicit = os.getenv("STT_NVIDIA_LANGUAGE_CODE", "").strip()
    if explicit:
        return _normalize_language_code(explicit)

    language = os.getenv("STT_LANGUAGE", "").strip()
    if not language:
        return "en-US"
    return _normalize_language_code(language)


def _normalize_language_code(value: str) -> str:
    cleaned = value.strip().replace("_", "-")
    mapping = {
        "en": "en-US",
        "hi": "hi-IN",
        "es": "es-US",
        "fr": "fr-FR",
        "de": "de-DE",
    }
    return mapping.get(cleaned.lower(), cleaned)


def _is_unavailable_language_error(error: Exception) -> bool:
    text = str(error).lower()
    return "unavailable model requested" in text or "invalid_argument" in text


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _env_float(name: str, legacy_name: str, *, default: float) -> float:
    for key in (name, legacy_name):
        value = os.getenv(key, "").strip()
        if not value:
            continue
        try:
            return float(value)
        except ValueError:
            continue
    return default


def _env_positive_float(name: str, legacy_name: str, *, default: float) -> float:
    value = _env_float(name, legacy_name, default=default)
    return value if value > 0 else default


def _nvidia_metadata(config: NvidiaSTTConfig) -> list[list[str]]:
    metadata = [["authorization", f"Bearer {config.api_key}"]]
    if config.function_id:
        metadata.insert(0, ["function-id", config.function_id])
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


def wav_duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as wav_file:
        frames = wav_file.getnframes()
        rate = wav_file.getframerate()
    return frames / max(1, rate)
