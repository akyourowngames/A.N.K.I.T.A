from __future__ import annotations

import hashlib
import uuid
from typing import Any

from .registry import optional_text, require_text


def text_stats(params: dict[str, Any]) -> dict[str, Any]:
    text = require_text(params, "text")
    lines = text.splitlines()
    words = [word for word in text.replace("\n", " ").split(" ") if word]
    return {
        "characters": len(text),
        "characters_no_spaces": len("".join(text.split())),
        "words": len(words),
        "lines": len(lines),
    }


def hash_text(params: dict[str, Any]) -> dict[str, Any]:
    text = require_text(params, "text")
    algorithm = optional_text(params, "algorithm", "sha256").lower()
    digest = hashlib.new(algorithm)
    digest.update(text.encode("utf-8"))
    return {
        "algorithm": algorithm,
        "hash": digest.hexdigest(),
    }


def generate_uuid(params: dict[str, Any]) -> dict[str, Any]:
    return {"uuid": str(uuid.uuid4())}
