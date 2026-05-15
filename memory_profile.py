from __future__ import annotations

from pathlib import Path
from typing import Any

from memory_graph import list_entities, list_facts, utc_now


PROFILE_TYPES = {"profile", "preference", "constraint", "skill", "decision"}


def write_profile_summary(db_path: Path, output_path: Path, max_items: int = 18) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    facts = profile_facts(db_path, max_items=max_items)
    lines = ["Generated Profile Summary", f"Updated: {utc_now()}", "Source: generated from TXT memory graph", ""]
    if facts:
        for fact in facts:
            lines.append(f"- [{fact.get('type')}, source: {fact.get('source_path')}] {fact.get('text')}")
    else:
        lines.append("- No profile facts indexed yet.")
    output_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return {"path": str(output_path.resolve()), "fact_count": len(facts)}


def profile_facts(db_path: Path, max_items: int = 18) -> list[dict[str, Any]]:
    facts = [fact for fact in list_facts(db_path, limit=600) if fact.get("type") in PROFILE_TYPES]
    facts.sort(key=profile_sort_key, reverse=True)
    return facts[:max_items]


def profile_sort_key(fact: dict[str, Any]) -> tuple[float, float, str]:
    return (
        float(fact.get("importance", 0.0)),
        float(fact.get("confidence", 0.0)),
        str(fact.get("valid_from") or fact.get("created_at") or ""),
    )


def read_profile_summary(path: Path, max_chars: int = 1800) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    return text[:max_chars].strip()


def project_summary(db_path: Path, project_query: str = "", limit: int = 10) -> dict[str, Any]:
    clean_query = project_query.casefold().strip()
    entities = [entity for entity in list_entities(db_path, limit=600) if entity.get("type") == "project"]
    if clean_query:
        entities = [
            entity
            for entity in entities
            if clean_query in str(entity.get("canonical_name", "")).casefold()
            or any(clean_query in str(alias).casefold() for alias in entity.get("aliases", []))
        ]
    project_ids = {str(entity.get("id")) for entity in entities}
    facts = [
        fact
        for fact in list_facts(db_path, limit=600)
        if fact.get("type") in {"project", "decision", "task", "constraint", "fact"}
        and (not project_ids or project_ids & set(str(item) for item in fact.get("subject_entity_ids", []) + fact.get("object_entity_ids", [])))
    ]
    if not facts and not clean_query:
        facts = [fact for fact in list_facts(db_path, limit=600) if fact.get("type") == "project"]
    facts.sort(key=profile_sort_key, reverse=True)
    selected = facts[:limit]
    return {
        "query": project_query,
        "entities": entities[:limit],
        "facts": selected,
        "summary": "\n".join(f"- {fact.get('text')} ({fact.get('source_path')})" for fact in selected),
    }
