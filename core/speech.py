from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

from core.llm_service import load_dotenv


class TextToSpeech(Protocol):
    def speak(self, text: str) -> None:
        ...


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
    voice_effect: str
    heavy_pitch_factor: float
    heavy_darkness: float
    player: str

    @classmethod
    def from_env(cls, project_root: Path) -> "TTSConfig":
        load_dotenv(project_root / ".env")
        return cls(
            enabled=_env_flag("TTS_ENABLED", default=True),
            provider=os.getenv("TTS_PROVIDER", "nvidia").strip().lower(),
            voice=os.getenv("TTS_VOICE", "Magpie-Multilingual.EN-US.Ray.Neutral").strip(),
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
            voice_effect=os.getenv("TTS_VOICE_EFFECT", "heavy").strip().lower(),
            heavy_pitch_factor=float(os.getenv("TTS_HEAVY_PITCH_FACTOR", "1.05")),
            heavy_darkness=float(os.getenv("TTS_HEAVY_DARKNESS", "0.62")),
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
        if self.voice_effect not in {"none", "off", "heavy", "cinematic"}:
            raise ValueError("TTS_VOICE_EFFECT must be none, off, heavy, or cinematic.")
        if not 0.5 <= self.heavy_pitch_factor <= 1.25:
            raise ValueError("TTS_HEAVY_PITCH_FACTOR must be between 0.5 and 1.25.")
        if not 0 <= self.heavy_darkness <= 1:
            raise ValueError("TTS_HEAVY_DARKNESS must be between 0 and 1.")


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
        pitch_factor, darkness = _voice_effect_settings(self.config)
        try:
            if self.config.nvidia_tts_streaming:
                responses = self.service.synthesize_online(
                    request_text,
                    voice_name=self.config.voice,
                    language_code=self.config.nvidia_tts_language_code,
                    encoding=self.riva_client.AudioEncoding.LINEAR_PCM,
                    sample_rate_hz=self.config.nvidia_tts_sample_rate,
                )
                play_pcm_stream(
                    responses,
                    self.config.nvidia_tts_sample_rate,
                    self.config.player,
                    volume=volume,
                    pitch_factor=pitch_factor,
                    darkness=darkness,
                )
                return

            response = self.service.synthesize(
                request_text,
                voice_name=self.config.voice,
                language_code=self.config.nvidia_tts_language_code,
                encoding=self.riva_client.AudioEncoding.LINEAR_PCM,
                sample_rate_hz=self.config.nvidia_tts_sample_rate,
            )
            audio = bytes(getattr(response, "audio", b""))
            play_pcm_audio(
                audio,
                self.config.nvidia_tts_sample_rate,
                self.config.player,
                volume=volume,
                pitch_factor=pitch_factor,
                darkness=darkness,
            )
        except Exception as error:
            raise RuntimeError(f"NVIDIA voice request failed: {error}") from error


def create_text_to_speech(config: TTSConfig) -> TextToSpeech:
    if config.provider in {"nvidia", "nvidia_riva", "riva"}:
        return NvidiaRivaTextToSpeech(config)
    config.validate()
    raise ValueError(f"Unsupported TTS_PROVIDER: {config.provider}")


def text_for_speech(text: str, max_chars: int | None = None) -> str:
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


def _voice_effect_settings(config: TTSConfig) -> tuple[float, float]:
    if config.voice_effect in {"none", "off"}:
        return 1.0, 0.0
    return config.heavy_pitch_factor, config.heavy_darkness


def _effect_sample_rate(sample_rate: int, pitch_factor: float) -> int:
    if abs(pitch_factor - 1.0) < 0.01:
        return sample_rate
    return max(8000, int(round(sample_rate * pitch_factor)))


def _process_pcm16(audio: bytes, *, volume: float = 1.0, darkness: float = 0.0) -> bytes:
    if not audio or (abs(volume - 1.0) < 0.01 and darkness <= 0.01):
        return audio
    try:
        import numpy as np
    except ImportError:
        return audio

    samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32)
    if darkness > 0.01 and samples.size:
        window = max(3, int(round(3 + darkness * 12)))
        if window % 2 == 0:
            window += 1
        if window <= samples.size:
            kernel = np.ones(window, dtype=np.float32) / window
            low_passed = np.convolve(samples, kernel, mode="same")
            wet = min(0.9, darkness * 0.85)
            samples = samples * (1.0 - wet) + low_passed * wet
        drive = 1.0 + darkness * 0.45
        normalized = np.clip(samples / 32768.0, -1.0, 1.0)
        samples = np.tanh(normalized * drive) * (32767.0 / np.tanh(drive))

    samples *= volume
    samples = np.clip(samples, -32768, 32767).astype(np.int16)
    return samples.tobytes()


def _pitch_down_pcm16(audio: bytes, pitch_factor: float) -> bytes:
    if not audio or abs(pitch_factor - 1.0) < 0.01:
        return audio
    try:
        import numpy as np
    except ImportError:
        return audio

    samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32)
    if samples.size < 2:
        return audio
    target_size = max(2, int(round(samples.size / pitch_factor)))
    source_positions = np.linspace(0, samples.size - 1, num=samples.size, dtype=np.float32)
    target_positions = np.linspace(0, samples.size - 1, num=target_size, dtype=np.float32)
    shifted = np.interp(target_positions, source_positions, samples)
    return np.clip(shifted, -32768, 32767).astype(np.int16).tobytes()


def play_pcm_stream(
    responses: Iterable[object],
    sample_rate: int,
    player: str = "auto",
    *,
    volume: float = 1.0,
    pitch_factor: float = 1.0,
    darkness: float = 0.0,
) -> None:
    try:
        import sounddevice as sd
    except ImportError:
        audio = b"".join(bytes(getattr(response, "audio", b"")) for response in responses)
        play_pcm_audio(audio, sample_rate, player, volume=volume, pitch_factor=pitch_factor, darkness=darkness)
        return

    playback_sample_rate = _effect_sample_rate(sample_rate, pitch_factor)
    try:
        with sd.RawOutputStream(samplerate=playback_sample_rate, channels=1, dtype="int16") as stream:
            for response in responses:
                audio = bytes(getattr(response, "audio", b""))
                if audio:
                    stream.write(_process_pcm16(audio, volume=volume, darkness=darkness))
    except Exception:
        with sd.RawOutputStream(samplerate=sample_rate, channels=1, dtype="int16") as stream:
            for response in responses:
                audio = bytes(getattr(response, "audio", b""))
                if audio:
                    audio = _pitch_down_pcm16(audio, pitch_factor)
                    stream.write(_process_pcm16(audio, volume=volume, darkness=darkness))


def play_pcm_audio(
    audio: bytes,
    sample_rate: int,
    player: str = "auto",
    *,
    volume: float = 1.0,
    pitch_factor: float = 1.0,
    darkness: float = 0.0,
) -> None:
    if not audio:
        return
    audio = _process_pcm16(audio, volume=volume, darkness=darkness)
    playback_sample_rate = _effect_sample_rate(sample_rate, pitch_factor)
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
                wav_file.setframerate(playback_sample_rate)
                wav_file.writeframes(audio)
            play_audio_file(audio_path, player)
        finally:
            audio_path.unlink(missing_ok=True)
        return

    try:
        with sd.RawOutputStream(samplerate=playback_sample_rate, channels=1, dtype="int16") as stream:
            stream.write(audio)
    except Exception:
        if playback_sample_rate != sample_rate:
            audio = _pitch_down_pcm16(audio, pitch_factor)
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


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _nvidia_riva_metadata(api_key: str, function_id: str) -> list[list[str]]:
    metadata = [["authorization", f"Bearer {api_key}"]]
    if function_id:
        metadata.insert(0, ["function-id", function_id])
    return metadata
