"""Bounded structured-output recovery through the existing configured gateway."""
import os
import threading
from memory import llm as memory_llm

_state = threading.local()


def _memory_model():
    return os.getenv("ZUMBA_KNOWLEDGE_MODEL", "").strip() or memory_llm._memory_model()


def reset_trace():
    _state.models = []


def trace():
    return list(dict.fromkeys(getattr(_state, "models", [])))


def chat_json(prompt, **kwargs):
    chosen = kwargs.pop("model", "") or _memory_model()
    fallback = os.getenv("ZUMBA_KNOWLEDGE_FALLBACK", "kilo-auto/free").strip()
    models = list(dict.fromkeys([chosen, fallback])) if fallback else [chosen]
    last_error = "Invalid structured output"
    for model in models:
        if not hasattr(_state, "models"):
            reset_trace()
        _state.models.append(model)
        try:
            result = memory_llm.chat_json(prompt, model=model, **kwargs)
            if isinstance(result, dict):
                return result
            last_error = f"{model} returned malformed JSON"
        except Exception as exc:
            last_error = str(exc)
    raise ValueError("Configured graph models could not produce a structured response: " + last_error[:350])
