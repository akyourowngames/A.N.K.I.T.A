"""Bounded structured-output recovery through the existing configured gateway."""
import os
import threading
from memory import llm as memory_llm

_state = threading.local()


def _memory_model():
    # Knowledge provider (Kilo step-3.7 free): ZUMBA_KNOWLEDGE_MODEL wins,
    # otherwise the shared knowledge default from core.config. The endpoint
    # and key resolve inside memory_llm, so chat settings never leak in.
    if os.getenv("ZUMBA_KNOWLEDGE_MODEL", "").strip():
        return os.getenv("ZUMBA_KNOWLEDGE_MODEL", "").strip()
    try:
        from core.config import get_knowledge_model

        return get_knowledge_model()
    except Exception:
        return memory_llm._memory_model()


def reset_trace():
    _state.models = []


def trace():
    return list(dict.fromkeys(getattr(_state, "models", [])))


def _fallback_models():
    raw = os.getenv("ZUMBA_KNOWLEDGE_FALLBACK", "").strip()
    if not raw:
        return []
    return [m.strip() for m in raw.replace(";", ",").split(",") if m.strip()]


def chat_json(prompt, **kwargs):
    chosen = kwargs.pop("model", "") or _memory_model()
    models = [chosen]
    for extra in _fallback_models():
        if extra not in models:
            models.append(extra)
    if _memory_model() not in models:
        models.append(_memory_model())
    last_error = "Invalid structured output"
    for model in models:
        if not hasattr(_state, "models"):
            reset_trace()
        _state.models.append(model)
        try:
            # memory_llm.chat_json already retries transient flakes internally.
            result = memory_llm.chat_json(prompt, model=model, **kwargs)
            if isinstance(result, dict):
                return result
            last_error = f"{model} returned malformed JSON"
        except Exception as exc:
            last_error = str(exc)
    tried = ", ".join(models)
    raise ValueError("Configured graph models could not produce a structured response "
                     f"(tried: {tried}): " + last_error[:350])
