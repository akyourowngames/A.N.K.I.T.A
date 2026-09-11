import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Single place to switch provider/model: set these three in .env and
# everything (chat, memory, knowledge, server) follows. Provider-specific
# names (GROQ_*, KILO_*) still work as fallbacks for backward compat.
DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"
ENV_API_KEY = "ZUMBA_API_KEY"
ENV_BASE_URL = "ZUMBA_BASE_URL"
ENV_MODEL = "ZUMBA_MODEL"
ACTIVE_PROVIDER = "nvidia"
# Provider-specific overrides (checked after the generic ZUMBA_* names).
PROVIDER_API_KEYS = ("NVIDIA_API_KEY", "GROQ_API_KEY")
PROVIDER_BASE_URLS = ("NVIDIA_BASE_URL", "GROQ_BASE_URL")
# Legacy Kilo-gateway env names (still honoured as fallbacks).
LEGACY_API_KEYS = ("KILO_API_KEY", "OPENCODE_API_KEY")
LEGACY_BASE_URLS = ("KILO_BASE_URL", "OPENCODE_BASE_URL")
CACHE_DIR = Path.home() / ".zumba"
MODELS_CACHE_FILE = CACHE_DIR / "models_cache.json"
LEGACY_MODELS_CACHE_FILE = CACHE_DIR / "models_cache_groq.json"
MODELS_CACHE_TTL = 24 * 3600
SESSIONS_DIR_NAME = "sessions"


def _first_env(*names: str) -> str:
    for name in names:
        value = (os.getenv(name) or "").strip().strip('"').strip("'")
        if value:
            return value
    return ""


def get_base_url() -> str:
    explicit = _first_env(ENV_BASE_URL, *PROVIDER_BASE_URLS, *LEGACY_BASE_URLS)
    return (explicit or DEFAULT_BASE_URL).rstrip("/")


def get_api_key(require: bool = True) -> str:
    key = _first_env(ENV_API_KEY, *PROVIDER_API_KEYS, *LEGACY_API_KEYS)
    if not key and require:
        raise RuntimeError(
            "ZUMBA_API_KEY (or NVIDIA_API_KEY) is not set. Get one at https://build.nvidia.com "
            "then set it with: setx ZUMBA_API_KEY \"your_key_here\" "
            "or create a .env file with ZUMBA_API_KEY=your_key_here"
        )
    return key


def get_models_cache_file() -> Path:
    """Cache file for `zumba models`. Namespaced per base_url so switching
    providers in .env never shows a stale model list from the old gateway."""
    try:
        import hashlib

        base = get_base_url().lower()
        digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
        return CACHE_DIR / f"models_cache_{digest}.json"
    except Exception:
        return MODELS_CACHE_FILE


def get_default_model() -> str:
    env_model = (os.getenv(ENV_MODEL) or "").strip()
    if env_model:
        return env_model
    try:
        from core.store import config_get
        saved = config_get("default_model", "").strip()
        if saved:
            # Ignore defaults saved for the legacy Kilo gateway so the
            # configured default becomes active after a provider switch.
            low = saved.lower()
            if low.endswith((":free", "-free")) or "/free" in low or low.startswith(("kilo-", "stepfun/")):
                pass
            else:
                return saved
    except Exception:
        pass
    return DEFAULT_MODEL


def set_default_model(model: str) -> None:
    try:
        from core.store import config_set
        config_set("default_model", model.strip())
    except Exception:
        pass


# --- Knowledge-graph provider (separate from chat) ---------------------------
# Chat/normal tasks use the NIM trio above. Graph ingestion, extraction and
# identity resolution need reliable structured JSON, which currently comes
# from the Kilo gateway's nex-mini free model (verified live 2026-09-11:
# step-3.7-flash:free burns the whole token budget on hidden reasoning and
# returns empty on extraction prompts; nex-n2.5-mini returns valid schema).
# Single switch point: set these three and all memory/knowledge LLM traffic
# follows (chat is untouched).
KNOWLEDGE_DEFAULT_MODEL = "nex-agi/nex-n2.5-mini:free"
ENV_KNOWLEDGE_MODEL = "ZUMBA_KNOWLEDGE_MODEL"
ENV_KNOWLEDGE_API_KEY = "ZUMBA_KNOWLEDGE_API_KEY"
ENV_KNOWLEDGE_BASE_URL = "ZUMBA_KNOWLEDGE_BASE_URL"


def get_knowledge_model() -> str:
    env_model = (os.getenv(ENV_KNOWLEDGE_MODEL) or "").strip()
    if env_model:
        return env_model
    return KNOWLEDGE_DEFAULT_MODEL


def get_knowledge_base_url() -> str:
    explicit = _first_env(ENV_KNOWLEDGE_BASE_URL, *LEGACY_BASE_URLS)
    return (explicit or get_base_url()).rstrip("/")


def get_knowledge_api_key(require: bool = True) -> str:
    key = _first_env(ENV_KNOWLEDGE_API_KEY, *LEGACY_API_KEYS)
    if key:
        return key
    return get_api_key(require=require)


def get_knowledge_llm() -> dict:
    """Triple used by all memory/knowledge structured calls: chat is untouched."""
    return {
        "model": get_knowledge_model(),
        "api_key": get_knowledge_api_key(require=True),
        "base_url": get_knowledge_base_url(),
    }


def get_sessions_dir() -> Path:
    return Path(__file__).resolve().parent / SESSIONS_DIR_NAME
