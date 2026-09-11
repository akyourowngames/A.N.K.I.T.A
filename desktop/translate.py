"""Hindi (or any non-English) query -> English, the Jarvis way.

The Jarvis reference listens with recognition.lang='hi' and then runs the
transcript through UniversalTranslator (mtranslate -> English) before doing
anything else, so the assistant always reasons in English. Same here: if the
configured STT language is English the text passes through untouched,
otherwise we translate and fall back to the original on any failure.
"""

from __future__ import annotations


def needs_translation(lang: str) -> bool:
    return not (lang or "en").lower().startswith("en")


def to_english(text: str, lang: str = "hi") -> str:
    text = (text or "").strip()
    if not text or not needs_translation(lang):
        return text
    try:
        import mtranslate as mt

        translated = mt.translate(text, "en", "auto")
    except Exception:
        return text
    out = (translated or "").strip()
    return out or text
