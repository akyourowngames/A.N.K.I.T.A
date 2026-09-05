"""Semantic extraction: salience gating, entity/relation extraction, and the
Mem0-style write decision (ADD / UPDATE / INVALIDATE / NOOP). All decision-
making is delegated to the LLM via structured prompts.
"""

from __future__ import annotations

import hashlib

from . import llm

SYSTEM = "You are a meticulous memory curator for a personal assistant. You reason about what is worth remembering and how facts evolve over time."

SALIENCE_PROMPT = """Decide whether this exchange is worth storing in long-term memory.

Rule of thumb — remember things that are:
- stable facts about the user or their world (projects, preferences, people, constraints)
- decisions and their reasons
- events that could be referenced later
- things the user asked to remember

Calibration — memorable (store these):
- "no wait, Atlas is a mobile app, not a website" / assistant: "Got it" -> true (correction of a stored fact)
- "actually I moved to Porto last month" -> true (identity/location change)
- "my name is Sam" / assistant: "Hi!" -> true (first-person identity fact, judge USER text primarily)
- "I prefer dark mode for everything" -> true (stable preference)
- "remember that the deploy key expires in June" -> true (explicit remember request)

Calibration — NOT memorable (skip these):
- "thanks!" / assistant: "anytime" -> false (pure pleasantry, no fact)
- "haha nice" / assistant: "glad you liked it" -> false (chit-chat)
- "what time is it" / assistant: "3pm" -> false (one-off lookup, no future reuse)

Bias: when in doubt about a first-person statement ("I ...", "my ..."), lean MEMORABLE.
A false negative loses the user's identity forever; a false positive only costs tokens.

Do NOT store: transient pleasantries, pure chit-chat without facts, content that is only about the current one-off task and has no future reuse.

EXCHANGE:
USER: {user}
ASSISTANT: {assistant}

Respond with JSON: {{"memorable": true|false, "reasons": ["..."]}}"""

EXTRACT_PROMPT = """Extract the durable knowledge from this exchange as entities and relationships.

Guidelines:
- Entities are people, projects, tools, concepts, organizations, places, technologies, preferences, recurring items.
- Give each entity: name, type, and a concise description embedding the concrete facts (include stable facts).
- Relationships are facts connecting two entities. Include the relationship type (present-tense verb, lowercase), a plain-language fact sentence, and a confidence 0..1.
- Only include things that remain true later (stable), not one-off ephemeral chat.
- Prefer specificity over generality. Use the exact names the user used.
- CORRECTIONS: when the user corrects something ("not a website, it is a mobile app", "I am Sam not Alex"), emit the POSITIVE authoritative fact ("Atlas is a mobile app", "user is Sam"), NOT just a negative ("X is not Y"). Give corrections confidence 0.95+.

EXCHANGE:
USER: {user}
ASSISTANT: {assistant}

Respond with JSON:
{{
  "entities": [{{"name": "..", "type": "..", "description": ".."}}],
  "relations": [{{"source": "..", "target": "..", "type": "..", "fact": "..", "confidence": 0.9}}]
}}"""

WRITE_DECISION_PROMPT = """You are reconciling newly-extracted knowledge against the existing memory graph. Decide, for each new relation, what to do.

Existing graph facts (each: id | source --type--> target | fact):
{existing}

New candidates:
{new_facts}

For each new relation decide an operation:
- ADD: genuinely new, no overlap with existing facts.
- UPDATE: refines, corrects, or supersedes an existing fact (give target_id of that fact).
- NOOP: already fully covered by an existing fact — skip.
- INVALIDATE: the new fact CONTRADICTS an existing one and the new fact is authoritative because it comes from the user's latest statement (give target_id). Corrections like "I am actually Sam, not Alex", "that is not a website, it is a mobile app", "I moved cities" MUST invalidate the outdated fact.
- CONFLICT: cannot tell which is correct; keep both, flag for later.

Be aggressive about invalidation: stale facts that contradict the user's latest statement poison future answers. When a new fact and an old fact cannot both be true, choose UPDATE or INVALIDATE — never ADD both.

Respond with JSON:
{{
  "ops": [
    {{"index": 0, "op": "ADD" | "UPDATE" | "NOOP" | "INVALIDATE" | "CONFLICT",
      "target_id": null | <id>, "reason": ".."}}
  ]
}}"""


def content_hash(user: str, assistant: str) -> str:
    return hashlib.sha256(f"{user}\u0000{assistant}".encode("utf-8")).hexdigest()


def should_remember(user: str, assistant: str) -> bool:
    """Salience gate. Fail-open on any error so memory capture never blocks chat."""
    try:
        out = llm.chat_json(
            SALIENCE_PROMPT.format(user=user[:3000], assistant=assistant[:3000]),
            system=SYSTEM,
            max_tokens=300,
        )
        if not out:
            return False
        return bool(out.get("memorable", False))
    except Exception:
        return False


def extract_graph(user: str, assistant: str, known: list | None = None) -> tuple:
    """Return (entities: list, relations: list). Empty lists on failure."""
    try:
        prompt = EXTRACT_PROMPT.format(user=user[:4000], assistant=assistant[:2000])
        if known:
            names = ", ".join(known[:40])
            prompt += f"\n\nKnown existing entities (use these EXACT names when the exchange refers to them via pronouns, typos, paraphrases like 'it', 'itss', 'my project', 'I'): {names}."
        out = llm.chat_json(
            prompt,
            system=SYSTEM,
            max_tokens=1800,
        )
    except Exception:
        return [], []
    if not isinstance(out, dict):
        return [], []
    ent = out.get("entities") or []
    rel = out.get("relations") or []
    ents = [e for e in ent if isinstance(e, dict) and e.get("name")]
    rels = [r for r in rel if isinstance(r, dict) and r.get("source") and r.get("target")]
    return ents, rels


def decide_writes(new_facts: list, existing: list):
    """Run the write-decider over new relations vs the current graph facts.

    Returns a list of ops dicts aligned to new_facts indices.
    """
    if not new_facts:
        return []
    try:
        out = llm.chat_json(
            WRITE_DECISION_PROMPT.format(
                existing="\n".join(existing) if existing else "(none yet)",
                new_facts="\n".join(
                    f"{i}: {f.get('source','')} --{f.get('type','')}--> {f.get('target','')} :: {f.get('fact','')}"
                    for i, f in enumerate(new_facts)
                ),
            ),
            system=SYSTEM,
            max_tokens=2000,
        )
    except Exception:
        # Fail-open: ADD everything rather than dropping knowledge.
        return [{"index": i, "op": "ADD", "target_id": None, "reason": "decider unavailable"} for i in range(len(new_facts))]
    if not isinstance(out, dict):
        return []
    ops = out.get("ops") or []
    res = {}
    for o in ops:
        if isinstance(o, dict):
            idx = o.get("index")
            if isinstance(idx, int):
                res[idx] = o
    return [res.get(i, {"index": i, "op": "ADD", "target_id": None, "reason": "default add"}) for i in range(len(new_facts))]


SWEEP_PROMPT = """Review these ACTIVE facts from a memory graph and find contradictions. Two facts contradict when they cannot both be true at the same time (e.g. "user's name is Alex" vs "user's name is Sam", "X is a website" vs "X is a mobile app", "lives in Delhi" vs "lives in Mumbai").

When two facts contradict, the one with the LATER fact id is the more recent statement and is authoritative — invalidate the older one.

FACTS (id | fact):
{facts}

Respond with JSON: {{"invalidate": [<older fact ids that are contradicted by a newer fact>]}}
If there are no contradictions, return {{"invalidate": []}}"""


def sweep_contradictions(active_facts: list) -> list:
    """Return ids of older facts contradicted by newer ones (LLM-reviewed)."""
    if len(active_facts) < 2:
        return []
    try:
        out = llm.chat_json(
            SWEEP_PROMPT.format(
                facts="\n".join(f"{f['id']} | {f['text']}" for f in active_facts[:80])
            ),
            system=SYSTEM,
            max_tokens=800,
        )
    except Exception:
        return []
    if not isinstance(out, dict):
        return []
    ids = out.get("invalidate") or []
    return [int(i) for i in ids if isinstance(i, (int, float, str)) and str(i).isdigit()]