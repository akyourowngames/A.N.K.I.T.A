from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _split_pipe(value: str) -> list[str]:
    return [item.strip() for item in value.split("|") if item.strip()]


def _normalize_approval_policy(value: str) -> str:
    policy = value.strip().lower()
    if policy in {"manual", "auto_safe", "auto"}:
        return policy
    return "auto_safe"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "off", "no"}


@dataclass(slots=True)
class Settings:
    api_key: str
    base_url: str
    primary_model: str
    fallback_models: list[str]
    vision_model: str
    vision_fallback_models: list[str]
    embedding_model: str
    session_id: str
    data_dir: Path
    tavily_api_key: str
    openweather_api_key: str
    chrome_path: str
    tesseract_cmd: str
    browser_backend: str
    automation_backend: str
    automation_model: str
    browser_automation_model: str
    codex_cli_path: str
    workspace_dir: Path
    camera_device_index: int
    camera_frame_width: int
    camera_frame_height: int
    telegram_bot_token: str
    telegram_admin_password: str
    telegram_admin_password_hash: str
    telegram_session_ttl_minutes: int
    telegram_guest_daily_limit: int
    telegram_max_upload_mb: int
    telegram_safe_roots: list[Path]
    telegram_artifact_dir: Path
    telegram_upload_dir: Path
    image_base_url: str
    image_model: str
    image_size: str
    image_output_dir: Path
    document_output_dir: Path = Path("data/generated/documents")
    document_template_dir: Path = Path("data/document_templates")
    image_infer_url: str = ""
    image_model_namespace: str = "black-forest-labs"
    tts_provider: str = "edge"
    edge_tts_voice: str = "en-US-GuyNeural"
    edge_tts_rate: str = "-12%"
    edge_tts_pitch: str = "-18Hz"
    edge_tts_volume: str = "+8%"
    tts_audio_codec: str = "mp3"
    sarvam_api_key: str = ""
    sarvam_tts_url: str = "https://api.sarvam.ai/text-to-speech/stream"
    sarvam_tts_language: str = "en-IN"
    sarvam_tts_speaker: str = "shubh"
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_pace: float = 1.1
    sarvam_tts_sample_rate: int = 22050
    sarvam_tts_codec: str = "mp3"
    sarvam_tts_preprocessing: bool = True
    sarvam_tts_max_spoken_chars: int = 420
    sarvam_tts_long_response_phrases: list[str] | None = None
    router_model: str = "nvidia/nemotron-mini-4b-instruct"
    router_timeout_seconds: float = 6.0
    router_max_retries: int = 1
    router_max_tokens: int = 512
    router_tool_limit: int = 5
    router_min_tool_score: float = 0.12
    router_general_chat_min_score: float = 0.16
    router_general_chat_min_margin: float = 0.015
    router_tool_over_chat_min_margin: float = 0.05
    local_router_enabled: bool = True
    local_router_confidence_threshold: float = 0.86
    local_router_margin_threshold: float = 0.08
    local_router_min_tool_score: float = 0.62
    local_router_max_tools: int = 2
    fast_chat_model: str = "meta/llama-3.3-70b-instruct"
    fast_chat_fallback_models: list[str] | None = None
    fast_chat_timeout_seconds: float = 8.0
    embedding_timeout_seconds: float = 8.0
    approval_policy: str = "auto_safe"
    companion_enabled: bool = True
    companion_min_interval_seconds: int = 300
    companion_max_per_day: int = 12
    companion_min_score: float = 0.62
    timeout_seconds: float = 60.0
    automation_timeout_seconds: float = 180.0
    max_retries: int = 3
    google_credentials_path: Path = Path("data/integrations/google_credentials.json")
    google_token_path: Path = Path("data/integrations/google_token.json")

    @property
    def model_chain(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for model in [self.primary_model, *self.fallback_models]:
            if model and model not in seen:
                seen.add(model)
                ordered.append(model)
        return ordered

    @property
    def vision_model_chain(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for model in [self.vision_model, *self.vision_fallback_models]:
            if model and model not in seen:
                seen.add(model)
                ordered.append(model)
        return ordered


def load_settings() -> Settings:
    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is missing. Add it to your environment or .env file.")

    data_dir = Path(os.getenv("JAKATA_DATA_DIR", "data")).resolve()
    workspace_dir = Path(os.getenv("JAKATA_WORKSPACE_DIR", ".")).resolve()
    home = Path.home()
    configured_safe_roots = [Path(item).expanduser().resolve() for item in _split_csv(os.getenv("JAKATA_TELEGRAM_SAFE_ROOTS", ""))]
    default_safe_roots = [
        workspace_dir,
        data_dir,
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
    ]
    safe_roots = configured_safe_roots or [path.resolve() for path in default_safe_roots]
    image_base_url = os.getenv("NVIDIA_IMAGE_BASE_URL", "").strip() or os.getenv(
        "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
    ).strip()

    return Settings(
        api_key=api_key,
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").strip(),
        primary_model=os.getenv(
            "NVIDIA_PRIMARY_MODEL", "meta/llama-3.1-8b-instruct"
        ).strip(),
        fallback_models=_split_csv(
            os.getenv(
                "NVIDIA_FALLBACK_MODELS",
                "nvidia/nemotron-mini-4b-instruct,meta/llama-3.3-70b-instruct,nvidia/nemotron-3-super-120b-a12b",
            )
        ),
        vision_model=os.getenv("NVIDIA_VISION_MODEL", "microsoft/phi-4-multimodal-instruct").strip(),
        vision_fallback_models=_split_csv(
            os.getenv(
                "NVIDIA_VISION_FALLBACK_MODELS",
                "google/gemma-3n-e4b-it,nvidia/nemotron-nano-12b-v2-vl,meta/llama-3.2-11b-vision-instruct",
            )
        ),
        embedding_model=os.getenv(
            "NVIDIA_EMBEDDING_MODEL", "nvidia/llama-nemotron-embed-1b-v2"
        ).strip(),
        session_id=os.getenv("JAKATA_SESSION_ID", "default").strip() or "default",
        data_dir=data_dir,
        tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
        openweather_api_key=os.getenv("OPENWEATHER_API_KEY", "").strip(),
        google_credentials_path=Path(
            os.getenv("JAKATA_GOOGLE_CREDENTIALS_PATH", str(data_dir / "integrations" / "google_credentials.json"))
        ).expanduser().resolve(),
        google_token_path=Path(
            os.getenv("JAKATA_GOOGLE_TOKEN_PATH", str(data_dir / "integrations" / "google_token.json"))
        ).expanduser().resolve(),
        chrome_path=os.getenv("JAKATA_CHROME_PATH", "").strip(),
        tesseract_cmd=os.getenv("JAKATA_TESSERACT_CMD", "").strip(),
        browser_backend=os.getenv("JAKATA_BROWSER_BACKEND", "playwright").strip().lower() or "playwright",
        automation_backend=os.getenv("JAKATA_AUTOMATION_BACKEND", "nvidia").strip() or "nvidia",
        automation_model=os.getenv("JAKATA_AUTOMATION_MODEL", "").strip() or "",
        browser_automation_model=os.getenv("JAKATA_BROWSER_AUTOMATION_MODEL", "").strip() or "",
        codex_cli_path=os.getenv("JAKATA_CODEX_CLI_PATH", "codex").strip() or "codex",
        workspace_dir=workspace_dir,
        camera_device_index=int(os.getenv("JAKATA_CAMERA_DEVICE_INDEX", "0").strip() or "0"),
        camera_frame_width=int(os.getenv("JAKATA_CAMERA_FRAME_WIDTH", "960").strip() or "960"),
        camera_frame_height=int(os.getenv("JAKATA_CAMERA_FRAME_HEIGHT", "540").strip() or "540"),
        telegram_bot_token=os.getenv("JAKATA_TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_admin_password=os.getenv("JAKATA_TELEGRAM_ADMIN_PASSWORD", "").strip(),
        telegram_admin_password_hash=os.getenv("JAKATA_TELEGRAM_ADMIN_PASSWORD_HASH", "").strip(),
        telegram_session_ttl_minutes=int(os.getenv("JAKATA_TELEGRAM_SESSION_TTL_MINUTES", "720").strip() or "720"),
        telegram_guest_daily_limit=int(os.getenv("JAKATA_TELEGRAM_GUEST_DAILY_LIMIT", "50").strip() or "50"),
        telegram_max_upload_mb=int(os.getenv("JAKATA_TELEGRAM_MAX_UPLOAD_MB", "45").strip() or "45"),
        telegram_safe_roots=safe_roots,
        telegram_artifact_dir=Path(os.getenv("JAKATA_TELEGRAM_ARTIFACT_DIR", str(data_dir / "telegram" / "artifacts"))).resolve(),
        telegram_upload_dir=Path(os.getenv("JAKATA_TELEGRAM_UPLOAD_DIR", str(data_dir / "telegram" / "uploads"))).resolve(),
        image_base_url=image_base_url,
        image_model=os.getenv("NVIDIA_IMAGE_MODEL", "flux.2-klein-4b").strip() or "flux.2-klein-4b",
        image_size=os.getenv("NVIDIA_IMAGE_SIZE", "1024x1024").strip() or "1024x1024",
        image_output_dir=Path(os.getenv("JAKATA_IMAGE_OUTPUT_DIR", str(data_dir / "generated" / "images"))).resolve(),
        document_output_dir=Path(os.getenv("JAKATA_DOCUMENT_OUTPUT_DIR", str(data_dir / "generated" / "documents"))).resolve(),
        document_template_dir=Path(os.getenv("JAKATA_DOCUMENT_TEMPLATE_DIR", str(data_dir / "document_templates"))).resolve(),
        image_infer_url=os.getenv("NVIDIA_IMAGE_INFER_URL", "").strip(),
        image_model_namespace=os.getenv("NVIDIA_IMAGE_MODEL_NAMESPACE", "black-forest-labs").strip() or "black-forest-labs",
        tts_provider=os.getenv("JAKATA_TTS_PROVIDER", "edge").strip().lower() or "edge",
        edge_tts_voice=os.getenv("EDGE_TTS_VOICE", "en-US-GuyNeural").strip() or "en-US-GuyNeural",
        edge_tts_rate=os.getenv("EDGE_TTS_RATE", "-12%").strip() or "-12%",
        edge_tts_pitch=os.getenv("EDGE_TTS_PITCH", "-18Hz").strip() or "-18Hz",
        edge_tts_volume=os.getenv("EDGE_TTS_VOLUME", "+8%").strip() or "+8%",
        tts_audio_codec=os.getenv("JAKATA_TTS_AUDIO_CODEC", "mp3").strip() or "mp3",
        sarvam_api_key=os.getenv("SARVAM_API_KEY", "").strip(),
        sarvam_tts_url=os.getenv("SARVAM_TTS_URL", "https://api.sarvam.ai/text-to-speech/stream").strip()
        or "https://api.sarvam.ai/text-to-speech/stream",
        sarvam_tts_language=os.getenv("SARVAM_TTS_LANGUAGE", "en-IN").strip() or "en-IN",
        sarvam_tts_speaker=os.getenv("SARVAM_TTS_SPEAKER", "shubh").strip() or "shubh",
        sarvam_tts_model=os.getenv("SARVAM_TTS_MODEL", "bulbul:v3").strip() or "bulbul:v3",
        sarvam_tts_pace=float(os.getenv("SARVAM_TTS_PACE", "1.1").strip() or "1.1"),
        sarvam_tts_sample_rate=int(os.getenv("SARVAM_TTS_SAMPLE_RATE", "22050").strip() or "22050"),
        sarvam_tts_codec=os.getenv("SARVAM_TTS_CODEC", "mp3").strip() or "mp3",
        sarvam_tts_preprocessing=os.getenv("SARVAM_TTS_PREPROCESSING", "true").strip().lower() not in {"0", "false", "off", "no"},
        sarvam_tts_max_spoken_chars=int(os.getenv("SARVAM_TTS_MAX_SPOKEN_CHARS", "420").strip() or "420"),
        sarvam_tts_long_response_phrases=_split_pipe(
            os.getenv(
                "SARVAM_TTS_LONG_RESPONSE_PHRASES",
                "I have prepared the full response, sir. Please review the written details when ready.|The full briefing is ready, sir. I have kept the detailed version in the chat.|I have completed the detailed answer, sir. The written version is ready for review.",
            )
        ),
        router_model=os.getenv("JAKATA_ROUTER_MODEL", "nvidia/nemotron-mini-4b-instruct").strip()
        or "nvidia/nemotron-mini-4b-instruct",
        router_timeout_seconds=float(os.getenv("JAKATA_ROUTER_TIMEOUT_SECONDS", "6").strip() or "6"),
        router_max_retries=int(os.getenv("JAKATA_ROUTER_MAX_RETRIES", "1").strip() or "1"),
        router_max_tokens=int(os.getenv("JAKATA_ROUTER_MAX_TOKENS", "512").strip() or "512"),
        router_tool_limit=int(os.getenv("JAKATA_ROUTER_TOOL_LIMIT", "5").strip() or "5"),
        router_min_tool_score=float(os.getenv("JAKATA_ROUTER_MIN_TOOL_SCORE", "0.12").strip() or "0.12"),
        router_general_chat_min_score=float(os.getenv("JAKATA_ROUTER_GENERAL_CHAT_MIN_SCORE", "0.16").strip() or "0.16"),
        router_general_chat_min_margin=float(os.getenv("JAKATA_ROUTER_GENERAL_CHAT_MIN_MARGIN", "0.015").strip() or "0.015"),
        router_tool_over_chat_min_margin=float(os.getenv("JAKATA_ROUTER_TOOL_OVER_CHAT_MIN_MARGIN", "0.05").strip() or "0.05"),
        local_router_enabled=_env_bool("JAKATA_LOCAL_ROUTER_ENABLED", True),
        local_router_confidence_threshold=float(os.getenv("JAKATA_LOCAL_ROUTER_CONFIDENCE_THRESHOLD", "0.86").strip() or "0.86"),
        local_router_margin_threshold=float(os.getenv("JAKATA_LOCAL_ROUTER_MARGIN_THRESHOLD", "0.08").strip() or "0.08"),
        local_router_min_tool_score=float(os.getenv("JAKATA_LOCAL_ROUTER_MIN_TOOL_SCORE", "0.62").strip() or "0.62"),
        local_router_max_tools=int(os.getenv("JAKATA_LOCAL_ROUTER_MAX_TOOLS", "2").strip() or "2"),
        fast_chat_model=os.getenv("JAKATA_FAST_CHAT_MODEL", "meta/llama-3.3-70b-instruct").strip()
        or "meta/llama-3.3-70b-instruct",
        fast_chat_fallback_models=_split_csv(os.getenv("JAKATA_FAST_CHAT_FALLBACK_MODELS", "")),
        fast_chat_timeout_seconds=float(os.getenv("JAKATA_FAST_CHAT_TIMEOUT_SECONDS", "8").strip() or "8"),
        embedding_timeout_seconds=float(os.getenv("JAKATA_EMBEDDING_TIMEOUT_SECONDS", "8").strip() or "8"),
        approval_policy=_normalize_approval_policy(os.getenv("JAKATA_APPROVAL_POLICY", "auto_safe")),
        companion_enabled=_env_bool("JAKATA_COMPANION_ENABLED", True),
        companion_min_interval_seconds=int(os.getenv("JAKATA_COMPANION_MIN_INTERVAL_SECONDS", "300").strip() or "300"),
        companion_max_per_day=int(os.getenv("JAKATA_COMPANION_MAX_PER_DAY", "12").strip() or "12"),
        companion_min_score=float(os.getenv("JAKATA_COMPANION_MIN_SCORE", "0.62").strip() or "0.62"),
        timeout_seconds=float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "20").strip() or "20"),
        automation_timeout_seconds=float(os.getenv("JAKATA_AUTOMATION_TIMEOUT_SECONDS", "180").strip() or "180"),
        max_retries=int(os.getenv("NVIDIA_MAX_RETRIES", "1").strip() or "1"),
    )
