from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from memory_graph import stable_id, utc_now


SECRET_MARKERS = {
    "api_key",
    "apikey",
    "password",
    "passwd",
    "secret",
    "token",
    "private_key",
    "access_key",
    "bearer",
}

NEGATION_MARKERS = {
    "not",
    "no",
    "never",
    "without",
    "dont",
    "don't",
    "cannot",
    "can't",
    "false",
    "off",
    "disabled",
    "disable",
    "avoid",
}


def is_secret_like(text: str) -> bool:
    clean = text.strip()
    if not clean:
        return False
    lowered = clean.casefold()
    compact = "".join(character for character in lowered if character.isalnum() or character == "_")
    for marker in SECRET_MARKERS:
        if marker in lowered or marker in compact:
            return True
    return contains_high_entropy_token(clean)


def contains_high_entropy_token(text: str) -> bool:
    for token in split_tokens_preserving_symbols(text):
        if len(token) < 28:
            continue
        if token.startswith("http://") or token.startswith("https://"):
            continue
        letters = sum(1 for character in token if character.isalpha())
        digits = sum(1 for character in token if character.isdigit())
        symbols = sum(1 for character in token if not character.isalnum())
        if letters > 8 and digits > 3 and symbols > 1:
            return True
    return False


def split_tokens_preserving_symbols(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    for character in text:
        if character.isspace():
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(character)
    if current:
        tokens.append("".join(current))
    return tokens


def content_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    current: list[str] = []
    for character in text.casefold():
        if character.isalnum():
            current.append(character)
            continue
        if current:
            token = "".join(current)
            if len(token) > 2:
                tokens.add(token)
            current = []
    if current:
        token = "".join(current)
        if len(token) > 2:
            tokens.add(token)
    return tokens


def negation_count(text: str) -> int:
    tokens = content_tokens(text)
    return sum(1 for marker in NEGATION_MARKERS if marker in tokens)


def contradiction_score(left: str, right: str) -> float:
    left_tokens = content_tokens(left)
    right_tokens = content_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    shared = len(left_tokens & right_tokens)
    overlap = shared / max(1, min(len(left_tokens), len(right_tokens)))
    similarity = SequenceMatcher(None, left.casefold(), right.casefold()).ratio()
    negation_flip = (negation_count(left) == 0) != (negation_count(right) == 0)
    if negation_flip and overlap >= 0.45:
        return max(0.85, overlap)
    if overlap >= 0.72 and similarity >= 0.58 and left.strip() != right.strip():
        return max(overlap, similarity)
    return 0.0


def apply_conflicts(
    facts: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    facts_by_id = {str(fact["id"]): fact for fact in facts}
    conflicts: list[dict[str, Any]] = []
    ordered = sorted(facts, key=lambda item: (str(item.get("source_path", "")), int(item.get("source_line") or 0)))
    for index, newer in enumerate(ordered):
        for older in ordered[:index]:
            if not comparable_facts(older, newer):
                continue
            score = contradiction_score(str(older.get("text", "")), str(newer.get("text", "")))
            if score <= 0:
                continue
            older_id = str(older["id"])
            newer_id = str(newer["id"])
            current_older = facts_by_id.get(older_id, older)
            current_newer = facts_by_id.get(newer_id, newer)
            current_older["valid_to"] = current_newer.get("valid_from") or current_newer.get("created_at") or utc_now()
            contradicted_by = list(current_older.get("contradicted_by", []))
            if newer_id not in contradicted_by:
                contradicted_by.append(newer_id)
            current_older["contradicted_by"] = contradicted_by
            current_newer["supersedes_fact_id"] = older_id
            conflict = {
                "id": stable_id("conflict", older_id, newer_id),
                "older_fact_id": older_id,
                "newer_fact_id": newer_id,
                "score": round(score, 4),
                "older_text": older.get("text", ""),
                "newer_text": newer.get("text", ""),
                "source_path": newer.get("source_path", ""),
                "created_at": utc_now(),
            }
            if not any(item["id"] == conflict["id"] for item in conflicts):
                conflicts.append(conflict)
            edges.extend(conflict_edges(older_id, newer_id, newer, score))
    return list(facts_by_id.values()), dedupe_edges(edges), conflicts


def comparable_facts(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("id") == right.get("id"):
        return False
    if left.get("type") != right.get("type"):
        return False
    left_subjects = set(str(item) for item in left.get("subject_entity_ids", []))
    right_subjects = set(str(item) for item in right.get("subject_entity_ids", []))
    if left_subjects and right_subjects and not (left_subjects & right_subjects):
        return False
    return True


def conflict_edges(older_id: str, newer_id: str, newer: dict[str, Any], score: float) -> list[dict[str, Any]]:
    now = utc_now()
    source_path = str(newer.get("source_path", ""))
    return [
        {
            "id": stable_id("edge", newer_id, "supersedes", older_id),
            "source_id": newer_id,
            "target_id": older_id,
            "relation_type": "supersedes",
            "confidence": score,
            "evidence_fact_id": newer_id,
            "source_path": source_path,
            "created_at": now,
            "valid_from": newer.get("valid_from") or now,
            "valid_to": None,
        },
        {
            "id": stable_id("edge", older_id, "contradicts", newer_id),
            "source_id": older_id,
            "target_id": newer_id,
            "relation_type": "contradicts",
            "confidence": score,
            "evidence_fact_id": newer_id,
            "source_path": source_path,
            "created_at": now,
            "valid_from": newer.get("valid_from") or now,
            "valid_to": None,
        },
    ]


def dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for edge in edges:
        edge_id = str(edge.get("id", ""))
        if not edge_id or edge_id in seen:
            continue
        seen.add(edge_id)
        result.append(edge)
    return result
