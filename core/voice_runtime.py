from __future__ import annotations

from pathlib import Path
from typing import Callable

from core.nvidia_stt import NvidiaSTTConfig, SpeechRecognitionMicrophone, SpeechToText, create_speech_to_text


class VoiceInputEmpty(RuntimeError):
    pass


StatusCallback = Callable[[str], None]


def load_speech_engine(config: NvidiaSTTConfig, status: StatusCallback | None = None) -> SpeechToText:
    if status is not None:
        provider_name = "web speech recognizer" if config.provider in {"web", "speech_recognition"} else "NVIDIA speech model"
        status(f"Loading {provider_name}...")
    return create_speech_to_text(config)


def listen_once_text(
    config: NvidiaSTTConfig,
    speech: SpeechToText | None = None,
    status: StatusCallback | None = None,
) -> str:
    audio_path: Path | None = None
    try:
        if speech is None:
            speech = load_speech_engine(config, status)
        microphone = SpeechRecognitionMicrophone(config)
        if status is not None:
            status("Listening... speak naturally, then pause.")
        audio_path = microphone.listen_to_wav()
        if audio_path is None:
            raise VoiceInputEmpty("I did not hear speech before the timeout.")
        if status is not None:
            provider_name = "web speech" if config.provider in {"web", "speech_recognition"} else "NVIDIA"
            status(f"Transcribing with {provider_name}...")
        transcript = speech.transcribe_file(audio_path).strip()
        if not transcript:
            raise VoiceInputEmpty("NVIDIA did not return a transcript.")
        return transcript
    finally:
        if audio_path is not None:
            audio_path.unlink(missing_ok=True)
