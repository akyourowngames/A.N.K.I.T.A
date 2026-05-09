from __future__ import annotations

import html
import importlib.util
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, TextIO

from jarvis_nim import env_bool, env_float, env_int, env_value


class VoiceError(Exception):
    pass


@dataclass(frozen=True)
class VoiceConfig:
    api_key: str
    space_trigger: bool
    stt_enabled: bool
    stt_provider: str
    stt_server: str
    stt_function_id: str
    stt_language_code: str
    stt_model: str
    stt_use_ssl: bool
    stt_streaming: bool
    stt_streaming_chunk_bytes: int
    stt_automatic_punctuation: bool
    stt_sample_rate: int
    stt_input_device: str
    stt_start_timeout_seconds: float
    stt_listen_max_seconds: float
    stt_listen_min_seconds: float
    stt_silence_seconds: float
    stt_energy_threshold: float
    stt_input_gain: float
    tts_enabled: bool
    tts_provider: str
    tts_server: str
    tts_function_id: str
    tts_language_code: str
    tts_voice: str
    tts_use_ssl: bool
    tts_sample_rate: int
    tts_streaming: bool
    tts_ssml: bool
    tts_rate: str
    tts_pitch: str
    tts_volume: str
    tts_voice_effect: str
    tts_heavy_pitch_factor: float
    tts_heavy_darkness: float
    tts_playback_speed: float
    tts_speak_oneshot: bool

    @classmethod
    def from_env(cls) -> "VoiceConfig":
        voice_enabled = env_bool("VOICE_ENABLED", True)
        return cls(
            api_key=env_value("NVIDIA_API_KEY"),
            space_trigger=env_bool("VOICE_SPACE_TRIGGER", True),
            stt_enabled=voice_enabled and env_bool("STT_ENABLED", True),
            stt_provider=env_value("STT_PROVIDER", "nvidia").lower(),
            stt_server=env_value("STT_NVIDIA_SERVER", "grpc.nvcf.nvidia.com:443"),
            stt_function_id=env_value("STT_NVIDIA_FUNCTION_ID"),
            stt_language_code=env_value("STT_NVIDIA_LANGUAGE_CODE", env_value("STT_LANGUAGE", "en-US")),
            stt_model=env_value("STT_NVIDIA_MODEL"),
            stt_use_ssl=env_bool("STT_NVIDIA_USE_SSL", True),
            stt_streaming=env_bool("STT_NVIDIA_STREAMING", True),
            stt_streaming_chunk_bytes=env_int(
                "STT_NVIDIA_STREAMING_CHUNK_BYTES",
                env_int("STT_NVIDIA_FILE_STREAMING_CHUNK", 3200),
            ),
            stt_automatic_punctuation=env_bool("STT_NVIDIA_AUTOMATIC_PUNCTUATION", True),
            stt_sample_rate=env_int("STT_SAMPLE_RATE", 16000),
            stt_input_device=env_value("STT_INPUT_DEVICE"),
            stt_start_timeout_seconds=env_float("STT_START_TIMEOUT_SECONDS", env_float("STT_LISTEN_TIMEOUT_SECONDS", 3.0)),
            stt_listen_max_seconds=env_float("STT_LISTEN_MAX_SECONDS", env_float("STT_PHRASE_TIME_LIMIT_SECONDS", 6.0)),
            stt_listen_min_seconds=env_float("STT_LISTEN_MIN_SECONDS", 0.2),
            stt_silence_seconds=env_float("STT_SILENCE_SECONDS", env_float("STT_PAUSE_THRESHOLD", 0.35)),
            stt_energy_threshold=env_float("STT_ENERGY_THRESHOLD", 35.0),
            stt_input_gain=env_float("STT_INPUT_GAIN", 1.0),
            tts_enabled=voice_enabled and env_bool("TTS_ENABLED", False),
            tts_provider=env_value("TTS_PROVIDER", "nvidia").lower(),
            tts_server=env_value("TTS_NVIDIA_SERVER", "grpc.nvcf.nvidia.com:443"),
            tts_function_id=env_value("TTS_NVIDIA_FUNCTION_ID"),
            tts_language_code=env_value("TTS_NVIDIA_LANGUAGE_CODE", "en-US"),
            tts_voice=env_value("TTS_VOICE", "Magpie-Multilingual.EN-US.Ray.Neutral"),
            tts_use_ssl=env_bool("TTS_NVIDIA_USE_SSL", True),
            tts_sample_rate=env_int("TTS_NVIDIA_SAMPLE_RATE", 44100),
            tts_streaming=env_bool("TTS_NVIDIA_STREAMING", True),
            tts_ssml=env_bool("TTS_NVIDIA_SSML", True),
            tts_rate=env_value("TTS_RATE", "+18%"),
            tts_pitch=env_value("TTS_PITCH", "-6Hz"),
            tts_volume=env_value("TTS_VOLUME", "+80%"),
            tts_voice_effect=env_value("TTS_VOICE_EFFECT", "heavy").lower(),
            tts_heavy_pitch_factor=env_float("TTS_HEAVY_PITCH_FACTOR", 1.04),
            tts_heavy_darkness=env_float("TTS_HEAVY_DARKNESS", 0.55),
            tts_playback_speed=env_float("TTS_PLAYBACK_SPEED", 1.08),
            tts_speak_oneshot=env_bool("TTS_SPEAK_ONESHOT", False),
        )


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def voice_status_lines(config: VoiceConfig) -> list[str]:
    lines = [
        f"Voice space trigger -> {'on' if config.space_trigger else 'off'}",
        f"STT -> {'on' if config.stt_enabled else 'off'} ({config.stt_provider})",
        f"TTS -> {'on' if config.tts_enabled else 'off'} ({config.tts_provider})",
        f"NVIDIA_API_KEY -> {'set' if config.api_key else 'missing'}",
        f"STT server -> {config.stt_server}",
        f"STT function -> {'set' if config.stt_function_id else 'missing'}",
        f"STT streaming -> {'on' if config.stt_streaming else 'off'}",
        f"STT input device -> {config.stt_input_device or 'system default'}",
        f"TTS server -> {config.tts_server}",
        f"TTS function -> {'set' if config.tts_function_id else 'missing'}",
        f"TTS voice -> {config.tts_voice or 'server default'}",
        f"TTS style -> rate {config.tts_rate}, pitch {config.tts_pitch}, speed {config.tts_playback_speed}, SSML {'on' if config.tts_ssml else 'off'}",
        f"python package sounddevice -> {'ok' if has_module('sounddevice') else 'missing'}",
        f"python package numpy -> {'ok' if has_module('numpy') else 'missing'}",
        f"python package riva.client -> {'ok' if has_module('riva.client') else 'missing'}",
    ]
    return lines


def voice_status_text(config: VoiceConfig) -> str:
    return "\n".join(voice_status_lines(config))


def ensure_nvidia_voice(config: VoiceConfig, purpose: str) -> None:
    if purpose == "stt":
        if not config.stt_enabled:
            raise VoiceError("STT is disabled.")
        if config.stt_provider != "nvidia":
            raise VoiceError(f"Unsupported STT provider: {config.stt_provider}")
        if not config.stt_function_id:
            raise VoiceError("Missing STT_NVIDIA_FUNCTION_ID.")
    if purpose == "tts":
        if not config.tts_enabled:
            raise VoiceError("TTS is disabled.")
        if config.tts_provider != "nvidia":
            raise VoiceError(f"Unsupported TTS provider: {config.tts_provider}")
        if not config.tts_function_id:
            raise VoiceError("Missing TTS_NVIDIA_FUNCTION_ID.")
    if not config.api_key:
        raise VoiceError("Missing NVIDIA_API_KEY.")
    if not has_module("riva.client"):
        raise VoiceError("Missing python package: riva.client")


def nvidia_auth(config: VoiceConfig, purpose: str):
    import riva.client

    if purpose == "stt":
        server = config.stt_server
        use_ssl = config.stt_use_ssl
        function_id = config.stt_function_id
    else:
        server = config.tts_server
        use_ssl = config.tts_use_ssl
        function_id = config.tts_function_id

    metadata = [["authorization", f"Bearer {config.api_key}"]]
    if function_id:
        metadata.append(["function-id", function_id])
    return riva.client.Auth(use_ssl=use_ssl, uri=server, metadata_args=metadata)


def normalized_energy_threshold(value: float) -> float:
    if value <= 0:
        return 0.0
    if value > 1:
        return value / 32768.0
    return value


def list_microphones() -> list[dict[str, object]]:
    if not has_module("sounddevice"):
        raise VoiceError("Missing python package: sounddevice")
    import sounddevice as sd

    devices = sd.query_devices()
    microphones = []
    for index, device in enumerate(devices):
        max_input_channels = int(device.get("max_input_channels", 0))
        if max_input_channels <= 0:
            continue
        microphones.append(
            {
                "index": index,
                "name": str(device.get("name", "")),
                "channels": max_input_channels,
                "default_samplerate": int(device.get("default_samplerate", 0)),
            }
        )
    return microphones


def microphone_report() -> str:
    microphones = list_microphones()
    if not microphones:
        return "No input microphones found."
    lines = ["Input microphones:"]
    for microphone in microphones:
        lines.append(
            f"{microphone['index']}: {microphone['name']} "
            f"({microphone['channels']} ch, {microphone['default_samplerate']} Hz)"
        )
    return "\n".join(lines)


def select_input_device(config: VoiceConfig) -> int | None:
    requested = config.stt_input_device.strip()
    if not requested:
        return None
    if requested.isdecimal():
        return int(requested)

    wanted = requested.casefold()
    for microphone in list_microphones():
        name = str(microphone["name"]).casefold()
        if wanted in name:
            return int(microphone["index"])
    raise VoiceError(f"Input device not found: {requested}")


def record_microphone_audio(config: VoiceConfig) -> bytes:
    if not has_module("sounddevice"):
        raise VoiceError("Missing python package: sounddevice")
    if not has_module("numpy"):
        raise VoiceError("Missing python package: numpy")

    import numpy as np
    import sounddevice as sd

    sample_rate = max(8000, config.stt_sample_rate)
    block_size = max(400, int(sample_rate * 0.05))
    start_deadline = time.monotonic() + max(0.1, config.stt_start_timeout_seconds)
    max_deadline = time.monotonic() + max(0.2, config.stt_listen_max_seconds)
    silence_seconds = max(0.05, config.stt_silence_seconds)
    min_seconds = max(0.0, config.stt_listen_min_seconds)
    threshold = normalized_energy_threshold(config.stt_energy_threshold)
    chunks: list[object] = []
    speech_started = False
    speech_started_at = 0.0
    last_voice_at = 0.0
    input_device = select_input_device(config)

    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        blocksize=block_size,
        device=input_device,
    ) as stream:
        while time.monotonic() < max_deadline:
            block, _overflow = stream.read(block_size)
            mono = block.reshape(-1)
            if config.stt_input_gain != 1.0:
                mono = np.clip(mono * config.stt_input_gain, -1.0, 1.0)
            energy = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
            now = time.monotonic()
            if energy >= threshold:
                if not speech_started:
                    speech_started = True
                    speech_started_at = now
                last_voice_at = now
            if speech_started:
                chunks.append(mono.copy())
                long_enough = now - speech_started_at >= min_seconds
                quiet_enough = now - last_voice_at >= silence_seconds
                if long_enough and quiet_enough:
                    break
            elif now >= start_deadline:
                break

    if not chunks:
        return b""
    audio = np.concatenate(chunks)
    audio = np.clip(audio, -1.0, 1.0)
    return (audio * 32767).astype(np.int16).tobytes()


def transcript_from_asr_response(response: object) -> str:
    parts: list[str] = []
    for result in getattr(response, "results", []):
        alternatives = getattr(result, "alternatives", [])
        if not alternatives:
            continue
        transcript = getattr(alternatives[0], "transcript", "").strip()
        if transcript:
            parts.append(transcript)
    return " ".join(parts).strip()


def transcribe_nvidia_audio(config: VoiceConfig, audio_bytes: bytes) -> str:
    return transcribe_nvidia_audio_at_rate(config, audio_bytes, config.stt_sample_rate)


def transcribe_nvidia_audio_at_rate(config: VoiceConfig, audio_bytes: bytes, sample_rate: int) -> str:
    ensure_nvidia_voice(config, "stt")
    if not audio_bytes:
        return ""

    import riva.client

    auth = nvidia_auth(config, "stt")
    service = riva.client.ASRService(auth)
    recognition_config = riva.client.RecognitionConfig(
        encoding=riva.client.AudioEncoding.LINEAR_PCM,
        sample_rate_hertz=sample_rate,
        language_code=config.stt_language_code,
        max_alternatives=1,
        enable_automatic_punctuation=config.stt_automatic_punctuation,
    )
    if config.stt_model:
        recognition_config.model = config.stt_model
    try:
        if config.stt_streaming:
            return transcribe_nvidia_streaming(service, recognition_config, audio_bytes, config.stt_streaming_chunk_bytes)
        response = service.offline_recognize(audio_bytes, recognition_config)
        return transcript_from_asr_response(response)
    except Exception as error:
        if config.stt_streaming:
            raise VoiceError(f"NVIDIA STT failed: {error}") from error
        try:
            return transcribe_nvidia_streaming(service, recognition_config, audio_bytes, config.stt_streaming_chunk_bytes)
        except Exception as stream_error:
            raise VoiceError(f"NVIDIA STT failed: {stream_error}") from stream_error


def transcribe_nvidia_streaming(
    service: object,
    recognition_config: object,
    audio_bytes: bytes,
    chunk_bytes: int,
) -> str:
    import riva.client

    streaming_config = riva.client.StreamingRecognitionConfig(config=recognition_config, interim_results=False)
    chunks = audio_chunks(audio_bytes, max(400, chunk_bytes))
    parts: list[str] = []
    for response in service.streaming_response_generator(chunks, streaming_config):
        text = transcript_from_asr_response(response)
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def audio_chunks(audio_bytes: bytes, chunk_bytes: int):
    for index in range(0, len(audio_bytes), chunk_bytes):
        yield audio_bytes[index : index + chunk_bytes]


def listen_once(config: VoiceConfig) -> str:
    audio_bytes = record_microphone_audio(config)
    return transcribe_nvidia_audio(config, audio_bytes)


def tts_input_text(config: VoiceConfig, text: str) -> str:
    clean_text = text.strip()
    if not clean_text or not config.tts_ssml:
        return clean_text
    volume = ssml_volume_value(config.tts_volume)
    return (
        "<speak><prosody "
        f'rate="{html.escape(ssml_rate_value(config.tts_rate), quote=True)}" '
        f'pitch="{html.escape(config.tts_pitch, quote=True)}" '
        f'volume="{html.escape(volume, quote=True)}">'
        f"{html.escape(clean_text)}"
        "</prosody></speak>"
    )


def ssml_rate_value(value: str) -> str:
    clean = value.strip()
    if not clean.endswith("%") or not clean:
        return clean
    number_text = clean[:-1].strip()
    if not number_text:
        return clean
    try:
        number = float(number_text)
    except ValueError:
        return clean
    if number_text[0] in {"+", "-"}:
        number = 100 + number
    number = min(250.0, max(25.0, number))
    if number.is_integer():
        return f"{int(number)}%"
    return f"{number}%"


def ssml_volume_value(value: str) -> str:
    clean = value.strip()
    if not clean:
        return "+0dB"
    if clean.endswith("dB"):
        return clean
    if not clean.endswith("%"):
        return clean
    number_text = clean[:-1].strip()
    if not number_text:
        return "+0dB"
    try:
        number = float(number_text)
    except ValueError:
        return "+0dB"
    if number_text[0] not in {"+", "-"}:
        number = number - 100
    db_value = min(8.0, max(-20.0, number * 0.06))
    sign = "+" if db_value >= 0 else ""
    if float(db_value).is_integer():
        return f"{sign}{int(db_value)}dB"
    return f"{sign}{round(db_value, 2)}dB"


def synthesize_nvidia_tts(config: VoiceConfig, text: str, streaming: bool | None = None) -> bytes:
    ensure_nvidia_voice(config, "tts")
    clean_text = tts_input_text(config, text)
    if not clean_text:
        return b""

    import riva.client

    use_streaming = config.tts_streaming if streaming is None else streaming
    auth = nvidia_auth(config, "tts")
    service = riva.client.SpeechSynthesisService(auth)
    voice_name = config.tts_voice or None

    try:
        if use_streaming:
            chunks = []
            for response in service.synthesize_online(
                clean_text,
                voice_name=voice_name,
                language_code=config.tts_language_code,
                encoding=riva.client.AudioEncoding.LINEAR_PCM,
                sample_rate_hz=config.tts_sample_rate,
            ):
                audio = getattr(response, "audio", b"")
                if audio:
                    chunks.append(audio)
            return b"".join(chunks)

        response = service.synthesize(
            clean_text,
            voice_name=voice_name,
            language_code=config.tts_language_code,
            encoding=riva.client.AudioEncoding.LINEAR_PCM,
            sample_rate_hz=config.tts_sample_rate,
        )
        return getattr(response, "audio", b"")
    except Exception as error:
        raise VoiceError(f"NVIDIA TTS failed: {error}") from error


def output_sample_rate(config: VoiceConfig) -> int:
    speed = config.tts_playback_speed if config.tts_playback_speed > 0 else 1.0
    rate = config.tts_sample_rate * speed
    if config.tts_voice_effect == "heavy" and config.tts_heavy_pitch_factor > 0:
        rate = rate / config.tts_heavy_pitch_factor
    return max(8000, int(rate))


def darken_pcm(config: VoiceConfig, samples):
    if config.tts_voice_effect != "heavy" or config.tts_heavy_darkness <= 0:
        return samples

    import numpy as np

    darkness = min(0.95, max(0.0, config.tts_heavy_darkness))
    blend = max(0.05, 1.0 - darkness)
    source = samples.astype(np.float32)
    shaped = np.empty_like(source)
    previous = 0.0
    for index, sample in enumerate(source):
        previous = previous + blend * (float(sample) - previous)
        shaped[index] = previous
    return np.clip(shaped, -32768, 32767).astype(np.int16)


def play_pcm_audio(config: VoiceConfig, audio_bytes: bytes) -> None:
    if not audio_bytes:
        return
    if not has_module("sounddevice"):
        raise VoiceError("Missing python package: sounddevice")
    if not has_module("numpy"):
        raise VoiceError("Missing python package: numpy")

    import numpy as np
    import sounddevice as sd

    samples = np.frombuffer(audio_bytes, dtype=np.int16)
    if samples.size == 0:
        return
    samples = darken_pcm(config, samples)
    sd.play(samples, samplerate=output_sample_rate(config), blocking=True)


def speak_text_blocking(config: VoiceConfig, text: str) -> None:
    if not config.tts_enabled:
        return
    clean_text = text.strip()
    if not clean_text:
        return
    if config.tts_streaming:
        try:
            stream_nvidia_tts_to_output(config, clean_text)
            return
        except Exception:
            audio = synthesize_nvidia_tts(config, clean_text, streaming=False)
            play_pcm_audio(config, audio)
            return
    audio = synthesize_nvidia_tts(config, clean_text, streaming=False)
    play_pcm_audio(config, audio)


def stream_nvidia_tts_to_output(config: VoiceConfig, text: str) -> None:
    ensure_nvidia_voice(config, "tts")
    if not has_module("sounddevice"):
        raise VoiceError("Missing python package: sounddevice")
    if not has_module("numpy"):
        raise VoiceError("Missing python package: numpy")

    import numpy as np
    import riva.client
    import sounddevice as sd

    auth = nvidia_auth(config, "tts")
    service = riva.client.SpeechSynthesisService(auth)
    voice_name = config.tts_voice or None
    output_rate = output_sample_rate(config)
    try:
        with sd.OutputStream(samplerate=output_rate, channels=1, dtype="int16") as output_stream:
            for response in service.synthesize_online(
                tts_input_text(config, text),
                voice_name=voice_name,
                language_code=config.tts_language_code,
                encoding=riva.client.AudioEncoding.LINEAR_PCM,
                sample_rate_hz=config.tts_sample_rate,
            ):
                audio = getattr(response, "audio", b"")
                if not audio:
                    continue
                samples = np.frombuffer(audio, dtype=np.int16)
                if samples.size == 0:
                    continue
                output_stream.write(darken_pcm(config, samples).reshape(-1, 1))
    except Exception as error:
        raise VoiceError(f"NVIDIA TTS failed: {error}") from error


class VoiceSpeaker:
    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._failed = False
        if config.tts_enabled:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def say(self, text: str) -> None:
        if not self._thread or not text.strip():
            return
        self._queue.put(text)

    def close(self) -> None:
        if not self._thread:
            return
        self._queue.put(None)

    def _run(self) -> None:
        while True:
            text = self._queue.get()
            if text is None:
                return
            try:
                speak_text_blocking(self.config, text)
            except Exception as error:
                if not self._failed:
                    self._failed = True
                    print(f"Voice output failed: {error}", file=sys.stderr)


def read_text_or_voice(
    prompt: str,
    config: VoiceConfig,
    listener: Callable[[], str] | None = None,
    char_reader: Callable[[], str] | None = None,
    writer: TextIO | None = None,
) -> str:
    if writer is None:
        writer = sys.stdout
    if not config.space_trigger or not config.stt_enabled:
        return input(prompt).strip()

    if char_reader is None:
        if os.name != "nt" or not sys.stdin.isatty():
            return input(prompt).strip()
        import msvcrt

        char_reader = msvcrt.getwch

    if listener is None:
        listener = lambda: listen_once(config)

    writer.write(prompt)
    writer.flush()
    buffer: list[str] = []
    while True:
        char = char_reader()
        if char in {"\x00", "\xe0"}:
            char_reader()
            continue
        if char in {"\r", "\n"}:
            writer.write("\n")
            writer.flush()
            return "".join(buffer).strip()
        if char == "\x03":
            raise KeyboardInterrupt
        if char == "\x1a":
            raise EOFError
        if char in {"\b", "\x7f"}:
            if buffer:
                buffer.pop()
                writer.write("\b \b")
                writer.flush()
            continue
        if char == " " and not buffer:
            writer.write("[listening...]\n")
            writer.flush()
            transcript = listener().strip()
            if transcript:
                writer.write(f"{prompt}{transcript}\n")
            else:
                writer.write(f"{prompt}\n")
            writer.flush()
            return transcript
        if char:
            buffer.append(char)
            writer.write(char)
            writer.flush()
