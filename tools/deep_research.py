"""
A.N.K.I.T.A — Deep Research Engine 🐍 (Hydra / Broodmother)
=============================================================
Transforms any topic into a structured Master Intelligence Brief by:

  1. SPLINTER  — LLM breaks topic into 4-6 focused sub-queries
  2. SCOUT SWARM — parallel ThreadPoolExecutor (up to 10 workers) each:
       a. search_and_fetch(sub_query) → search results + page text
       b. fetch_page_content(url) for top 2-3 URLs per sub-query
       c. LLM summarises its own findings → 3 bullet points (Map step)
  3. REDUCE    — Broodmother LLM call merges all scout summaries into a
                 Master Intelligence Brief (structured: topics, key facts,
                 conflicts, sources)
  4. Returns a RESEARCH_CONTEXT_BLOCK string ready to be injected into
     ContentAgent's system prompt for Journalist Mode writing.

Usage:
    from tools.deep_research import deep_research
    brief = deep_research("AI regulation in India 2025", runtime=runtime)
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Max parallel scout threads
_MAX_SCOUTS = 10

# Max chars to read per page inside each scout
_SCOUT_MAX_CHARS = 8000

# Max sub-queries to splinter into
_MAX_SUB_QUERIES = 6


# ─────────────────────────────────────────────────────────────────────────────
# SPLINTER — break topic into focused sub-queries
# ─────────────────────────────────────────────────────────────────────────────

def _splinter(topic: str, runtime: Any) -> List[str]:
    """Ask the LLM to decompose a topic into 4-6 focused research sub-queries."""
    from llm import call_chat_once

    messages = [
        {
            "role": "system",
            "content": (
                "You are a research strategist. Given a topic, output a JSON array of "
                f"4-{_MAX_SUB_QUERIES} focused search sub-queries that together cover "
                "the topic comprehensively. Sub-queries should be specific, diverse, "
                "and each answerable by a web search. "
                "Return ONLY a valid JSON array of strings. No markdown. No explanation."
            ),
        },
        {"role": "user", "content": f"Topic: {topic}"},
    ]
    try:
        response = call_chat_once(runtime, messages, tools=None, max_tokens=256)
        content = (response.get("content") or "").strip()
        # Strip markdown fences if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        queries = json.loads(content)
        if isinstance(queries, list) and queries:
            return [str(q) for q in queries[:_MAX_SUB_QUERIES]]
    except Exception as err:
        log.warning("[DeepResearch] Splinter failed: %s — using topic directly", err)

    # Fallback: use the topic itself as a single query
    return [topic]


# ─────────────────────────────────────────────────────────────────────────────
# SCOUT — one parallel thread's job
# ─────────────────────────────────────────────────────────────────────────────

def _scout(sub_query: str, runtime: Any) -> Dict[str, Any]:
    """
    One scout's full research loop for a single sub-query.
    Returns: {sub_query, sources: [{url, title, content}], summary, bullets}
    """
    from llm import call_chat_once
    from tools.realtime_search import search_and_fetch, fetch_page_content

    sources: List[Dict[str, Any]] = []

    # Step 1: search + auto-fetch top 3 pages
    try:
        result = search_and_fetch(
            query=sub_query,
            max_results=6,
            fetch_top=3,
            max_chars_per_page=_SCOUT_MAX_CHARS,
        )
        for item in result.get("results", []):
            if item.get("content", "").strip():
                sources.append({
                    "url":     item.get("url", ""),
                    "title":   item.get("title", ""),
                    "content": item.get("content", "")[:_SCOUT_MAX_CHARS],
                })
    except Exception as err:
        log.warning("[Scout] search_and_fetch failed for %r: %s", sub_query, err)

    if not sources:
        return {
            "sub_query": sub_query,
            "sources":   [],
            "summary":   f"No data found for: {sub_query}",
            "bullets":   [],
        }

    # Step 2: Map — ask LLM to summarise this scout's findings into 3 bullets
    combined_content = ""
    for s in sources[:3]:
        combined_content += f"\n\n[{s['title']}] ({s['url']})\n{s['content'][:3000]}"
    combined_content = combined_content[:10000]

    bullets: List[str] = []
    summary = ""
    try:
        map_messages = [
            {
                "role": "system",
                "content": (
                    "You are a research analyst. Read the following web content and extract "
                    "exactly 3 bullet points of key facts relevant to the sub-query. "
                    "Be specific. Include numbers, names, dates where present. "
                    "Output ONLY the 3 bullet points as a JSON array of strings."
                ),
            },
            {
                "role": "user",
                "content": f"Sub-query: {sub_query}\n\nContent:\n{combined_content}",
            },
        ]
        map_response = call_chat_once(runtime, map_messages, tools=None, max_tokens=400)
        map_content = (map_response.get("content") or "").strip()
        if map_content.startswith("```"):
            map_content = map_content.split("```")[1]
            if map_content.startswith("json"):
                map_content = map_content[4:]
        bullets = json.loads(map_content)
        if not isinstance(bullets, list):
            bullets = []
        summary = " | ".join(bullets[:3])
    except Exception as err:
        log.warning("[Scout] Map LLM call failed: %s", err)
        # Fallback: use first 300 chars of combined content
        summary = combined_content[:300]

    return {
        "sub_query": sub_query,
        "sources":   [{"url": s["url"], "title": s["title"]} for s in sources],
        "summary":   summary,
        "bullets":   bullets,
    }


# ─────────────────────────────────────────────────────────────────────────────
# REDUCE — Broodmother merges all scout outputs into the Master Brief
# ─────────────────────────────────────────────────────────────────────────────

def _reduce(topic: str, scout_results: List[Dict[str, Any]], runtime: Any) -> str:
    """
    Broodmother LLM call — synthesises all scout summaries into a structured
    Master Intelligence Brief with:
      - Executive Summary
      - Key Facts (with sources)
      - Conflicting Information (if any)
      - Gaps / Caveats
      - Source List
    """
    from llm import call_chat_once

    # Build the Broodmother input
    scout_text_parts = []
    all_sources: List[str] = []
    for r in scout_results:
        sq = r.get("sub_query", "")
        bullets = r.get("bullets", [])
        sources = r.get("sources", [])
        bullet_text = "\n".join(f"  • {b}" for b in bullets) if bullets else "  (no data)"
        source_urls = [s.get("url", "") for s in sources if s.get("url", "")]
        all_sources.extend(source_urls)
        scout_text_parts.append(
            f"SUB-QUERY: {sq}\n{bullet_text}\n"
            f"SOURCES: {', '.join(source_urls[:3]) if source_urls else 'none'}"
        )

    broodmother_input = "\n\n---\n\n".join(scout_text_parts)
    unique_sources = list(dict.fromkeys(url for url in all_sources if url))[:20]

    try:
        reduce_messages = [
            {
                "role": "system",
                "content": (
                    "You are the Broodmother — master intelligence analyst. "
                    "You receive parallel scout reports from multiple research threads. "
                    "Your job: synthesise them into a structured Master Intelligence Brief.\n\n"
                    "FORMAT:\n"
                    "RESEARCH_CONTEXT_BLOCK:\n"
                    "TOPIC: <topic>\n"
                    "EXECUTIVE_SUMMARY: <2-3 sentences covering the core answer>\n"
                    "KEY_FACTS:\n"
                    "  - <fact 1> [Source: URL]\n"
                    "  - <fact 2> [Source: URL]\n"
                    "  ... (include 8-15 specific, verifiable facts)\n"
                    "CONFLICTS: <any contradictions between sources, or 'None found'>\n"
                    "GAPS: <what is unknown or unverifiable>\n"
                    "SOURCES:\n"
                    "  - URL1\n"
                    "  - URL2\n"
                    "  ...\n"
                    "END_RESEARCH_CONTEXT\n\n"
                    "Rules:\n"
                    "- Include ONLY facts from the scout reports — no hallucination.\n"
                    "- Attribute every key fact to a source URL.\n"
                    "- If scouts found conflicting info, note it explicitly.\n"
                    "- Write in clear, factual prose — no opinion."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"TOPIC: {topic}\n\n"
                    f"SCOUT REPORTS:\n\n{broodmother_input}\n\n"
                    f"ALL SOURCES: {chr(10).join(unique_sources)}"
                ),
            },
        ]
        reduce_response = call_chat_once(runtime, reduce_messages, tools=None, max_tokens=2048)
        brief = (reduce_response.get("content") or "").strip()
        if not brief:
            raise ValueError("Empty brief from Broodmother")
        return brief
    except Exception as err:
        log.error("[DeepResearch] Reduce failed: %s", err)
        # Fallback: concatenate all scout summaries
        lines = [f"RESEARCH_CONTEXT_BLOCK:\nTOPIC: {topic}\nKEY_FACTS:"]
        for r in scout_results:
            for b in r.get("bullets", []):
                lines.append(f"  - {b}")
        lines.append("END_RESEARCH_CONTEXT")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def deep_research(topic: str, runtime: Any = None) -> Dict[str, Any]:
    """
    Full Hydra deep-research pipeline: Splinter → Scout Swarm → Reduce → Brief.

    Args:
        topic:   The research topic or question.
        runtime: LLMRuntime instance (required for splinter + scout Map + reduce).

    Returns:
        {
            "ok":      bool,
            "topic":   str,
            "brief":   str,   ← the RESEARCH_CONTEXT_BLOCK (inject into ContentAgent)
            "scouts":  int,   ← number of scout threads that ran
            "sources": int,   ← total sources gathered
            "elapsed": float, ← wall-clock seconds
        }
    """
    if not topic or not topic.strip():
        return {"ok": False, "error": "topic is required", "brief": ""}

    t0 = time.time()
    topic = topic.strip()
    log.info("[DeepResearch] 🐍 Starting deep research: %r", topic)

    # 1. SPLINTER
    print(f"[DeepResearch] 🔪 Splintering topic into sub-queries…", flush=True)
    sub_queries = _splinter(topic, runtime)
    print(f"[DeepResearch] 🐝 Launching {len(sub_queries)} scout threads…", flush=True)

    # 2. SCOUT SWARM (parallel)
    scout_results: List[Dict[str, Any]] = []
    max_workers = min(_MAX_SCOUTS, len(sub_queries))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(_scout, sq, runtime): sq
            for sq in sub_queries
        }
        for future in as_completed(future_map):
            sq = future_map[future]
            try:
                result = future.result()
                scout_results.append(result)
                n_sources = len(result.get("sources", []))
                print(
                    f"[Scout ✅] {sq[:50]!r} → {n_sources} sources",
                    flush=True,
                )
            except Exception as err:
                log.warning("[Scout ❌] %r failed: %s", sq, err)
                scout_results.append({
                    "sub_query": sq,
                    "sources":   [],
                    "summary":   f"Scout failed: {err}",
                    "bullets":   [],
                })

    total_sources = sum(len(r.get("sources", [])) for r in scout_results)
    print(
        f"[DeepResearch] 🧠 {len(scout_results)} scouts done, {total_sources} sources. Reducing…",
        flush=True,
    )

    # 3. REDUCE
    brief = _reduce(topic, scout_results, runtime)
    elapsed = time.time() - t0

    print(
        f"[DeepResearch] ✅ Master Brief ready in {elapsed:.1f}s — {len(brief)} chars.",
        flush=True,
    )

    return {
        "ok":      True,
        "topic":   topic,
        "brief":   brief,
        "kind":    "deep_research",
        "scouts":  len(scout_results),
        "sources": total_sources,
        "elapsed": round(elapsed, 2),
        "summary": brief[:300] + "…" if len(brief) > 300 else brief,
    }
