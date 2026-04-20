from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(slots=True)
class Settings:
    api_key: str
    base_url: str
    primary_model: str
    fallback_models: list[str]
    embedding_model: str
    session_id: str
    data_dir: Path
    tavily_api_key: str
    openweather_api_key: str
    timeout_seconds: float = 60.0
    max_retries: int = 3

    @property
    def model_chain(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for model in [self.primary_model, *self.fallback_models]:
            if model and model not in seen:
                seen.add(model)
                ordered.append(model)
        return ordered


def load_settings() -> Settings:
    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is missing. Add it to your environment or .env file.")

    return Settings(
        api_key=api_key,
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").strip(),
        primary_model=os.getenv(
            "NVIDIA_PRIMARY_MODEL", "moonshotai/kimi-k2-instruct-0905"
        ).strip(),
        fallback_models=_split_csv(
            os.getenv(
                "NVIDIA_FALLBACK_MODELS",
                "z-ai/glm-5,nvidia/nemotron-3-super-120b-a12b,meta/llama-3.3-70b-instruct",
            )
        ),
        embedding_model=os.getenv(
            "NVIDIA_EMBEDDING_MODEL", "nvidia/llama-nemotron-embed-1b-v2"
        ).strip(),
        session_id=os.getenv("JAKATA_SESSION_ID", "default").strip() or "default",
        data_dir=Path(os.getenv("JAKATA_DATA_DIR", "data")).resolve(),
        tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
        openweather_api_key=os.getenv("OPENWEATHER_API_KEY", "").strip(),
    )
