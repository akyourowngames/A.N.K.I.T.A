from __future__ import annotations

import html
import importlib.util
import json
import os
import queue
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TextIO

from jarvis_nim import env_bool, env_float, env_int, env_value


class VoiceError(Exception):
    pass


@dataclass(frozen=True)
class VoiceConfig:
    api_key: str
    profile_name: str
    profile_file: Path
    space_trigger: bool
    listen_wait_timeout_seconds: float
    listen_after_tts_delay_seconds: float
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
    stt_min_speech_rms: float
    stt_noise_sample_seconds: float
    stt_noise_multiplier: float
    stt_preroll_seconds: float
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
    tts_max_speak_chars: int
    tts_speak_oneshot: bool

    @classmethod
    def from_env(cls) -> "VoiceConfig":
        voice_enabled = env_bool("VOICE_ENABLED", True)
        profile_file = Path(env_value("JARVIS_VOICE_PROFILE_FILE", "config/voice_profiles.json"))
        profile_name, profile = load_voice_profile(profile_file, env_value("JARVIS_VOICE_PROFILE"))
        return cls(
            api_key=env_value("NVIDIA_API_KEY"),
            profile_name=profile_name,
            profile_file=profile_file,
            space_trigger=env_bool("VOICE_SPACE_TRIGGER", True),
            listen_wait_timeout_seconds=env_float("VOICE_LISTEN_WAIT_TIMEOUT_SECONDS", 20.0),
            listen_after_tts_delay_seconds=env_float("VOICE_LISTEN_AFTER_TTS_DELAY_SECONDS", 0.35),
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
            stt_silence_seconds=env_float(
                "STT_POST_SPEECH_SILENCE_SECONDS",
                env_float("STT_SILENCE_SECONDS", env_float("STT_PAUSE_THRESHOLD", 0.25)),
            ),
            stt_energy_threshold=env_float("STT_ENERGY_THRESHOLD", 650.0),
            stt_min_speech_rms=env_float("STT_MIN_SPEECH_RMS", 0.035),
            stt_noise_sample_seconds=env_float("STT_NOISE_SAMPLE_SECONDS", 0.25),
            stt_noise_multiplier=env_float("STT_NOISE_MULTIPLIER", 2.4),
            stt_preroll_seconds=env_float("STT_PREROLL_SECONDS", 0.2),
            stt_input_gain=env_float("STT_INPUT_GAIN", 1.0),
            tts_enabled=voice_enabled and env_bool("TTS_ENABLED", False),
            tts_provider=env_value("TTS_PROVIDER", "nvidia").lower(),
            tts_server=env_value("TTS_NVIDIA_SERVER", "grpc.nvcf.nvidia.com:443"),
            tts_function_id=env_value("TTS_NVIDIA_FUNCTION_ID"),
            tts_language_code=env_value("TTS_NVIDIA_LANGUAGE_CODE", "en-US"),
            tts_voice=voice_profile_value(profile, "tts_voice", "TTS_VOICE", "Magpie-Multilingual.EN-US.Leo.Calm"),
            tts_use_ssl=env_bool("TTS_NVIDIA_USE_SSL", True),
            tts_sample_rate=env_int("TTS_NVIDIA_SAMPLE_RATE", 44100),
            tts_streaming=env_bool("TTS_NVIDIA_STREAMING", True),
            tts_ssml=env_bool("TTS_NVIDIA_SSML", True),
            tts_rate=voice_profile_value(profile, "tts_rate", "TTS_RATE", "+12%"),
            tts_pitch=voice_profile_value(profile, "tts_pitch", "TTS_PITCH", "-18Hz"),
            tts_volume=voice_profile_value(profile, "tts_volume", "TTS_VOLUME", "+55%"),
            tts_voice_effect=voice_profile_value(profile, "tts_voice_effect", "TTS_VOICE_EFFECT", "heavy").lower(),
            tts_heavy_pitch_factor=voice_profile_float(profile, "tts_heavy_pitch_factor", "TTS_HEAVY_PITCH_FACTOR", 1.14),
            tts_heavy_darkness=voice_profile_float(profile, "tts_heavy_darkness", "TTS_HEAVY_DARKNESS", 0.34),
            tts_playback_speed=voice_profile_float(profile, "tts_playback_speed", "TTS_PLAYBACK_SPEED", 1.06),
            tts_max_speak_chars=env_int("TTS_MAX_SPEAK_CHARS", 300),
            tts_speak_oneshot=env_bool("TTS_SPEAK_ONESHOT", False),
        )


def load_voice_profile(path: Path, requested_profile: str) -> tuple[str, dict[str, object]]:
    if not path.exists():
        return "", {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return "", {}
    if not isinstance(data, dict):
        return "", {}
    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict):
        return "", {}
    name = requested_profile.strip() or str(data.get("default_profile", "")).strip()
    profile = profiles.get(name)
    if isinstance(profile, dict):
        return name, profile
    return "", {}


def voice_profile_value(profile: dict[str, object], profile_key: str, env_name: str, fallback: str) -> str:
    value = env_value(env_name)
    if value:
        return value
    profile_value = profile.get(profile_key)
    if isinstance(profile_value, str) and profile_value.strip():
        return profile_value.strip()
    return fallback


def voice_profile_float(profile: dict[str, object], profile_key: str, env_name: str, fallback: float) -> float:
    value = env_value(env_name)
    if value:
        try:
            return float(value)
        except ValueError:
            return fallback
    profile_value = profile.get(profile_key)
    if isinstance(profile_value, (int, float)):
        return float(profile_value)
    if isinstance(profile_value, str):
        try:
            return float(profile_value)
        except ValueError:
            return fallback
    return fallback


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def voice_status_lines(config: VoiceConfig) -> list[str]:
    lines = [
        f"Voice space trigger -> {'on' if config.space_trigger else 'off'}",
        f"Voice profile -> {config.profile_name or 'env/default'}",
        f"STT -> {'on' if config.stt_enabled else 'off'} ({config.stt_provider})",
        f"TTS -> {'on' if config.tts_enabled else 'off'} ({config.tts_provider})",
        f"NVIDIA_API_KEY -> {'set' if config.api_key else 'missing'}",
        f"STT server -> {config.stt_server}",
        f"STT function -> {'set' if config.stt_function_id else 'missing'}",
        f"STT streaming -> {'on' if config.stt_streaming else 'off'}",
        f"STT input device -> {config.stt_input_device or 'system default'}",
        f"STT endpointing -> threshold {config.stt_energy_threshold}, min RMS {config.stt_min_speech_rms}, silence {config.stt_silence_seconds}s",
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


def microphone_level_report(config: VoiceConfig, seconds: float = 1.5) -> str:
    if not has_module("sounddevice"):
        raise VoiceError("Missing python package: sounddevice")
    if not has_module("numpy"):
        raise VoiceError("Missing python package: numpy")

    import numpy as np
    import sounddevice as sd

    sample_rate = max(8000, config.stt_sample_rate)
    block_size = max(400, int(sample_rate * 0.05))
    levels: list[float] = []
    input_device = select_input_device(config)
    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        blocksize=block_size,
        device=input_device,
    ) as stream:
        end_at = time.monotonic() + max(0.2, seconds)
        while time.monotonic() < end_at:
            block, _overflow = stream.read(block_size)
            levels.append(rms(block.reshape(-1)))

    if not levels:
        return "No microphone levels captured."
    median = float(np.median(levels))
    mean = float(np.mean(levels))
    peak = max(levels)
    threshold = speech_threshold(
        levels,
        normalized_energy_threshold(config.stt_energy_threshold),
        config.stt_min_speech_rms,
        config.stt_noise_multiplier,
    )
    return "\n".join(
        [
            f"Mic RMS median -> {median:.5f} ({median * 32768:.0f} / 32768)",
            f"Mic RMS mean -> {mean:.5f} ({mean * 32768:.0f} / 32768)",
            f"Mic RMS peak -> {peak:.5f} ({peak * 32768:.0f} / 32768)",
            f"Speech threshold -> {threshold:.5f} ({threshold * 32768:.0f} / 32768)",
        ]
    )


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


def rms(samples: object) -> float:
    import numpy as np

    if not hasattr(samples, "size") or not samples.size:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples))))


def speech_threshold(noise_levels: list[float], base_threshold: float, min_speech_rms: float, multiplier: float) -> float:
    threshold = max(0.0, base_threshold, min_speech_rms)
    if noise_levels:
        import numpy as np

        noise_floor = float(np.median(noise_levels))
        threshold = max(threshold, noise_floor * max(1.0, multiplier))
    return threshold


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
    base_threshold = normalized_energy_threshold(config.stt_energy_threshold)
    threshold = max(base_threshold, config.stt_min_speech_rms)
    noise_sample_deadline = time.monotonic() + max(0.0, config.stt_noise_sample_seconds)
    preroll_blocks = max(1, int(max(0.05, config.stt_preroll_seconds) * sample_rate / block_size))
    preroll = deque(maxlen=preroll_blocks)
    noise_levels: list[float] = []
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
            raw_mono = block.reshape(-1)
            energy = rms(raw_mono)
            mono = raw_mono
            if config.stt_input_gain != 1.0:
                mono = np.clip(mono * config.stt_input_gain, -1.0, 1.0)
            now = time.monotonic()
            if not speech_started:
                preroll.append(mono.copy())
                if now <= noise_sample_deadline:
                    noise_levels.append(energy)
                    threshold = speech_threshold(
                        noise_levels,
                        base_threshold,
                        config.stt_min_speech_rms,
                        config.stt_noise_multiplier,
                    )
            just_started = False
            if energy >= threshold:
                if not speech_started:
                    speech_started = True
                    speech_started_at = now
                    chunks.extend(item.copy() for item in preroll)
                    just_started = True
                last_voice_at = now
            if speech_started:
                if not just_started:
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
    clean_text = speakable_text(text)
    if not clean_text or not config.tts_ssml:
        return clean_text
    volume = ssml_volume_value(config.tts_volume)
    return (
        "<speak><prosody "
        f'rate="{html.escape(ssml_rate_value(config.tts_rate), quote=True)}" '
        f'pitch="{html.escape(config.tts_pitch, quote=True)}" '
        f'volume="{html.escape(volume, quote=True)}">'
        f"{escape_ssml_text(clean_text)}"
        "</prosody></speak>"
    )


def speakable_text(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if is_timing_line(line):
            continue
        line = strip_markdown_speech_noise(line)
        line = strip_speech_paths_and_urls(line)
        line = clean_speech_symbols(line)
        if line:
            lines.append(line)
    return " ".join(lines).strip()


def is_timing_line(line: str) -> bool:
    compact = "".join(line.lower().split())
    return compact.startswith("first=") and "total=" in compact


def strip_markdown_speech_noise(line: str) -> str:
    while line.startswith("#"):
        line = line[1:].strip()
    for marker in ("- ", "* ", "> "):
        if line.startswith(marker):
            line = line[len(marker) :].strip()
    return line.replace("`", "").replace("#", "").strip()


def strip_speech_paths_and_urls(line: str) -> str:
    arrow_index = line.find(" -> ")
    if arrow_index >= 0:
        right_side = line[arrow_index + 4 :].strip()
        if text_starts_with_path_or_url(right_side):
            line = line[:arrow_index].rstrip()

    result: list[str] = []
    index = 0
    while index < len(line):
        if text_starts_with_path_or_url(line[index:]):
            replacement = speech_path_replacement(line, index)
            index = skip_path_or_url(line, index)
            if replacement:
                if result and result[-1] not in {" ", ".", ",", ":"}:
                    result.append(" ")
                result.append(replacement)
            elif result and result[-1] not in {" ", ".", ",", ":"}:
                result.append(" ")
            continue
        result.append(line[index])
        index += 1
    return collapse_spaces("".join(result)).strip(" ,:")


def text_starts_with_path_or_url(text: str) -> bool:
    if text.startswith("http://") or text.startswith("https://") or text.startswith("www."):
        return True
    if len(text) >= 3 and text[0].isalpha() and text[1] == ":" and text[2] in {"\\", "/"}:
        return True
    if text.startswith("\\\\"):
        return True
    return False


def skip_path_or_url(text: str, start: int) -> int:
    if text.startswith("http://", start) or text.startswith("https://", start) or text.startswith("www.", start):
        index = start
        while index < len(text) and not text[index].isspace():
            index += 1
        return index

    index = start
    while index < len(text):
        char = text[index]
        if char in {"\n", "\r", "\t"}:
            break
        if char in {".", "!", "?"} and index + 1 < len(text) and text[index + 1].isspace():
            break
        if char in {",", ";"}:
            break
        index += 1
    return index


def speech_path_replacement(text: str, start: int) -> str:
    if text.startswith("http://", start) or text.startswith("https://", start) or text.startswith("www.", start):
        return "link"
    end = skip_path_or_url(text, start)
    local_path = text[start:end].strip()
    leaf = local_path.replace("\\", "/").split("/")[-1]
    if "." in leaf and leaf.rsplit(".", 1)[-1]:
        return "local file"
    return "local folder"


def clean_speech_symbols(line: str) -> str:
    replacements = {
        "|": ", ",
        "\\": " ",
        "/": " ",
        "{": " ",
        "}": " ",
        "[": " ",
        "]": " ",
    }
    cleaned: list[str] = []
    for char in line:
        cleaned.append(replacements.get(char, char))
    return collapse_spaces("".join(cleaned))


def collapse_spaces(text: str) -> str:
    return " ".join(text.split())


def speech_chunks(text: str, max_chars: int) -> list[str]:
    clean_text = collapse_spaces(speakable_text(text))
    if not clean_text:
        return []
    limit = max(80, min(380, max_chars))
    pieces = split_speech_pieces(clean_text)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        for part in split_oversized_piece(piece, limit):
            candidate = part if not current else f"{current} {part}"
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks


def split_speech_pieces(text: str) -> list[str]:
    pieces: list[str] = []
    current: list[str] = []
    for char in text:
        current.append(char)
        if char in {".", "!", "?", ";", ",", ":"}:
            piece = "".join(current).strip()
            if piece:
                pieces.append(piece)
            current = []
    tail = "".join(current).strip()
    if tail:
        pieces.append(tail)
    return pieces


def split_oversized_piece(piece: str, limit: int) -> list[str]:
    if len(piece) <= limit:
        return [piece]
    parts: list[str] = []
    current = ""
    for word in piece.split():
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        if len(word) <= limit:
            current = word
        else:
            for index in range(0, len(word), limit):
                parts.append(word[index : index + limit])
            current = ""
    if current:
        parts.append(current)
    return parts


def escape_ssml_text(text: str) -> str:
    escaped = html.escape(text, quote=False)
    return escaped.replace("&apos;", "'").replace("&#x27;", "'")


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


def nvidia_tts_voice_names(config: VoiceConfig) -> list[str]:
    ensure_nvidia_voice(config, "tts")
    from riva.client.proto import riva_tts_pb2

    auth = nvidia_auth(config, "tts")
    import riva.client

    service = riva.client.SpeechSynthesisService(auth)
    response = service.stub.GetRivaSynthesisConfig(
        riva_tts_pb2.RivaSynthesisConfigRequest(),
        metadata=service.auth.get_auth_metadata(),
    )
    voices: list[str] = []
    for model_config in getattr(response, "model_config", []):
        parameters = getattr(model_config, "parameters", {})
        prefix = str(parameters.get("voice_name", "")).strip()
        subvoices = str(parameters.get("subvoices", "")).strip()
        for entry in subvoices.split(","):
            name = entry.split(":", 1)[0].strip()
            if not name:
                continue
            full_name = f"{prefix}.{name}" if prefix and not name.startswith(prefix) else name
            if full_name not in voices:
                voices.append(full_name)
    return voices


def voice_catalog_text(config: VoiceConfig, locale: str = "EN-US") -> str:
    locale_prefix = f"Magpie-Multilingual.{locale.upper()}."
    voices = [voice for voice in nvidia_tts_voice_names(config) if voice.startswith(locale_prefix)]
    if not voices:
        return f"No voices found for {locale.upper()}."
    return "\n".join(voices)


def output_sample_rate(config: VoiceConfig) -> int:
    speed = config.tts_playback_speed if config.tts_playback_speed > 0 else 1.0
    rate = config.tts_sample_rate * speed
    return max(8000, int(rate))


def darken_pcm(config: VoiceConfig, samples):
    if config.tts_voice_effect != "heavy" or config.tts_heavy_darkness <= 0:
        return samples

    import numpy as np

    darkness = min(0.45, max(0.0, config.tts_heavy_darkness))
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
    chunks = speech_chunks(text, config.tts_max_speak_chars)
    if not chunks:
        return
    for chunk in chunks:
        if config.tts_streaming:
            try:
                stream_nvidia_tts_to_output(config, chunk)
                continue
            except Exception:
                audio = synthesize_nvidia_tts(config, chunk, streaming=False)
                play_pcm_audio(config, audio)
                continue
        audio = synthesize_nvidia_tts(config, chunk, streaming=False)
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
        self._idle = threading.Event()
        self._idle.set()
        if config.tts_enabled:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def say(self, text: str) -> None:
        if not self._thread or not text.strip():
            return
        self._idle.clear()
        self._queue.put(text)

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        return self._idle.wait(timeout=timeout)

    def close(self) -> None:
        if not self._thread:
            return
        self._queue.put(None)

    def _run(self) -> None:
        while True:
            text = self._queue.get()
            if text is None:
                self._idle.set()
                return
            try:
                speak_text_blocking(self.config, text)
            except Exception as error:
                if not self._failed:
                    self._failed = True
                    print(short_voice_error(error), file=sys.stderr)
            finally:
                if self._queue.empty():
                    self._idle.set()


def short_voice_error(error: Exception) -> str:
    message = str(error).strip()
    compact = message.lower()
    if "maximum sequence length" in compact or "longer than maximum" in compact:
        return "Voice output failed: NVIDIA rejected an oversized speech segment."
    if "triton" in compact or "grpc" in compact or "inactiverpcerror" in compact:
        return "Voice output failed: NVIDIA voice service returned an audio error."
    first_line = message.splitlines()[0] if message else error.__class__.__name__
    if len(first_line) > 180:
        first_line = first_line[:177].rstrip() + "..."
    return f"Voice output failed: {first_line}"


def listen_after_output_idle(
    config: VoiceConfig,
    speaker: VoiceSpeaker,
    listen_func: Callable[[VoiceConfig], str] | None = None,
) -> str:
    wait_for_output_idle(config, speaker)
    if listen_func is None:
        listen_func = listen_once
    return listen_func(config)


def wait_for_output_idle(config: VoiceConfig, speaker: VoiceSpeaker) -> None:
    speaker.wait_until_idle(config.listen_wait_timeout_seconds)
    if config.listen_after_tts_delay_seconds > 0:
        time.sleep(config.listen_after_tts_delay_seconds)


def read_text_or_voice(
    prompt: str,
    config: VoiceConfig,
    listener: Callable[[], str] | None = None,
    before_listen: Callable[[], None] | None = None,
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
            if before_listen is not None:
                writer.write("[waiting for speech output...]\n")
                writer.flush()
                before_listen()
                writer.write(f"{prompt}")
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
