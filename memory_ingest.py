from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from memory_conflicts import apply_conflicts, is_secret_like
from memory_graph import stable_id, utc_now
from memory_system import MemoryConfig, ensure_memory_workspace, is_relative_to, memory_files


MEMORY_TYPES = {
    "profile",
    "preference",
    "project",
    "task",
    "fact",
    "event",
    "decision",
    "constraint",
    "relationship",
    "skill",
}


@dataclass(frozen=True)
class SourceFact:
    text: str
    fact_type: str
    source_path: str
    source_line: int
    section: str
    created_at: str
    valid_from: str
    importance: float
    confidence: float


def build_memory_graph(memory_config: MemoryConfig, include_transcripts: bool = False) -> dict[str, Any]:
    ensure_memory_workspace(memory_config)
    source_facts = collect_source_facts(memory_config, include_transcripts=include_transcripts)
    raw_entities: list[dict[str, Any]] = []
    raw_facts: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for source_fact in source_facts:
        if is_secret_like(source_fact.text):
            continue
        entity_refs = extract_entities(source_fact)
        raw_entities.extend(entity_refs)
        fact_entities = [entity_id_for_ref(ref) for ref in entity_refs]
        fact = fact_from_source(source_fact, fact_entities)
        raw_facts.append(fact)
        edges.extend(edges_for_fact(fact, entity_refs))

    entities, entity_conflicts, alias_map = resolve_entities(raw_entities)
    facts = remap_fact_entities(raw_facts, alias_map)
    edges = remap_edges(edges, alias_map)
    facts, edges, fact_conflicts = apply_conflicts(facts, edges)
    episodes = collect_episodes(memory_config, include_transcripts=include_transcripts)
    return {
        "entities": entities,
        "facts": dedupe_by_id(facts),
        "edges": dedupe_by_id(edges),
        "episodes": episodes,
        "conflicts": entity_conflicts + fact_conflicts,
        "source_files": [path.relative_to(memory_config.root).as_posix() for path in source_paths(memory_config, include_transcripts)],
    }


def source_paths(memory_config: MemoryConfig, include_transcripts: bool) -> list[Path]:
    ensure_memory_workspace(memory_config)
    result: list[Path] = []
    transcript_root = memory_config.root / "transcripts"
    for path in memory_files(memory_config.root, include_transcripts=include_transcripts):
        if not is_memory_source_path(path, memory_config.root, transcript_root, include_transcripts):
            continue
        result.append(path)
    return result


def is_memory_source_path(path: Path, root: Path, transcript_root: Path, include_transcripts: bool) -> bool:
    if path.name == ".gitkeep":
        return False
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    parts = list(relative.parts)
    if not parts:
        return False
    if parts[0] in {"graph", "vector"}:
        return False
    if is_relative_to(path, transcript_root) and not include_transcripts:
        return False
    return path.suffix.casefold() in {".txt", ".md"}


def collect_source_facts(memory_config: MemoryConfig, include_transcripts: bool = False) -> list[SourceFact]:
    facts: list[SourceFact] = []
    for path in source_paths(memory_config, include_transcripts):
        facts.extend(source_facts_from_file(path, memory_config.root))
    return facts


def source_facts_from_file(path: Path, root: Path) -> list[SourceFact]:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    relative = path.relative_to(root).as_posix()
    section = ""
    timestamp = file_timestamp(path)
    facts: list[SourceFact] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        parsed_time = bracket_timestamp(stripped)
        if parsed_time:
            timestamp = parsed_time
            continue
        next_section = section_heading(stripped)
        if next_section:
            section = next_section
            continue
        if is_wiki_metadata(stripped):
            continue
        fact_text = clean_fact_line(stripped)
        if not fact_text or not looks_like_memory_fact(fact_text):
            continue
        prefixed_type, clean_text = typed_fact_prefix(fact_text)
        fact_text = clean_text
        fact_type = prefixed_type or fact_type_from_context(relative, section, fact_text)
        facts.append(
            SourceFact(
                text=fact_text,
                fact_type=fact_type,
                source_path=relative,
                source_line=line_number,
                section=section,
                created_at=timestamp,
                valid_from=timestamp,
                importance=importance_for_source(relative, fact_type),
                confidence=confidence_for_source(relative),
            )
        )
    return facts


def file_timestamp(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    except OSError:
        return utc_now()


def bracket_timestamp(text: str) -> str:
    if not (text.startswith("[") and text.endswith("]")):
        return ""
    value = text[1:-1].strip()
    try:
        return datetime.fromisoformat(value).astimezone().isoformat(timespec="seconds")
    except ValueError:
        return ""


def section_heading(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("#"):
        return stripped.lstrip("#").strip()
    if stripped.endswith(":") and len(stripped) <= 80:
        title = stripped[:-1].strip()
        if title and not title.startswith("-"):
            return title
    return ""


def is_wiki_metadata(text: str) -> bool:
    for field in ("Title:", "Updated:", "Source:", "Confidence:"):
        if text.startswith(field):
            return True
    return False


def clean_fact_line(text: str) -> str:
    line = text.strip()
    changed = True
    while changed:
        changed = False
        for marker in ("- ", "* "):
            if line.startswith(marker):
                line = line[len(marker) :].strip()
                changed = True
        numbered = strip_numbered_prefix(line)
        if numbered != line:
            line = numbered
            changed = True
        if line.startswith("[ ] ") or line.startswith("[x] ") or line.startswith("[X] "):
            line = line[4:].strip()
            changed = True
    return line.strip()


def strip_numbered_prefix(text: str) -> str:
    index = 0
    while index < len(text) and text[index].isdigit():
        index += 1
    if index == 0 or index + 1 >= len(text):
        return text
    if text[index] in {".", ")"} and text[index + 1].isspace():
        return text[index + 2 :].strip()
    return text


def looks_like_memory_fact(text: str) -> bool:
    if len(text.strip()) < 4:
        return False
    if text.endswith(":"):
        return False
    if " " not in text and ":" not in text:
        return False
    return True


def fact_type_from_context(relative_path: str, section: str, text: str) -> str:
    path_parts = set(part.casefold() for part in relative_path.replace("\\", "/").split("/"))
    clean_section = section.casefold()
    clean_text = text.casefold()
    for memory_type in MEMORY_TYPES:
        plural = memory_type + "s"
        if memory_type in clean_section or plural in clean_section:
            return memory_type
    if "projects" in path_parts:
        return "project"
    if "transcripts" in path_parts:
        return "event"
    if relative_path.casefold() == "user.txt":
        if "name:" in clean_text or "style:" in clean_text:
            return "profile"
        return "preference" if clean_section else "profile"
    if relative_path.casefold() == "extracted.txt":
        return "fact"
    return "fact"


def typed_fact_prefix(text: str) -> tuple[str, str]:
    clean = text.strip()
    if not clean.startswith("["):
        return "", clean
    end = clean.find("]")
    if end <= 1:
        return "", clean
    candidate = clean[1:end].strip().casefold()
    if candidate not in MEMORY_TYPES:
        return "", clean
    return candidate, clean[end + 1 :].strip()


def importance_for_source(relative_path: str, fact_type: str) -> float:
    clean = relative_path.casefold()
    if clean == "user.txt":
        return 0.95
    if clean.startswith("wiki/"):
        return 0.82
    if fact_type in {"constraint", "decision"}:
        return 0.86
    if clean == "extracted.txt":
        return 0.72
    if clean.startswith("transcripts/"):
        return 0.45
    return 0.65


def confidence_for_source(relative_path: str) -> float:
    clean = relative_path.casefold()
    if clean == "user.txt":
        return 0.95
    if clean.startswith("wiki/"):
        return 0.82
    if clean == "extracted.txt":
        return 0.72
    if clean.startswith("transcripts/"):
        return 0.55
    return 0.65


def extract_entities(source_fact: SourceFact) -> list[dict[str, Any]]:
    names: list[str] = []
    if source_fact.source_path.casefold() == "user.txt":
        names.append(user_entity_name())
    project_name = project_name_from_path(source_fact.source_path)
    if project_name:
        names.append(project_name)
    names.extend(structured_entity_names(source_fact.text))
    for relation in structured_relation_triples(source_fact.text):
        names.append(relation["source"])
        names.append(relation["target"])
    names.extend(quoted_phrases(source_fact.text))
    names.extend(dotted_acronyms(source_fact.text))
    names.extend(titlecase_phrases(source_fact.text))
    names.extend(file_like_tokens(source_fact.text))
    entities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in names:
        clean_name = clean_entity_name(name)
        if not clean_name:
            continue
        key = normalize_entity_key(clean_name)
        if not key or key in seen:
            continue
        seen.add(key)
        entities.append(
            {
                "id": stable_id("entity", key),
                "canonical_name": clean_name,
                "aliases": [clean_name],
                "type": entity_type(clean_name, source_fact),
                "summary": entity_summary(clean_name, source_fact),
                "confidence": source_fact.confidence,
                "source_paths": [source_fact.source_path],
                "created_at": source_fact.created_at,
                "updated_at": utc_now(),
                "normalized_key": key,
            }
        )
    return entities


def user_entity_name() -> str:
    for env_name in ("USER_NAME", "JARVIS_USER_NAME"):
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    return "User"


def project_name_from_path(relative_path: str) -> str:
    parts = relative_path.replace("\\", "/").split("/")
    if len(parts) >= 4 and parts[0] == "wiki" and parts[1] == "pages" and parts[2] == "projects":
        return slug_to_name(Path(parts[-1]).stem)
    return ""


def slug_to_name(value: str) -> str:
    return " ".join(part for part in value.replace("_", "-").split("-") if part).strip()


def quoted_phrases(text: str) -> list[str]:
    phrases: list[str] = []
    active_quote = ""
    current: list[str] = []
    quote_chars = {'"', "'", "`"}
    for character in text:
        if active_quote:
            if character == active_quote:
                phrase = "".join(current).strip()
                if phrase:
                    phrases.append(phrase)
                current = []
                active_quote = ""
            else:
                current.append(character)
            continue
        if character in quote_chars:
            active_quote = character
    return phrases


def dotted_acronyms(text: str) -> list[str]:
    result: list[str] = []
    for token in text.replace("/", " ").replace("\\", " ").split():
        clean = token.strip(".,;:()[]{}")
        letters = [character for character in clean if character.isalpha()]
        dots = clean.count(".")
        if len(letters) >= 3 and dots >= 2 and all(character.isupper() for character in letters):
            result.append(clean)
    return result


def titlecase_phrases(text: str) -> list[str]:
    tokens = word_tokens(text)
    phrases: list[str] = []
    current: list[str] = []
    for token in tokens:
        if is_title_entity_token(token):
            current.append(token)
            continue
        if current:
            phrases.extend(flush_title_phrase(current))
            current = []
    if current:
        phrases.extend(flush_title_phrase(current))
    return phrases


def flush_title_phrase(tokens: list[str]) -> list[str]:
    if len(tokens) >= 2:
        return [" ".join(tokens)]
    token = tokens[0]
    if token.isupper() and len(token) > 2:
        return [token]
    return []


def word_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    for character in text:
        if character.isalnum() or character in {".", "_", "-"}:
            current.append(character)
            continue
        if current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def is_title_entity_token(token: str) -> bool:
    letters = [character for character in token if character.isalpha()]
    if not letters:
        return False
    if all(character.isupper() for character in letters) and len(letters) > 1:
        return True
    return token[0].isupper() and any(character.islower() for character in token[1:])


def file_like_tokens(text: str) -> list[str]:
    result: list[str] = []
    for token in word_tokens(text):
        clean = token.strip(".,;:()[]{}")
        suffix = Path(clean).suffix.casefold()
        if suffix in {".py", ".txt", ".md", ".json", ".tsx", ".ts", ".sqlite", ".db"}:
            result.append(clean)
    return result


def clean_entity_name(name: str) -> str:
    value = " ".join(name.strip().split())
    return value.strip(".,;:()[]{}")


def normalize_entity_key(name: str) -> str:
    parts = []
    previous_space = False
    for character in name.casefold().strip():
        if character.isspace() or character in {"_", "-"}:
            if not previous_space:
                parts.append(" ")
                previous_space = True
            continue
        if character.isalnum() or character == ".":
            parts.append(character)
            previous_space = False
    return "".join(parts).strip()


def entity_type(name: str, source_fact: SourceFact) -> str:
    clean = name.casefold()
    if clean == user_entity_name().casefold() or clean == "user":
        return "person"
    if source_fact.fact_type == "project" or project_name_from_path(source_fact.source_path):
        return "project"
    if source_fact.fact_type in {"preference", "goal", "constraint"}:
        return source_fact.fact_type
    if Path(name).suffix:
        return "file"
    if clean.endswith("agent"):
        return "agent"
    if source_fact.fact_type == "decision":
        return "decision"
    return "topic"


def entity_summary(name: str, source_fact: SourceFact) -> str:
    return f"{name} appears in {source_fact.source_path}:{source_fact.source_line}."


def entity_id_for_ref(entity: dict[str, Any]) -> str:
    return str(entity["id"])


def fact_from_source(source_fact: SourceFact, entity_ids: list[str]) -> dict[str, Any]:
    subject_ids = entity_ids[:1]
    object_ids = entity_ids[1:]
    return {
        "id": stable_id("fact", source_fact.source_path, source_fact.source_line, source_fact.text),
        "text": source_fact.text,
        "type": source_fact.fact_type,
        "subject_entity_ids": subject_ids,
        "object_entity_ids": object_ids,
        "source_path": source_fact.source_path,
        "source_line": source_fact.source_line,
        "source_span": {"start_line": source_fact.source_line, "end_line": source_fact.source_line},
        "confidence": source_fact.confidence,
        "importance": source_fact.importance,
        "created_at": source_fact.created_at,
        "updated_at": utc_now(),
        "valid_from": source_fact.valid_from,
        "valid_to": None,
        "supersedes_fact_id": None,
        "contradicted_by": [],
    }


def edges_for_fact(fact: dict[str, Any], entity_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    fact_id = str(fact["id"])
    source_path = str(fact.get("source_path", ""))
    now = utc_now()
    for entity in entity_refs:
        entity_id = entity_id_for_ref(entity)
        edges.append(
            {
                "id": stable_id("edge", entity_id, "mentioned_in", fact_id),
                "source_id": entity_id,
                "target_id": fact_id,
                "relation_type": "mentioned_in",
                "confidence": fact.get("confidence", 0.7),
                "evidence_fact_id": fact_id,
                "source_path": source_path,
                "created_at": now,
                "valid_from": fact.get("valid_from"),
                "valid_to": None,
            }
        )
    for index, left in enumerate(entity_refs):
        for right in entity_refs[index + 1 :]:
            left_id = entity_id_for_ref(left)
            right_id = entity_id_for_ref(right)
            edges.append(
                {
                    "id": stable_id("edge", left_id, "mentioned_with", right_id, fact_id),
                    "source_id": left_id,
                    "target_id": right_id,
                    "relation_type": "mentioned_with",
                    "confidence": fact.get("confidence", 0.7),
                    "evidence_fact_id": fact_id,
                    "source_path": source_path,
                    "created_at": now,
                    "valid_from": fact.get("valid_from"),
                    "valid_to": None,
                }
            )
    edges.extend(explicit_relation_edges(fact, entity_refs))
    return edges


def structured_entity_names(text: str) -> list[str]:
    names: list[str] = []
    for part in structured_parts(text):
        label, value = split_label_value(part)
        if label.casefold() != "entities":
            continue
        for raw in value.split(","):
            clean = raw.strip()
            if clean:
                names.append(clean)
    return names


def structured_relation_triples(text: str) -> list[dict[str, str]]:
    triples: list[dict[str, str]] = []
    for part in structured_parts(text):
        label, value = split_label_value(part)
        if label.casefold() != "relations":
            continue
        for raw_relation in value.split(";"):
            pieces = [piece.strip() for piece in raw_relation.split("->")]
            if len(pieces) != 3:
                continue
            source, relation, target = pieces
            if source and relation and target:
                triples.append({"source": source, "relation": relation, "target": target})
    return triples


def structured_parts(text: str) -> list[str]:
    return [part.strip() for part in text.split("|") if part.strip()]


def split_label_value(text: str) -> tuple[str, str]:
    index = text.find(":")
    if index < 0:
        return "", text
    return text[:index].strip(), text[index + 1 :].strip()


def explicit_relation_edges(fact: dict[str, Any], entity_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    name_to_id = {normalize_entity_key(str(ref.get("canonical_name", ""))): str(ref.get("id")) for ref in entity_refs}
    edges: list[dict[str, Any]] = []
    fact_id = str(fact["id"])
    for relation in structured_relation_triples(str(fact.get("text", ""))):
        source_id = name_to_id.get(normalize_entity_key(relation["source"]))
        target_id = name_to_id.get(normalize_entity_key(relation["target"]))
        if not source_id or not target_id:
            continue
        relation_type = safe_relation_type(relation["relation"])
        edges.append(
            {
                "id": stable_id("edge", source_id, relation_type, target_id, fact_id),
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": relation_type,
                "confidence": fact.get("confidence", 0.7),
                "evidence_fact_id": fact_id,
                "source_path": fact.get("source_path", ""),
                "created_at": utc_now(),
                "valid_from": fact.get("valid_from"),
                "valid_to": None,
            }
        )
    return edges


def safe_relation_type(value: str) -> str:
    chars: list[str] = []
    previous = False
    for character in value.casefold().strip():
        if character.isalnum():
            chars.append(character)
            previous = False
            continue
        if not previous:
            chars.append("_")
            previous = True
    clean = "".join(chars).strip("_")
    return clean or "related_to"


def resolve_entities(raw_entities: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    by_key: dict[str, dict[str, Any]] = {}
    alias_map: dict[str, str] = {}
    for entity in raw_entities:
        key = str(entity.get("normalized_key", ""))
        if not key:
            continue
        current = by_key.get(key)
        if current is None:
            by_key[key] = dict(entity)
            alias_map[str(entity["id"])] = str(entity["id"])
            continue
        current["aliases"] = sorted(set(current.get("aliases", []) + entity.get("aliases", [])), key=str.casefold)
        current["source_paths"] = sorted(set(current.get("source_paths", []) + entity.get("source_paths", [])))
        current["confidence"] = max(float(current.get("confidence", 0.0)), float(entity.get("confidence", 0.0)))
        current["updated_at"] = utc_now()
        alias_map[str(entity["id"])] = str(current["id"])
    conflicts = unresolved_entity_conflicts(list(by_key.values()))
    return sorted(by_key.values(), key=lambda item: str(item.get("canonical_name", "")).casefold()), conflicts, alias_map


def unresolved_entity_conflicts(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for index, left in enumerate(entities):
        for right in entities[index + 1 :]:
            left_name = str(left.get("canonical_name", ""))
            right_name = str(right.get("canonical_name", ""))
            ratio = SequenceMatcher(None, normalize_entity_key(left_name), normalize_entity_key(right_name)).ratio()
            if ratio < 0.88:
                continue
            conflicts.append(
                {
                    "id": stable_id("entity_conflict", left.get("id"), right.get("id")),
                    "type": "possible_same_as",
                    "left_entity_id": left.get("id"),
                    "right_entity_id": right.get("id"),
                    "left_name": left_name,
                    "right_name": right_name,
                    "score": round(ratio, 4),
                    "reason": "Names are similar but not merged without stronger source evidence.",
                    "created_at": utc_now(),
                }
            )
    return conflicts


def remap_fact_entities(facts: list[dict[str, Any]], alias_map: dict[str, str]) -> list[dict[str, Any]]:
    for fact in facts:
        fact["subject_entity_ids"] = remap_ids(fact.get("subject_entity_ids", []), alias_map)
        fact["object_entity_ids"] = remap_ids(fact.get("object_entity_ids", []), alias_map)
    return facts


def remap_edges(edges: list[dict[str, Any]], alias_map: dict[str, str]) -> list[dict[str, Any]]:
    for edge in edges:
        edge["source_id"] = alias_map.get(str(edge.get("source_id")), str(edge.get("source_id")))
        edge["target_id"] = alias_map.get(str(edge.get("target_id")), str(edge.get("target_id")))
        edge["id"] = stable_id(
            "edge",
            edge.get("source_id"),
            edge.get("relation_type"),
            edge.get("target_id"),
            edge.get("evidence_fact_id"),
        )
    return edges


def remap_ids(values: list[Any], alias_map: dict[str, str]) -> list[str]:
    result: list[str] = []
    for value in values:
        clean = alias_map.get(str(value), str(value))
        if clean not in result:
            result.append(clean)
    return result


def dedupe_by_id(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        item_id = str(item.get("id", ""))
        if item_id:
            by_id[item_id] = item
    return list(by_id.values())


def collect_episodes(memory_config: MemoryConfig, include_transcripts: bool = False) -> list[dict[str, Any]]:
    if not include_transcripts:
        return []
    transcript_root = memory_config.root / "transcripts"
    if not transcript_root.exists():
        return []
    episodes: list[dict[str, Any]] = []
    for path in sorted(transcript_root.glob("*.txt"), key=lambda item: item.name):
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        relative = path.relative_to(memory_config.root).as_posix()
        for block in transcript_blocks(text):
            timestamp = block.get("timestamp") or file_timestamp(path)
            user = block.get("user", "")
            assistant = block.get("assistant", "")
            if not user and not assistant:
                continue
            episodes.append(
                {
                    "id": stable_id("episode", relative, timestamp, user[:120], assistant[:120]),
                    "session_day": path.stem,
                    "user_summary": compact_summary(user),
                    "assistant_summary": compact_summary(assistant),
                    "extracted_decisions": [],
                    "extracted_tasks": [],
                    "linked_entity_ids": [],
                    "source_transcript_path": relative,
                    "timestamp": timestamp,
                }
            )
    return episodes


def transcript_blocks(text: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    active_role = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            if current:
                blocks.append(current)
            current = {"timestamp": line[3:].strip()}
            active_role = ""
            continue
        if line.startswith("User:"):
            active_role = "user"
            current[active_role] = line[5:].strip()
            continue
        if line.startswith("Jarvis:"):
            active_role = "assistant"
            current[active_role] = line[7:].strip()
            continue
        if active_role and line:
            current[active_role] = (current.get(active_role, "") + "\n" + line).strip()
    if current:
        blocks.append(current)
    return blocks


def compact_summary(text: str, limit: int = 220) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: max(20, limit - 3)].rstrip() + "..."
