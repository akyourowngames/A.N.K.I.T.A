import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

DEFAULT_BASE_URL = "https://opencode.ai/zen/v1"
DEFAULT_MODEL = "muse-spark-1.3-contributor-free"
ENV_API_KEY = "KILO_API_KEY"
ENV_BASE_URL = "KILO_BASE_URL"
ENV_MODEL = "ZUMBA_MODEL"
CACHE_DIR = Path.home() / ".zumba"
MODELS_CACHE_FILE = CACHE_DIR / "models_cache.json"
MODELS_CACHE_TTL = 24 * 3600
SESSIONS_DIR_NAME = "sessions"


def get_base_url() -> str:
    return (os.getenv(ENV_BASE_URL) or os.getenv("OPENCODE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def get_api_key(require: bool = True) -> str:
    key = (os.getenv("OPENCODE_API_KEY") or os.getenv(ENV_API_KEY) or "").strip().strip('"').strip("'")
    if not key and require:
        raise RuntimeError(
            "KILO_API_KEY (or OPENCODE_API_KEY) is not set. Get one at https://opencode.ai/auth "
            "then set it with: setx KILO_API_KEY \"your_key_here\" "
            "or create a .env file with KILO_API_KEY=your_key_here"
        )
    return key


def get_default_model() -> str:
    env_model = (os.getenv(ENV_MODEL) or "").strip()
    if env_model:
        return env_model
    try:
        from core.store import config_get
        saved = config_get("default_model", "").strip()
        if saved:
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


def get_sessions_dir() -> Path:
    return Path(__file__).resolve().parent / SESSIONS_DIR_NAME
