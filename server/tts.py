import io
import re

HEAVY_MALE_VOICES = [
    "en-US-GuyNeural",
    "en-US-ChristopherNeural",
    "en-GB-RyanNeural",
    "en-US-DavisNeural",
    "en-US-EricNeural",
    "en-US-SteffanNeural",
    "en-AU-WilliamNeural",
]

DEFAULT_VOICE = HEAVY_MALE_VOICES[0]


def tts_short_text(text: str, max_chars: int = 280) -> str:
    t = text or ""
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!\[.*?\]\(.*?\)", " ", t)
    t = re.sub(r"\[([^\]]*)\]\(.*?\)", r"\1", t)
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"[*_~>|#-]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", t)
    short = " ".join(p for p in parts[:2] if p).strip() or t
    if len(short) > max_chars:
        cut = short[:max_chars]
        m = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind(", "), cut.rfind("; "))
        if m > 80:
            short = cut[:m + 1].strip()
        else:
            short = cut.rsplit(" ", 1)[0].strip() + "…"
    return short


async def synthesize_mp3(text: str, voice: str = DEFAULT_VOICE, rate: str = "-10%", pitch: str = "-20Hz") -> tuple[bytes, str, str]:
    short = tts_short_text(text)
    if not short:
        raise ValueError("empty text")
    import edge_tts
    voice = (voice or DEFAULT_VOICE).strip()
    if voice.lower() == "default":
        voice = DEFAULT_VOICE
    candidates = [voice] + [v for v in HEAVY_MALE_VOICES if v != voice]
    last_err = ""
    for v in candidates:
        try:
            buf = io.BytesIO()
            comm = edge_tts.Communicate(short, voice=v, rate=rate, pitch=pitch)
            async for chunk in comm.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    buf.write(chunk["data"])
            data = buf.getvalue()
            if data:
                return data, v, short
        except Exception as e:
            last_err = str(e)[:200]
            continue
    raise RuntimeError(last_err or "edge-tts produced no audio")
