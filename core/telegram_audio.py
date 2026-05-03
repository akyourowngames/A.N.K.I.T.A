from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from core.llm_service import load_dotenv


@dataclass(frozen=True)
class AudioTranscript:
    text: str
    language: str
    language_probability: float
    duration_seconds: float


@dataclass(frozen=True)
class AudioTranscriptionConfig:
    enabled: bool
    model_name: str
    device: str
    compute_type: str
    cpu_threads: int
    num_workers: int
    beam_size: int
    batch_size: int
    vad_filter: bool
    language: str
    task: str
    download_root: Path
    max_audio_mb: float

    @classmethod
    def from_env(cls, project_root: Path) -> "AudioTranscriptionConfig":
        load_dotenv(project_root / ".env")
        _configure_hf_hub_env()
        model_name = os.getenv("TELEGRAM_WHISPER_MODEL", "base").strip() or "base"
        task = os.getenv("TELEGRAM_WHISPER_TASK", "transcribe").strip().lower() or "transcribe"
        if task not in {"transcribe", "translate"}:
            task = "transcribe"
        download_root = _env_path(
            "TELEGRAM_WHISPER_DOWNLOAD_ROOT",
            project_root / "memory" / "store" / "faster-whisper",
        )
        return cls(
            enabled=_env_bool("TELEGRAM_AUDIO_TRANSCRIPTION", default=True),
            model_name=model_name,
            device=os.getenv("TELEGRAM_WHISPER_DEVICE", "auto").strip() or "auto",
            compute_type=os.getenv("TELEGRAM_WHISPER_COMPUTE_TYPE", "int8").strip() or "int8",
            cpu_threads=_env_int("TELEGRAM_WHISPER_CPU_THREADS", default=0),
            num_workers=_env_int("TELEGRAM_WHISPER_WORKERS", default=1),
            beam_size=max(1, _env_int("TELEGRAM_WHISPER_BEAM_SIZE", default=1)),
            batch_size=max(1, _env_int("TELEGRAM_WHISPER_BATCH_SIZE", default=1)),
            vad_filter=_env_bool("TELEGRAM_WHISPER_VAD", default=True),
            language=os.getenv("TELEGRAM_WHISPER_LANGUAGE", "").strip(),
            task=task,
            download_root=download_root,
            max_audio_mb=max(1.0, _env_float("TELEGRAM_MAX_AUDIO_MB", default=100.0)),
        )


class FasterWhisperAudioTranscriber:
    def __init__(self, config: AudioTranscriptionConfig):
        self.config = config
        self._model = None
        self._batched_model = None
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, project_root: Path) -> "FasterWhisperAudioTranscriber":
        return cls(AudioTranscriptionConfig.from_env(project_root))

    def status(self) -> str:
        if not self.config.enabled:
            return "disabled"
        language = self.config.language or "auto"
        return (
            f"enabled, model={self.config.model_name}, language={language}, "
            f"device={self.config.device}, compute={self.config.compute_type}"
        )

    def transcribe_file(self, audio_path: Path) -> AudioTranscript:
        if not self.config.enabled:
            raise RuntimeError("Telegram audio transcription is disabled.")
        if not audio_path.exists():
            raise RuntimeError(f"Audio file does not exist: {audio_path}")
        audio_size_mb = audio_path.stat().st_size / (1024 * 1024)
        if audio_size_mb > self.config.max_audio_mb:
            raise RuntimeError(
                f"Audio is {audio_size_mb:.1f} MB, above TELEGRAM_MAX_AUDIO_MB={self.config.max_audio_mb:.1f}."
            )

        start_time = time.perf_counter()
        model = self._ensure_model()
        options = {
            "beam_size": self.config.beam_size,
            "vad_filter": self.config.vad_filter,
            "task": self.config.task,
            "condition_on_previous_text": False,
        }
        if self.config.language:
            options["language"] = self.config.language

        if self.config.batch_size > 1:
            segments, info = self._ensure_batched_model(model).transcribe(
                str(audio_path),
                batch_size=self.config.batch_size,
                **options,
            )
        else:
            segments, info = model.transcribe(str(audio_path), **options)

        parts: list[str] = []
        for segment in segments:
            text = str(getattr(segment, "text", "")).strip()
            if text:
                parts.append(text)

        elapsed = time.perf_counter() - start_time
        return AudioTranscript(
            text=" ".join(parts).strip(),
            language=str(getattr(info, "language", "") or ""),
            language_probability=float(getattr(info, "language_probability", 0.0) or 0.0),
            duration_seconds=elapsed,
        )

    def _ensure_model(self):
        _configure_hf_hub_env()
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel
            except ImportError as error:
                raise RuntimeError(
                    "Install free local transcription support with: python -m pip install faster-whisper"
                ) from error

            self.config.download_root.mkdir(parents=True, exist_ok=True)
            kwargs = {
                "device": self.config.device,
                "compute_type": self.config.compute_type,
                "download_root": str(self.config.download_root),
            }
            if self.config.cpu_threads > 0:
                kwargs["cpu_threads"] = self.config.cpu_threads
            if self.config.num_workers > 0:
                kwargs["num_workers"] = self.config.num_workers
            self._model = WhisperModel(self.config.model_name, **kwargs)
            return self._model

    def _ensure_batched_model(self, model):
        with self._lock:
            if self._batched_model is not None:
                return self._batched_model
            try:
                from faster_whisper import BatchedInferencePipeline
            except ImportError as error:
                raise RuntimeError(
                    "The installed faster-whisper package does not expose batched transcription."
                ) from error
            self._batched_model = BatchedInferencePipeline(model=model)
            return self._batched_model


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    if not value:
        return default.resolve(strict=False)
    return Path(value).expanduser().resolve(strict=False)


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _env_int(name: str, *, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, *, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _configure_hf_hub_env() -> None:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")
    os.environ.setdefault("HUGGINGFACE_HUB_VERBOSITY", os.environ["HF_HUB_VERBOSITY"])
