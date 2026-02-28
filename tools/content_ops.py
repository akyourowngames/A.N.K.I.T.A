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
    # 3. Call the LLM — format-adaptive token budget + 30s timeout
    # ------------------------------------------------------------------
    # Token budget scales with content complexity
    _FORMAT_TOKEN_MAP: Dict[str, int] = {
        "poem": 1024, "email": 1024, "summary": 1024, "caption": 512,
        "tweet": 512, "tagline": 512, "slogan": 512,
        "essay": 2048, "letter": 2048, "script": 2048, "story": 2048,
        "report": 4096, "pitch deck": 4096, "pitch": 4096, "analysis": 4096,
        "proposal": 4096, "plan": 4096,
    }
    generation_max_tokens = 2048  # default
    for fmt_key, tok_budget in _FORMAT_TOKEN_MAP.items():
        if fmt_key in format_clean.lower():
            generation_max_tokens = tok_budget
            break

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
    try:
        runtime = build_runtime_from_env()
        # Wrap LLM call in a 30-second timeout
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(call_chat_once, runtime, messages, None, generation_max_tokens)
            try:
                response = future.result(timeout=30)
            except FuturesTimeout:
                return {
                    "ok": False,
                    "error": "LLM timed out after 30 seconds.",
                    "spoken_reply": f"Sorry, the {format_clean} generation timed out. Try again or use a shorter format.",
                }
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
    # 4. Determine output path — GPS LOCK: always Desktop unless overridden
    # ------------------------------------------------------------------
    if output_dir:
        dest_dir = Path(output_dir).expanduser().resolve()
    else:
        # Hard-wire to the real Desktop — never a hidden project subfolder
        dest_dir = Path.home() / "Desktop"

    dest_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{_safe_filename(topic)}_{_safe_filename(format_clean)}_{timestamp}.txt"
    file_path = dest_dir / filename
    absolute_path = str(file_path.resolve())

    # ------------------------------------------------------------------
    # 5. Save the generated content + write audit log entry
    # ------------------------------------------------------------------
    _audit_write(absolute_path, "attempting", 0)
    try:
        file_path.write_text(generated_text, encoding="utf-8")
        byte_count = len(generated_text.encode("utf-8"))
        _audit_write(absolute_path, "success", byte_count)
    except Exception as err:
        _audit_write(absolute_path, f"FAILED: {err}", 0)
        return {
            "ok": False,
            "error": f"Failed to save file: {err}",
            "spoken_reply": f"I generated the {format_clean} but couldn't save it: {err}",
        }

    # ------------------------------------------------------------------
    # 6. Return receipt — agent MUST see status:success before saying "saved"
    # ------------------------------------------------------------------
    spoken_reply = (
        f"Done! ✅ Generated the {format_clean} about {topic_clean} "
        f"and saved it to Desktop as {filename}."
    )

    return {
        "ok": True,
        "status": "success",
        "path": absolute_path,
        "absolute_path": absolute_path,
        "FILE_PATH": absolute_path,        # picked up by _extract_artifacts
        "bytes": byte_count,
        "filename": filename,
        "topic": topic_clean,
        "format_type": format_clean,
        "spoken_reply": spoken_reply,
    }


# ---------------------------------------------------------------------------
# Audit log helper
# ---------------------------------------------------------------------------

def _audit_write(path: str, status: str, byte_count: int) -> None:
    """Append a write event to ~/.ankita/audit.log for forensics."""
    try:
        import time as _time
        audit_dir = Path.home() / ".ankita"
        audit_dir.mkdir(parents=True, exist_ok=True)
        log_line = (
            f"[{_time.strftime('%Y-%m-%d %H:%M:%S')}] "
            f"Attempted write to: {path} | Status: {status} | Bytes: {byte_count}\n"
        )
        with open(audit_dir / "audit.log", "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception:
        pass  # Audit must never crash the main flow
