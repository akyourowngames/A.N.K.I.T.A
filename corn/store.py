import json
from pathlib import Path
from typing import Any, Dict


def _default_store() -> Dict[str, Any]:
    return {"version": 1, "jobs": []}


def load_store(path: Path) -> Dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _default_store()
    data = json.loads(raw)
    if not isinstance(data, dict):
        return _default_store()
    jobs = data.get("jobs")
    return {
        "version": 1,
        "jobs": jobs if isinstance(jobs, list) else [],
    }


def save_store(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    tmp.replace(path)

