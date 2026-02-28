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


_DEEP_MODE_KEYWORDS = {
    "deep", "comprehensive", "detailed", "in-depth", "in depth", "full",
    "10 page", "10-page", "massive", "extensive", "thorough", "research",
    "investigation", "complete", "full investigation", "deep report",
    "deep dive", "deep-dive", "long form", "longform",
}

# Sections for parallel chunk generation — each chunk gets its own LLM call
_DEEP_SECTION_PLAN = [
    ("Executive Summary & Background",
     "Write the Executive Summary (300+ words) and Background & Context (500+ words) sections. "
     "Start with '## Executive Summary' header. Be thorough and substantive."),
    ("Main Analysis — Part 1",
     "Write 2 deep analysis sections (500+ words each) covering the most important aspects. "
     "Use '## [Section Name]' headers. Include specific facts, numbers, examples."),
    ("Main Analysis — Part 2",
     "Write 2 more deep analysis sections (500+ words each) covering different important aspects. "
     "Use '## [Section Name]' headers. Include specific facts, numbers, examples."),
    ("Main Analysis — Part 3",
     "Write 1 deep analysis section (500+ words) covering remaining key aspects, "
     "followed by a Real-World Examples & Case Studies section (600+ words). "
     "Use '## [Section Name]' headers."),
    ("Implications, Conclusion & Recommendations",
     "Write the Implications & Impact section (400+ words), Conclusion (300+ words), "
     "and Recommendations (300+ words). Use '## [Section Name]' headers. "
     "Make the conclusion and recommendations actionable and specific."),
]

_DEEP_MODE_SYSTEM_PROMPT = (
    "You are an expert writer, journalist, and analyst. "
    "You are in DEEP MODE — the user wants a COMPREHENSIVE, LONG-FORM document. "
    "Target: 6000-8000+ words minimum (approximately 10+ pages when printed).\n\n"
    "MANDATORY STRUCTURE:\n"
    "  # [Document Title]\n"
    "  ## Executive Summary (300+ words)\n"
    "  ## Background & Context (500+ words)\n"
    "  ## [Main Analysis Section 1] (500+ words)\n"
    "  ## [Main Analysis Section 2] (500+ words)\n"
    "  ## [Main Analysis Section 3] (500+ words)\n"
    "  ## [Main Analysis Section 4] (500+ words)\n"
    "  ## [Main Analysis Section 5] (500+ words)\n"
    "  ## Real-World Examples & Case Studies (600+ words)\n"
    "  ## Implications & Impact (400+ words)\n"
    "  ## Conclusion (300+ words)\n"
    "  ## Recommendations (300+ words)\n"
    "  ## References / Sources (if available)\n\n"
    "RULES:\n"
    "- Every section MUST be substantive — no filler, no vague summaries.\n"
    "- Use headers (##), subheaders (###), bullet lists, numbered lists throughout.\n"
    "- Include specific facts, numbers, names, dates wherever applicable.\n"
    "- DO NOT truncate. DO NOT summarise at the end. Write the COMPLETE document.\n"
    "- If research context is provided, use ALL facts from it. Cite every claim.\n"
    "- Adapt tone to the format: analytical for reports, narrative for essays, etc.\n"
    "- Quality over speed — this is a flagship document, not a draft."
)

_NORMAL_SYSTEM_PROMPT = (
    "You are an expert writer and analyst. "
    "Adapt your tone perfectly to the requested format. "
    "If the format is a song or poem, be creative and use rhyme/rhythm. "
    "If the format is a technical report, be precise and professional. "
    "If the format is a script or pitch deck, be persuasive and structured. "
    "Always produce complete, polished, ready-to-use content — not an outline."
)

# Token budgets — (normal, deep) per format
_FORMAT_TOKEN_MAP: Dict[str, int] = {
    "poem": 1024, "email": 1024, "summary": 1024, "caption": 512,
    "tweet": 512, "tagline": 512, "slogan": 512,
    "essay": 2048, "letter": 2048, "script": 2048, "story": 2048,
    "report": 3000, "pitch deck": 3000, "pitch": 3000, "analysis": 3000,
    "proposal": 3000, "plan": 3000,
}
_DEEP_TOKEN_BUDGET = 8192   # ~6000-8000 words


def _detect_deep_mode(format_type: str, topic: str, extra_context: str) -> bool:
    """Return True if the request signals deep/comprehensive/long-form writing."""
    combined = f"{format_type} {topic} {extra_context}".lower()
    return any(kw in combined for kw in _DEEP_MODE_KEYWORDS)


def _generate_deep_parallel(
    topic_clean: str,
    format_clean: str,
    context_section: str,
    research_context: str,
    runtime: Any,
    call_chat_once: Any,
) -> str:
    """
    Parallel Chunk Engine — generates a 10-page deep document by splitting it
    into 5 sections and calling the LLM in parallel for each section.
    Then stitches all chunks into a single cohesive document.

    Returns the full assembled document text.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed

    research_note = (
        f"\n\nRESEARCH CONTEXT (use ALL facts, cite sources):\n{research_context}"
        if research_context
        else ""
    )

    def _generate_chunk(section_name: str, section_instructions: str) -> tuple[str, str]:
        chunk_system = (
            _DEEP_MODE_SYSTEM_PROMPT
            + "\n\nYou are generating ONE SECTION of a larger document. "
            "Write ONLY this section — do not write an intro or outro for the whole doc. "
            "Start directly with the section header."
        )
        chunk_user = (
            f"Full document topic: {topic_clean} ({format_clean}){context_section}{research_note}\n\n"
            f"YOUR SECTION TO WRITE: {section_name}\n"
            f"INSTRUCTIONS: {section_instructions}\n\n"
            f"Write this section completely and substantively. Minimum 800 words for this section. "
            f"Use clear ## and ### headers. Start writing now."
        )
        msgs = [
            {"role": "system", "content": chunk_system},
            {"role": "user", "content": chunk_user},
        ]
        try:
            resp = call_chat_once(runtime, msgs, tools=None, max_tokens=2048)
            text = (resp.get("content") or "").strip()
            return section_name, text
        except Exception as err:
            return section_name, f"## {section_name}\n\n[Section generation failed: {err}]"

    # Generate title separately (fast, 128 tokens)
    title_msgs = [
        {"role": "system", "content": "Generate a professional document title only. No extra text."},
        {"role": "user", "content": f"Write a title for a comprehensive {format_clean} about: {topic_clean}"},
    ]
    try:
        title_resp = call_chat_once(runtime, title_msgs, tools=None, max_tokens=64)
        title = (title_resp.get("content") or f"Comprehensive {format_clean.title()}: {topic_clean}").strip()
    except Exception:
        title = f"Comprehensive {format_clean.title()}: {topic_clean}"

    print(f"[ContentEngine] 🚀 Launching {len(_DEEP_SECTION_PLAN)} parallel section threads…", flush=True)

    # Parallel section generation — all 5 sections at once
    section_texts: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(_DEEP_SECTION_PLAN)) as pool:
        futures = {
            pool.submit(_generate_chunk, sname, sinstr): sname
            for sname, sinstr in _DEEP_SECTION_PLAN
        }
        for future in _as_completed(futures):
            sname = futures[future]
            try:
                _, text = future.result()
                section_texts[sname] = text
                wc = len(text.split())
                print(f"[ContentEngine] ✅ Section '{sname}' — {wc} words", flush=True)
            except Exception as err:
                section_texts[sname] = f"## {sname}\n\n[Generation failed: {err}]"

    # Stitch in order
    parts = [f"# {title}\n"]
    for sname, _ in _DEEP_SECTION_PLAN:
        parts.append(section_texts.get(sname, f"## {sname}\n\n[Missing]"))

    full_doc = "\n\n---\n\n".join(parts)
    total_words = len(full_doc.split())
    print(f"[ContentEngine] 🎉 Full document assembled: {total_words} words ({len(full_doc)} chars)", flush=True)
    return full_doc


def write_and_save_content(
    workspace_root: Path,
    topic: str,
    format_type: str,
    extra_context: str = "",
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate any type of text content via LLM and save it to disk.

    Two-speed engine:
      - NORMAL: concise, format-appropriate output (1024–3000 tokens, 30s timeout)
      - DEEP:   long-form, 10-page document (8192 tokens, 120s timeout)
                Triggered by keywords: deep, comprehensive, detailed, in-depth, etc.

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
    # 2. Detect depth mode + build the generation prompt
    # ------------------------------------------------------------------
    format_clean = format_type.strip() or "content"
    topic_clean = topic.strip() or "the requested subject"
    context_section = (
        f"\n\nAdditional context / rough notes:\n{extra_context.strip()}"
        if extra_context and extra_context.strip()
        else ""
    )

    is_deep = _detect_deep_mode(format_clean, topic_clean, extra_context)

    if is_deep:
        # Deep mode uses the Parallel Chunk Engine — generate sections in parallel
        # then stitch. No single LLM call timeout concern.
        generation_max_tokens = _DEEP_TOKEN_BUDGET
        timeout_secs = 180   # per-section calls are 30s each, total wall-clock ~60s parallel
        depth_label = "deep (parallel chunks)"
        # We'll skip messages/system_prompt — handled inside _generate_deep_parallel
        system_prompt = _DEEP_MODE_SYSTEM_PROMPT
        user_prompt = ""  # unused for deep mode
    else:
        system_prompt = _NORMAL_SYSTEM_PROMPT
        user_prompt = (
            f"Write a {format_clean} about: {topic_clean}.{context_section}\n\n"
            f"Produce only the final {format_clean} — no meta-commentary, no preamble."
        )
        # Normal token budget — scales with format
        generation_max_tokens = 2048  # default
        for fmt_key, tok_budget in _FORMAT_TOKEN_MAP.items():
            if fmt_key in format_clean.lower():
                generation_max_tokens = tok_budget
                break
        timeout_secs = 30
        depth_label = "normal"

    if is_deep:
        print(f"[ContentEngine] 🔥 DEEP MODE (Parallel Chunks) for: {topic_clean!r}", flush=True)
    else:
        print(f"[ContentEngine] ✍️  Normal mode: {format_clean!r} — {generation_max_tokens} tokens", flush=True)

    # ------------------------------------------------------------------
    # 3. Call the LLM — branch: parallel chunk engine (deep) or single call (normal)
    # ------------------------------------------------------------------
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
    try:
        runtime = build_runtime_from_env()

        if is_deep:
            # ── PARALLEL CHUNK ENGINE ──────────────────────────────────────────
            # Extract any research context from extra_context if present
            research_ctx = ""
            if "RESEARCH_CONTEXT_BLOCK:" in extra_context:
                research_ctx = extra_context
            elif "[RESEARCH_CONTEXT]" in extra_context:
                research_ctx = extra_context

            generated_text = _generate_deep_parallel(
                topic_clean=topic_clean,
                format_clean=format_clean,
                context_section=context_section,
                research_context=research_ctx,
                runtime=runtime,
                call_chat_once=call_chat_once,
            )
        else:
            # ── NORMAL SINGLE CALL ─────────────────────────────────────────────
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(call_chat_once, runtime, messages, None, generation_max_tokens)
                try:
                    response = future.result(timeout=timeout_secs)
                except FuturesTimeout:
                    return {
                        "ok": False,
                        "error": f"LLM timed out after {timeout_secs} seconds.",
                        "spoken_reply": f"Sorry, the {format_clean} generation timed out after {timeout_secs}s. Try again.",
                    }
            generated_text = (response.get("content") or "").strip()

        if not generated_text:
            return {
                "ok": False,
                "error": "LLM returned empty content.",
                "spoken_reply": f"Sorry, I wasn't able to generate the {format_clean}. The model returned no content.",
            }
        word_count = len(generated_text.split())
        print(f"[ContentEngine] ✅ Generated {word_count} words ({len(generated_text)} chars) [{depth_label}]", flush=True)
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
