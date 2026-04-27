from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterator

import requests

from jakata_agent.config import Settings


@dataclass(slots=True)
class EdgeTTSClient:
    voice: str = "en-US-GuyNeural"
    rate: str = "-12%"
    pitch: str = "-18Hz"
    volume: str = "+8%"

    @classmethod
    def from_settings(cls, settings: Settings) -> "EdgeTTSClient":
        return cls(
            voice=settings.edge_tts_voice,
            rate=settings.edge_tts_rate,
            pitch=settings.edge_tts_pitch,
            volume=settings.edge_tts_volume,
        )

    def stream(self, text: str) -> Iterator[bytes]:
        clean_text = " ".join(text.strip().split())
        if not clean_text:
            return
        yield from asyncio.run(self._synthesize(clean_text))

    async def _synthesize(self, text: str) -> list[bytes]:
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError("edge-tts is not installed. Run: pip install -r requirements.txt") from exc

        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            pitch=self.pitch,
            volume=self.volume,
        )
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                chunks.append(chunk["data"])
        return chunks


@dataclass(slots=True)
class SarvamTTSClient:
    api_key: str
    api_url: str
    target_language_code: str = "en-IN"
    speaker: str = "shubh"
    model: str = "bulbul:v3"
    pace: float = 1.1
    speech_sample_rate: int = 22050
    output_audio_codec: str = "mp3"
    enable_preprocessing: bool = True
    timeout_seconds: float = 60.0

    @classmethod
    def from_settings(cls, settings: Settings) -> "SarvamTTSClient":
        return cls(
            api_key=settings.sarvam_api_key,
            api_url=settings.sarvam_tts_url,
            target_language_code=settings.sarvam_tts_language,
            speaker=settings.sarvam_tts_speaker,
            model=settings.sarvam_tts_model,
            pace=settings.sarvam_tts_pace,
            speech_sample_rate=settings.sarvam_tts_sample_rate,
            output_audio_codec=settings.sarvam_tts_codec,
            enable_preprocessing=settings.sarvam_tts_preprocessing,
            timeout_seconds=settings.timeout_seconds,
        )

    def stream(self, text: str) -> Iterator[bytes]:
        clean_text = " ".join(text.strip().split())
        if not clean_text:
            return
        if not self.api_key:
            raise RuntimeError("SARVAM_API_KEY is missing.")

        headers = {
            "api-subscription-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": clean_text,
            "target_language_code": self.target_language_code,
            "speaker": self.speaker,
            "model": self.model,
            "pace": self.pace,
            "speech_sample_rate": self.speech_sample_rate,
            "output_audio_codec": self.output_audio_codec,
            "enable_preprocessing": self.enable_preprocessing,
        }

        with requests.post(
            self.api_url,
            headers=headers,
            json=payload,
            stream=True,
            timeout=(10, self.timeout_seconds),
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
