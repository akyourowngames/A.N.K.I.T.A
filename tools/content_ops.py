"""
Content generation operations for A.N.K.I.T.A.

Provides a single dynamic tool — write_and_save_content — that can generate
any type of text content (reports, scripts, songs, pitch decks, etc.) via the
LLM and save the result to the user's Desktop.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, Optional


def _safe_filename(text: str, max_len: int = 40) -> str:
    """Convert arbitrary text into a safe filename fragment."""
    safe = re.sub(r'[\\/:*?"<>|]', "_", text)
    safe = re.sub(r"\s+", "_", safe.strip())
    return safe[:max_len] or "content"


# Known content format keywords, ordered longest-first so multi-word matches win
_FORMAT_KEYWORDS: list = [
    "pitch deck", "pitch script", "progress report", "status report",
    "cover letter", "press release", "product description", "executive summary",
    "short story", "blog post", "case study", "action plan", "lesson plan",
    "meeting notes", "research summary", "project proposal",
    "report", "script", "song", "poem", "essay", "email", "summary",
    "paragraph", "story", "pitch", "letter", "proposal", "plan",
    "outline", "review", "analysis", "description", "bio", "biography",
    "tweet", "caption", "tagline", "slogan", "advertisement", "ad",
]


def detect_format_type(filename_stem: str, raw_text: str = "") -> tuple[str, str]:
    """
    Auto-detect the content format_type and topic from a filename stem
    and optionally the first line of the file.

    Strategy (in priority order):
    1. Match a known format keyword inside the filename stem.
    2. Check the first line of raw_text for a format hint (e.g. "format: script").
    3. Fall back to "content" as the format.

    Also extracts the topic by removing the matched format fragment from the stem.

    Args:
        filename_stem: Filename without extension, with _ and - already replaced by spaces.
        raw_text:      Optional first portion of the file contents.

    Returns:
        (format_type, topic) — both as clean strings.
    """
    stem_lower = filename_stem.lower().strip()

    # 1. Check raw_text first line for an explicit "format: X" directive
    if raw_text:
        first_line = raw_text.splitlines()[0].strip().lower()
        for marker in ("format:", "type:", "content type:"):
            if first_line.startswith(marker):
                declared = first_line[len(marker):].strip()
                if declared:
                    # Topic is everything in the filename stem
                    topic = filename_stem.strip() or "your notes"
                    return declared, topic

    # 2. Scan filename stem for known format keywords (longest match wins)
    detected_format = ""
    for kw in _FORMAT_KEYWORDS:
        if kw in stem_lower:
            detected_format = kw
            # Remove the format keyword from the stem to get the topic
            topic = re.sub(re.escape(kw), "", stem_lower, count=1).strip(" _-")
            topic = re.sub(r"\s+", " ", topic).strip()
            topic = topic if topic else filename_stem.strip()
            return detected_format, topic

    # 3. No format found — use "content" and the full stem as topic
    topic = filename_stem.strip() or "your notes"
    return "content", topic


def write_and_save_content(
    workspace_root: Path,
    topic: str,
    format_type: str,
    extra_context: str = "",
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate any type of text content via LLM and save it to disk.

    Args:
        workspace_root: The ANKITA workspace root (used only for relative ops).
        topic:          What the content is about.
        format_type:    Requested format — e.g. 'report', 'script', 'song',
                        'paragraph', 'pitch deck', 'summary', etc.
        extra_context:  Optional rough notes or extra instructions for the LLM.
        output_dir:     Where to save the file. Defaults to the user's Desktop.

    Returns:
        A dict with keys: ok, path, bytes, spoken_reply.
        'spoken_reply' is the string A.N.K.I.T.A should say aloud via TTS.
    """
    # ------------------------------------------------------------------
    # 1. Import LLM runtime lazily (avoids circular imports at module load)
    # ------------------------------------------------------------------
    from llm import build_runtime_from_env, call_chat_once  # type: ignore

    # ------------------------------------------------------------------
    # 2. Build the generation prompt
    # ------------------------------------------------------------------
    format_clean = format_type.strip() or "content"
    topic_clean = topic.strip() or "the requested subject"
    context_section = (
        f"\n\nAdditional context / rough notes:\n{extra_context.strip()}"
        if extra_context and extra_context.strip()
        else ""
    )

    system_prompt = (
        "You are an expert writer and analyst. "
        "Adapt your tone perfectly to the requested format. "
        "If the format is a song or poem, be creative and use rhyme/rhythm. "
        "If the format is a technical report, be precise and professional. "
        "If the format is a script or pitch deck, be persuasive and structured. "
        "Always produce complete, polished, ready-to-use content — not an outline."
    )

    user_prompt = (
        f"Write a {format_clean} about: {topic_clean}.{context_section}\n\n"
        f"Produce only the final {format_clean} — no meta-commentary, no preamble."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # ------------------------------------------------------------------
    # 3. Call the LLM — use a generous token budget for content generation
    # ------------------------------------------------------------------
    try:
        runtime = build_runtime_from_env()
        # Content generation needs more tokens than typical tool calls
        generation_max_tokens = 2048
        response = call_chat_once(runtime, messages, tools=None, max_tokens=generation_max_tokens)
        generated_text = (response.get("content") or "").strip()
        if not generated_text:
            return {
                "ok": False,
                "error": "LLM returned empty content.",
                "spoken_reply": f"Sorry, I wasn't able to generate the {format_clean}. The model returned no content.",
            }
    except Exception as err:
        return {
            "ok": False,
            "error": str(err),
            "spoken_reply": f"Sorry, I ran into an error while generating the {format_clean}: {err}",
        }

    # ------------------------------------------------------------------
    # 4. Determine output path
    # ------------------------------------------------------------------
    if output_dir:
        dest_dir = Path(output_dir).expanduser()
    else:
        dest_dir = workspace_root / "generated_files"

    dest_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{_safe_filename(topic)}_{_safe_filename(format_clean)}_{timestamp}.txt"
    file_path = dest_dir / filename

    # ------------------------------------------------------------------
    # 5. Save the generated content
    # ------------------------------------------------------------------
    try:
        file_path.write_text(generated_text, encoding="utf-8")
        byte_count = len(generated_text.encode("utf-8"))
    except Exception as err:
        return {
            "ok": False,
            "error": f"Failed to save file: {err}",
            "spoken_reply": f"I generated the {format_clean} but couldn't save it: {err}",
        }

    # ------------------------------------------------------------------
    # 6. Return result with the spoken reply A.N.K.I.T.A will say aloud
    # ------------------------------------------------------------------
    spoken_reply = (
        f"Done! I've generated the {format_clean} about {topic_clean} "
        f"and saved it to the generated_files folder as {filename}."
    )

    return {
        "ok": True,
        "path": str(file_path),
        "bytes": byte_count,
        "filename": filename,
        "topic": topic_clean,
        "format_type": format_clean,
        "spoken_reply": spoken_reply,
    }
