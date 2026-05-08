from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .registry import ToolInputError, optional_text, require_text


def skill_workshop(params: dict[str, Any]) -> dict[str, Any]:
    action = optional_text(params, "action", "status").lower()
    if action == "status":
        return status()
    if action == "list_pending":
        return list_pending()
    if action == "suggest":
        return suggest(params)
    if action == "apply":
        return apply_pending(require_text(params, "id"))
    if action == "reject":
        return reject_pending(require_text(params, "id"))
    if action == "read":
        return read_skill(require_text(params, "skill_name"))
    raise ToolInputError(f"unsupported skill workshop action: {action}")


def status() -> dict[str, Any]:
    pending = pending_files()
    skills = skill_files()
    return {
        "skills_root": str(skills_root()),
        "pending_count": len(pending),
        "skill_count": len(skills),
        "summary": f"Skill workshop has {len(skills)} skills and {len(pending)} pending proposals.",
    }


def list_pending() -> dict[str, Any]:
    proposals = [read_json(path) for path in pending_files()]
    return {
        "pending": proposals,
        "summary": f"{len(proposals)} pending skill proposals.",
    }


def suggest(params: dict[str, Any]) -> dict[str, Any]:
    skill_name = require_text(params, "skill_name")
    body = require_text(params, "body")
    title = optional_text(params, "title", f"Skill update: {skill_name}")
    reason = optional_text(params, "reason", "User or assistant requested a reusable workflow.")
    apply_now = bool(params.get("apply"))
    proposal = {
        "id": proposal_id(skill_name),
        "skill_name": safe_skill_name(skill_name),
        "title": title,
        "reason": reason,
        "body": body,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    if apply_now:
        result = write_skill(proposal)
        result["proposal"] = proposal
        return result
    pending_root().mkdir(parents=True, exist_ok=True)
    path = pending_root() / f"{proposal['id']}.json"
    path.write_text(json.dumps(proposal, ensure_ascii=True, indent=2), encoding="utf-8")
    return {
        "status": "pending",
        "id": proposal["id"],
        "path": str(path),
        "summary": f"Queued skill proposal {proposal['id']} for {skill_name}.",
    }


def apply_pending(proposal_id_value: str) -> dict[str, Any]:
    path = pending_root() / f"{safe_file_id(proposal_id_value)}.json"
    if not path.is_file():
        raise ToolInputError(f"pending proposal does not exist: {proposal_id_value}")
    proposal = read_json(path)
    result = write_skill(proposal)
    archive_root().mkdir(parents=True, exist_ok=True)
    archive_path = archive_root() / path.name
    path.replace(archive_path)
    result["proposal"] = proposal
    result["archived_proposal"] = str(archive_path)
    return result


def reject_pending(proposal_id_value: str) -> dict[str, Any]:
    path = pending_root() / f"{safe_file_id(proposal_id_value)}.json"
    if not path.is_file():
        raise ToolInputError(f"pending proposal does not exist: {proposal_id_value}")
    rejected_root().mkdir(parents=True, exist_ok=True)
    target = rejected_root() / path.name
    path.replace(target)
    return {
        "status": "rejected",
        "path": str(target),
        "summary": f"Rejected skill proposal {proposal_id_value}.",
    }


def read_skill(skill_name: str) -> dict[str, Any]:
    path = skills_root() / safe_skill_name(skill_name) / "SKILL.txt"
    if not path.is_file():
        raise ToolInputError(f"skill does not exist: {skill_name}")
    content = path.read_text(encoding="utf-8-sig")
    return {
        "path": str(path),
        "content": content,
        "summary": f"Read skill {skill_name}.",
    }


def write_skill(proposal: dict[str, Any]) -> dict[str, Any]:
    skill_name = safe_skill_name(str(proposal.get("skill_name", "")))
    body = str(proposal.get("body", "")).strip()
    if not skill_name:
        raise ToolInputError("skill_name is required")
    if not body:
        raise ToolInputError("body is required")
    skill_dir = skills_root() / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.txt"
    content = "\n".join(
        [
            "---",
            f"name: {skill_name}",
            f"description: {str(proposal.get('title', skill_name)).strip()}",
            "---",
            "",
            body,
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")
    return {
        "status": "applied",
        "skill_name": skill_name,
        "path": str(path),
        "summary": f"Applied skill {skill_name} at {path}.",
    }


def skills_root() -> Path:
    configured = os.environ.get("JARVIS_SKILLS_DIR", "").strip()
    path = Path(configured).expanduser() if configured else Path("skills")
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def workshop_root() -> Path:
    path = skills_root() / "_workshop"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pending_root() -> Path:
    return workshop_root() / "pending"


def archive_root() -> Path:
    return workshop_root() / "applied"


def rejected_root() -> Path:
    return workshop_root() / "rejected"


def pending_files() -> list[Path]:
    root = pending_root()
    if not root.exists():
        return []
    return sorted((path for path in root.glob("*.json") if path.is_file()), key=lambda item: item.name)


def skill_files() -> list[Path]:
    root = skills_root()
    return sorted(
        (path for path in root.rglob("SKILL.txt") if "_workshop" not in path.parts),
        key=lambda item: str(item).lower(),
    )


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        return data
    return {}


def proposal_id(skill_name: str) -> str:
    stamp = datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
    return f"{safe_skill_name(skill_name)}-{stamp}"


def safe_file_id(value: str) -> str:
    return safe_skill_name(value)


def safe_skill_name(value: str) -> str:
    chars: list[str] = []
    previous_dash = False
    for char in value.strip().lower():
        if char.isalnum():
            chars.append(char)
            previous_dash = False
        elif char in {" ", "-", "_", "."} and not previous_dash:
            chars.append("-")
            previous_dash = True
    return "".join(chars).strip("-")
