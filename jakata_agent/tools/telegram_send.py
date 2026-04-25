from __future__ import annotations

import os
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jakata_agent.telegram_artifacts import ArtifactError, ArtifactRecord, TelegramArtifactService
from jakata_agent.tools.base import Tool, ToolResult


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
MAX_SCAN_FILES = 2000
MAX_SCAN_SECONDS = 5.0


class TelegramSendTool(Tool):
    name = "telegram_send"
    description = (
        "Send an existing local file, folder zip/manifest, generated image, or artifact to the current Telegram chat. "
        "Use this when the user asks to send, upload, attach, or deliver a file/image here. This does not open files on the PC."
    )
    safety = "write"
    input_schema = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Path, artifact id, or natural file/image query. Empty means latest matching artifact/file.",
            },
            "prefer": {
                "type": "string",
                "enum": ["auto", "image", "file", "directory"],
                "description": "Preferred attachment kind.",
            },
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": "Maximum attachments to prepare.",
            },
            "max_scan_files": {
                "type": "integer",
                "description": "Maximum safe-root files to inspect. Default 2000.",
            },
            "max_seconds": {
                "type": "number",
                "description": "Maximum seconds to search safe roots. Default 5.",
            },
        },
        "required": [],
        "additionalProperties": False,
    }

    def __init__(self, artifacts: TelegramArtifactService) -> None:
        self.artifacts = artifacts

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args.setdefault("target", "")
        args.setdefault("prefer", "auto")
        args.setdefault("max_results", 3)
        args.setdefault("max_scan_files", MAX_SCAN_FILES)
        args.setdefault("max_seconds", MAX_SCAN_SECONDS)
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        target = str(args.get("target", "")).strip()
        prefer = str(args.get("prefer", "auto")).strip().lower() or "auto"
        max_results = max(1, min(int(args.get("max_results", 3)), 5))
        max_scan_files = max(50, min(int(args.get("max_scan_files", MAX_SCAN_FILES)), 50_000))
        max_seconds = max(1.0, min(float(args.get("max_seconds", MAX_SCAN_SECONDS)), 30.0))
        try:
            records = self._resolve_records(target, prefer=prefer, max_results=max_results, max_scan_files=max_scan_files, max_seconds=max_seconds)
        except ArtifactError as exc:
            return ToolResult(ok=False, summary=str(exc), data={"target": target, "prefer": prefer}, error="artifact_error")
        if not records:
            return ToolResult(ok=False, summary=f"No Telegram-sendable file matched: {target or prefer}", data={"target": target, "prefer": prefer}, error="not_found")
        payload_records = [self._record_payload(record, prefer=prefer) for record in records]
        titles = ", ".join(record.title for record in records)
        return ToolResult(
            ok=True,
            summary=f"Prepared {len(records)} Telegram attachment(s): {titles}",
            data={"target": target, "prefer": prefer, "records": payload_records},
        )

    def render(self, data: dict[str, Any]) -> str:
        records = data.get("records", [])
        if not isinstance(records, list) or not records:
            return "No Telegram attachment prepared."
        titles = ", ".join(str(item.get("title", "attachment")) for item in records if isinstance(item, dict))
        return f"Prepared Telegram attachment(s): {titles}"

    def _resolve_records(self, target: str, *, prefer: str, max_results: int, max_scan_files: int, max_seconds: float) -> list[ArtifactRecord]:
        direct = self._direct_record(target, prefer=prefer)
        if direct is not None:
            return [direct]
        matches = self._rank_matches(target, prefer=prefer, max_scan_files=max_scan_files, max_seconds=max_seconds)
        return [record for _, record in matches[:max_results]]

    def _direct_record(self, target: str, *, prefer: str) -> ArtifactRecord | None:
        if not target:
            return None
        artifact = self.artifacts.get_artifact(target)
        if artifact is not None:
            return self.artifacts.sendable_or_manifest(artifact)
        try:
            path = self.artifacts.resolve_path(target)
        except ArtifactError:
            return None
        if path.exists() and path.is_file():
            record = self.artifacts.register_file(path, kind=self._kind_for_path(path, prefer), title=path.name, source="telegram_send")
            return self.artifacts.sendable_or_manifest(record)
        if path.exists() and path.is_dir():
            return self.artifacts.zip_directory(str(path))
        return None

    def _rank_matches(self, target: str, *, prefer: str, max_scan_files: int, max_seconds: float) -> list[tuple[float, ArtifactRecord]]:
        tokens = self._tokens(target)
        ranked: list[tuple[float, ArtifactRecord]] = []
        for record in self.artifacts.list_artifacts(limit=100):
            if not self._record_matches_preference(record, prefer):
                continue
            score = self._score_text(tokens, f"{record.title} {record.path} {record.kind}")
            if not tokens:
                score = 0.1
            if score > 0:
                ranked.append((score + self._mtime_score(record.path), record))
        for path in self._iter_safe_files(prefer, max_scan_files=max_scan_files, max_seconds=max_seconds):
            score = self._score_text(tokens, str(path))
            if not tokens:
                score = 0.1
            if score <= 0:
                continue
            try:
                record = self.artifacts.register_file(path, kind=self._kind_for_path(path, prefer), title=path.name, source="telegram_send")
            except ArtifactError:
                continue
            ranked.append((score + self._mtime_score(path), self.artifacts.sendable_or_manifest(record)))
        ranked.sort(key=lambda item: item[0], reverse=True)
        deduped: list[tuple[float, ArtifactRecord]] = []
        seen: set[str] = set()
        for score, record in ranked:
            key = os.path.normcase(record.path)
            if key in seen:
                continue
            seen.add(key)
            deduped.append((score, record))
        return deduped

    def _iter_safe_files(self, prefer: str, *, max_scan_files: int, max_seconds: float) -> list[Path]:
        files: list[Path] = []
        started = time.monotonic()
        scanned = 0
        for root in self.artifacts.safe_roots():
            if not root.exists() or not root.is_dir():
                continue
            try:
                for path in root.rglob("*"):
                    if time.monotonic() - started >= max_seconds or scanned >= max_scan_files:
                        files.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
                        return files[:max_scan_files]
                    if not path.is_file():
                        continue
                    scanned += 1
                    if prefer == "image" and path.suffix.lower() not in IMAGE_SUFFIXES:
                        continue
                    files.append(path)
            except OSError:
                continue
        files.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
        return files[:500]

    @staticmethod
    def _tokens(value: str) -> list[str]:
        return [token.lower() for token in re.findall(r"[A-Za-z0-9]+", value) if len(token) >= 2]

    @staticmethod
    def _score_text(tokens: list[str], value: str) -> float:
        if not tokens:
            return 0.0
        haystack = value.lower()
        return float(sum(1 for token in tokens if token in haystack))

    @staticmethod
    def _mtime_score(path: str | Path) -> float:
        try:
            return Path(path).stat().st_mtime / 1_000_000_000_000
        except OSError:
            return 0.0

    @staticmethod
    def _record_matches_preference(record: ArtifactRecord, prefer: str) -> bool:
        if prefer == "image":
            return record.mime_type.startswith("image/") or Path(record.path).suffix.lower() in IMAGE_SUFFIXES
        if prefer == "directory":
            return record.kind in {"directory_zip", "manifest"} or record.mime_type in {"application/zip", "application/x-zip-compressed"}
        return True

    @staticmethod
    def _kind_for_path(path: Path, prefer: str) -> str:
        if prefer == "image" or path.suffix.lower() in IMAGE_SUFFIXES:
            return "generated_image"
        return "pc_file"

    @staticmethod
    def _record_payload(record: ArtifactRecord, *, prefer: str) -> dict[str, Any]:
        payload = asdict(record)
        payload["as_photo"] = prefer == "image" or record.mime_type.startswith("image/")
        return payload
