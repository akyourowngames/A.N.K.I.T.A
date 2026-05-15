from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_graph import connected_edges, list_entities, list_facts, load_entity, load_fact
from memory_ingest import normalize_entity_key


@dataclass(frozen=True)
class MemorySearchOptions:
    max_facts: int = 6
    max_hops: int = 2
    timeout_ms: int = 250
    include_sources: bool = True


def memory_brain_search(db_path: Path, query: str, options: MemorySearchOptions | None = None) -> dict[str, Any]:
    opts = options or MemorySearchOptions()
    started = time.perf_counter()
    clean_query = query.strip()
    if not clean_query or not db_path.exists():
        return empty_search(clean_query)

    facts = list_facts(db_path, limit=1200)
    entities = list_entities(db_path, limit=1200)
    keyword_matches = keyword_fact_matches(clean_query, facts)
    entity_matches = entity_matches_for_query(clean_query, entities)
    seeds = [match["entity"]["id"] for match in entity_matches[:8]]
    seeds.extend(match["fact"]["id"] for match in keyword_matches[:8])
    activation = spreading_activation(db_path, seeds, opts.max_hops, started, opts.timeout_ms)

    entity_by_id = {str(entity["id"]): entity for entity in entities}
    fact_by_id = {str(fact["id"]): fact for fact in facts}
    fact_scores: dict[str, float] = {}
    graph_paths: list[dict[str, Any]] = []

    for match in keyword_matches:
        fact_id = str(match["fact"]["id"])
        fact_scores[fact_id] = max(fact_scores.get(fact_id, 0.0), float(match["score"]))

    for node_id, value in activation["scores"].items():
        if node_id in fact_by_id:
            fact_scores[node_id] = fact_scores.get(node_id, 0.0) + value
        elif node_id in entity_by_id:
            for edge in connected_edges(db_path, node_id, limit=24):
                target = edge["target_id"] if edge["source_id"] == node_id else edge["source_id"]
                if target in fact_by_id:
                    fact_scores[target] = fact_scores.get(target, 0.0) + value * 0.6

    ranked_facts = []
    for fact_id, score in fact_scores.items():
        fact = fact_by_id.get(fact_id)
        if not fact:
            continue
        final_score = score + float(fact.get("confidence", 0.0)) * 0.25 + float(fact.get("importance", 0.0)) * 0.2
        ranked_facts.append({"score": round(final_score, 4), "fact": fact})
    ranked_facts.sort(key=lambda item: item["score"], reverse=True)
    selected_facts = ranked_facts[: opts.max_facts]

    connected_entities = []
    seen_entities: set[str] = set()
    for match in entity_matches[:8]:
        entity = match["entity"]
        entity_id = str(entity["id"])
        if entity_id not in seen_entities:
            connected_entities.append({"score": match["score"], **entity})
            seen_entities.add(entity_id)
    for item in selected_facts:
        fact = item["fact"]
        for entity_id in fact.get("subject_entity_ids", []) + fact.get("object_entity_ids", []):
            entity = entity_by_id.get(str(entity_id))
            if entity and entity["id"] not in seen_entities:
                connected_entities.append({"score": item["score"], **entity})
                seen_entities.add(entity["id"])

    for item in selected_facts:
        fact = item["fact"]
        paths = activation["paths"].get(fact["id"], [])
        if paths:
            graph_paths.append({"target_fact_id": fact["id"], "path": paths[0]})

    warnings = stale_or_conflict_warnings(selected_facts)
    return {
        "query": clean_query,
        "answer_relevant_facts": selected_facts,
        "connected_entities": connected_entities[:12],
        "source_snippets": source_snippets(selected_facts),
        "graph_path_explanations": graph_paths[:8],
        "confidence": aggregate_confidence(selected_facts),
        "warnings": warnings,
        "timed_out": elapsed_ms(started) > opts.timeout_ms,
        "elapsed_ms": elapsed_ms(started),
    }


def empty_search(query: str) -> dict[str, Any]:
    return {
        "query": query,
        "answer_relevant_facts": [],
        "connected_entities": [],
        "source_snippets": [],
        "graph_path_explanations": [],
        "confidence": 0.0,
        "warnings": [],
        "timed_out": False,
        "elapsed_ms": 0,
    }


def query_terms(text: str) -> list[str]:
    terms: list[str] = []
    current: list[str] = []
    for character in text.casefold():
        if character.isalnum() or character == ".":
            current.append(character)
            continue
        if current:
            token = "".join(current)
            if len(token) > 2:
                terms.extend(term_variants(token))
            current = []
    if current:
        token = "".join(current)
        if len(token) > 2:
            terms.extend(term_variants(token))
    return unique_ordered(terms)


def term_variants(token: str) -> list[str]:
    variants = [token]
    if len(token) > 5 and token.endswith("ing"):
        variants.append(token[:-3])
    if len(token) > 4 and token.endswith("ed"):
        variants.append(token[:-2])
    if len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "is", "us")):
        variants.append(token[:-1])
    return variants


def unique_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def keyword_fact_matches(query: str, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    terms = query_terms(query)
    query_key = " ".join(terms)
    query_weight = sum(term_weight(term) for term in terms)
    matches: list[dict[str, Any]] = []
    for fact in facts:
        text = str(fact.get("text", ""))
        search_blob = " ".join([text, str(fact.get("type", "")), str(fact.get("source_path", ""))])
        text_terms = query_terms(search_blob)
        text_key = " ".join(text_terms)
        if not text_terms:
            continue
        shared_terms = set(terms) & set(text_terms)
        score = 0.0
        if query_key and query_key in text_key:
            score += 1.1
        if terms:
            score += sum(term_weight(term) for term in shared_terms) / max(0.1, query_weight)
        if score <= 0.12:
            continue
        matches.append({"score": round(score, 4), "fact": fact})
    matches.sort(key=lambda item: item["score"], reverse=True)
    return matches


def term_weight(term: str) -> float:
    if len(term) <= 3:
        return 0.2
    if len(term) == 4:
        return 0.45
    if len(term) == 5:
        return 0.7
    return 1.0


def entity_matches_for_query(query: str, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    query_key = normalize_entity_key(query)
    terms = set(query_terms(query))
    matches: list[dict[str, Any]] = []
    for entity in entities:
        names = [str(entity.get("canonical_name", ""))]
        aliases = entity.get("aliases", [])
        if isinstance(aliases, list):
            names.extend(str(alias) for alias in aliases if isinstance(alias, str))
        best = 0.0
        for name in names:
            key = normalize_entity_key(name)
            if not key:
                continue
            if key and key in query_key:
                best = max(best, 1.0)
            name_terms = set(query_terms(name))
            if name_terms and terms:
                best = max(best, len(name_terms & terms) / max(1, len(name_terms)))
        if best >= 0.25:
            matches.append({"score": round(best, 4), "entity": entity})
    matches.sort(key=lambda item: item["score"], reverse=True)
    return matches


def spreading_activation(
    db_path: Path,
    seed_ids: list[str],
    max_hops: int,
    started: float,
    timeout_ms: int,
) -> dict[str, Any]:
    scores: dict[str, float] = {}
    paths: dict[str, list[list[dict[str, str]]]] = {}
    frontier: list[tuple[str, float, int, list[dict[str, str]]]] = []
    for seed_id in unique_ordered(seed_ids):
        frontier.append((seed_id, 1.0, 0, [{"node_id": seed_id, "relation": "seed"}]))
        scores[seed_id] = max(scores.get(seed_id, 0.0), 1.0)
    while frontier:
        if elapsed_ms(started) > timeout_ms:
            break
        node_id, score, hop, path = frontier.pop(0)
        if hop >= max_hops:
            continue
        for edge in connected_edges(db_path, node_id, limit=80):
            neighbor = edge["target_id"] if edge["source_id"] == node_id else edge["source_id"]
            next_score = score * max(0.05, float(edge.get("confidence", 0.5))) * 0.62
            if next_score <= scores.get(neighbor, 0.0):
                continue
            scores[neighbor] = next_score
            next_path = [
                *path,
                {
                    "node_id": neighbor,
                    "relation": str(edge.get("relation_type", "related_to")),
                    "edge_id": str(edge.get("id", "")),
                },
            ]
            paths.setdefault(neighbor, []).append(next_path)
            frontier.append((neighbor, next_score, hop + 1, next_path))
    return {"scores": scores, "paths": paths}


def entity_neighbors(db_path: Path, entity_id: str, max_hops: int = 1, limit: int = 50) -> dict[str, Any]:
    entity = load_entity(db_path, entity_id)
    if entity is None:
        return {"entity": None, "neighbors": [], "edges": [], "facts": []}
    activation = spreading_activation(db_path, [entity_id], max_hops, time.perf_counter(), 500)
    neighbors = []
    facts = []
    for node_id, score in sorted(activation["scores"].items(), key=lambda item: item[1], reverse=True):
        if node_id == entity_id:
            continue
        fact = load_fact(db_path, node_id)
        if fact:
            facts.append({"score": round(score, 4), **fact})
            continue
        neighbor_entity = load_entity(db_path, node_id)
        if neighbor_entity:
            neighbors.append({"score": round(score, 4), **neighbor_entity})
    return {
        "entity": entity,
        "neighbors": neighbors[:limit],
        "edges": connected_edges(db_path, entity_id, limit=limit),
        "facts": facts[:limit],
    }


def timeline(db_path: Path, limit: int = 20, fact_type: str = "") -> dict[str, Any]:
    facts = list_facts(db_path, limit=max(limit * 4, limit))
    if fact_type:
        facts = [fact for fact in facts if fact.get("type") == fact_type]
    items = []
    for fact in facts[:limit]:
        items.append(
            {
                "timestamp": fact.get("valid_from") or fact.get("created_at"),
                "type": fact.get("type"),
                "text": fact.get("text"),
                "source_path": fact.get("source_path"),
                "source_line": fact.get("source_line"),
                "fact_id": fact.get("id"),
            }
        )
    return {"count": len(items), "items": items}


def summary_for_type(db_path: Path, fact_type: str, limit: int = 12) -> dict[str, Any]:
    facts = [fact for fact in list_facts(db_path, limit=500) if fact.get("type") == fact_type]
    facts.sort(key=lambda item: (float(item.get("importance", 0.0)), float(item.get("confidence", 0.0))), reverse=True)
    return {
        "type": fact_type,
        "facts": facts[:limit],
        "summary": "\n".join(f"- {fact['text']} ({fact['source_path']})" for fact in facts[:limit]),
    }


def source_snippets(selected_facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    for item in selected_facts:
        fact = item["fact"]
        snippets.append(
            {
                "fact_id": fact.get("id"),
                "source_path": fact.get("source_path"),
                "source_line": fact.get("source_line"),
                "text": fact.get("text"),
                "score": item.get("score"),
            }
        )
    return snippets


def stale_or_conflict_warnings(selected_facts: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for item in selected_facts:
        fact = item["fact"]
        if fact.get("valid_to") or fact.get("contradicted_by"):
            warnings.append(f"Fact {fact.get('id')} may be superseded or contradicted.")
    return warnings


def aggregate_confidence(selected_facts: list[dict[str, Any]]) -> float:
    if not selected_facts:
        return 0.0
    total = 0.0
    for item in selected_facts:
        total += float(item["fact"].get("confidence", 0.0))
    return round(total / len(selected_facts), 4)


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
