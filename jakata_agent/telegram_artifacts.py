from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jakata_agent.config import Settings
from jakata_agent.tasks.models import TaskRecord, utcnow_iso
from jakata_agent.tasks.store import TaskStore


SECRET_KEY_RE = re.compile(r"(api[_-]?key|token|password|secret|authorization|bot[_-]?token)", re.IGNORECASE)


class ArtifactError(RuntimeError):
    pass


@dataclass(slots=True)
class ArtifactRecord:
    id: str
    kind: str
    title: str
    path: str
    size_bytes: int
    mime_type: str
    source: str
    created_at: str
    extra: dict[str, Any]


class TelegramArtifactService:
    def __init__(self, settings: Settings, task_store: TaskStore | None = None) -> None:
        self.settings = settings
        self.task_store = task_store
        self.artifact_dir = settings.telegram_artifact_dir
        self.upload_dir = settings.telegram_upload_dir
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.artifact_dir / "artifacts.json"

    @property
    def max_upload_bytes(self) -> int:
        return max(1, int(self.settings.telegram_max_upload_mb)) * 1024 * 1024

    def resolve_path(self, raw_path: str) -> Path:
        cleaned = raw_path.strip().strip("\"'")
        if not cleaned:
            raise ArtifactError("Path is required.")
        path = Path(cleaned).expanduser()
        if not path.is_absolute():
            path = self.settings.workspace_dir / path
        return path.resolve()

    def is_safe_path(self, path: str | Path) -> bool:
        target = Path(path).resolve()
        for root in self.safe_roots():
            try:
                common = os.path.commonpath([os.path.normcase(str(target)), os.path.normcase(str(root))])
            except ValueError:
                continue
            if common == os.path.normcase(str(root)):
                return True
        return False

    def safe_roots(self) -> list[Path]:
        roots = list(self.settings.telegram_safe_roots)
        roots.extend([self.artifact_dir, self.upload_dir, self.settings.image_output_dir])
        seen: set[str] = set()
        unique: list[Path] = []
        for root in roots:
            resolved = Path(root).expanduser().resolve()
            key = os.path.normcase(str(resolved))
            if key in seen:
                continue
            seen.add(key)
            unique.append(resolved)
        return unique

    def list_directory(self, raw_path: str, limit: int = 200) -> str:
        directory = self.resolve_path(raw_path)
        if not directory.exists():
            raise ArtifactError(f"Path not found: {directory}")
        if not directory.is_dir():
            raise ArtifactError(f"Not a directory: {directory}")
        entries = []
        try:
            children = sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        except PermissionError as exc:
            raise ArtifactError(f"Permission denied: {directory}") from exc
        for item in children[:limit]:
            try:
                stat = item.stat()
                size = "-" if item.is_dir() else self._human_size(stat.st_size)
                kind = "dir " if item.is_dir() else "file"
                entries.append(f"{kind:4} {size:>10} {item.name}")
            except OSError:
                continue
        suffix = "" if len(children) <= limit else f"\n... {len(children) - limit} more item(s)"
        return f"{directory}\n" + ("\n".join(entries) if entries else "No items.") + suffix

    def find_files(self, query: str, limit: int = 50) -> list[str]:
        needle = query.strip().lower()
        if not needle:
            raise ArtifactError("Usage: /findfile <query>")
        matches: list[str] = []
        for root in self.safe_roots():
            if not root.exists() or not root.is_dir():
                continue
            try:
                iterator = root.rglob("*")
                for item in iterator:
                    if len(matches) >= limit:
                        return matches
                    try:
                        if needle in item.name.lower():
                            matches.append(str(item))
                    except OSError:
                        continue
            except OSError:
                continue
        return matches

    def register_file(
        self,
        path: str | Path,
        *,
        kind: str,
        title: str | None = None,
        source: str = "pc",
        extra: dict[str, Any] | None = None,
    ) -> ArtifactRecord:
        target = Path(path).resolve()
        if not target.exists() or not target.is_file():
            raise ArtifactError(f"File not found: {target}")
        stat = target.stat()
        record = ArtifactRecord(
            id=self._new_id(),
            kind=kind,
            title=title or target.name,
            path=str(target),
            size_bytes=stat.st_size,
            mime_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream",
            source=source,
            created_at=utcnow_iso(),
            extra=extra or {},
        )
        self._upsert(record)
        return record

    def create_text_artifact(self, title: str, content: str, *, suffix: str = ".md", kind: str = "report") -> ArtifactRecord:
        filename = f"{self._slug(title)}-{self._new_id()[:8]}{suffix}"
        path = self.artifact_dir / filename
        path.write_text(self.redact_text(content), encoding="utf-8")
        return self.register_file(path, kind=kind, title=title, source="generated")

    def create_json_artifact(self, title: str, payload: dict[str, Any], *, kind: str = "json") -> ArtifactRecord:
        filename = f"{self._slug(title)}-{self._new_id()[:8]}.json"
        path = self.artifact_dir / filename
        cleaned = self.redact_payload(payload)
        path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return self.register_file(path, kind=kind, title=title, source="generated")

    def create_zip_artifact(self, title: str, files: dict[str, str], *, kind: str = "zip") -> ArtifactRecord:
        filename = f"{self._slug(title)}-{self._new_id()[:8]}.zip"
        path = self.artifact_dir / filename
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for arcname, content in files.items():
                archive.writestr(arcname, self.redact_text(content))
        if path.stat().st_size > self.max_upload_bytes:
            path.unlink(missing_ok=True)
            return self.create_text_artifact(
                f"{title} export too large",
                f"Export was larger than {self.settings.telegram_max_upload_mb} MB and was not sent.",
                suffix=".txt",
                kind="manifest",
            )
        return self.register_file(path, kind=kind, title=title, source="generated")

    def zip_directory(self, raw_path: str) -> ArtifactRecord:
        directory = self.resolve_path(raw_path)
        if not directory.exists():
            raise ArtifactError(f"Path not found: {directory}")
        if not directory.is_dir():
            raise ArtifactError(f"Not a directory: {directory}")

        files = self._collect_directory_files(directory)
        total_size = sum(size for _, size in files)
        if total_size > self.max_upload_bytes:
            return self._directory_manifest(directory, files, reason="directory is larger than Telegram upload limit")

        zip_path = self.artifact_dir / f"{self._slug(directory.name or 'directory')}-{self._new_id()[:8]}.zip"
        try:
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path, _ in files:
                    archive.write(path, path.relative_to(directory))
        except OSError as exc:
            zip_path.unlink(missing_ok=True)
            raise ArtifactError(f"Could not zip directory: {exc}") from exc

        if zip_path.stat().st_size > self.max_upload_bytes:
            zip_path.unlink(missing_ok=True)
            return self._directory_manifest(directory, files, reason="zip is larger than Telegram upload limit")
        return self.register_file(zip_path, kind="directory_zip", title=f"{directory.name}.zip", source="generated")

    def oversize_manifest(self, path: str | Path) -> ArtifactRecord:
        target = Path(path).resolve()
        size = target.stat().st_size if target.exists() else 0
        content = "\n".join(
            [
                f"Path: {target}",
                f"Size: {self._human_size(size)}",
                f"Limit: {self.settings.telegram_max_upload_mb} MB",
                "Result: file was not sent because it is larger than the Telegram upload limit.",
            ]
        )
        return self.create_text_artifact(f"{target.name} upload manifest", content, suffix=".txt", kind="manifest")

    def list_artifacts(self, limit: int = 20) -> list[ArtifactRecord]:
        records = [self._dict_to_record(item) for item in self._load_index()]
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records[:limit]

    def get_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        token = artifact_id.strip()
        if not token:
            return None
        for item in self._load_index():
            if str(item.get("id", "")) == token:
                return self._dict_to_record(item)
        return None

    def record_upload(self, path: str | Path, *, telegram_user_id: int, kind: str = "upload") -> ArtifactRecord:
        return self.register_file(
            path,
            kind=kind,
            title=Path(path).name,
            source="telegram_upload",
            extra={"telegram_user_id": telegram_user_id},
        )

    def save_upload_bytes(self, *, telegram_user_id: int, filename: str, data: bytes, kind: str = "upload") -> ArtifactRecord:
        target = self.prepare_upload_path(telegram_user_id=telegram_user_id, filename=filename)
        target.write_bytes(data)
        return self.record_upload(target, telegram_user_id=telegram_user_id, kind=kind)

    def prepare_upload_path(self, *, telegram_user_id: int, filename: str) -> Path:
        user_dir = self.upload_dir / str(telegram_user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        safe_name = self._safe_filename(filename or f"upload-{self._new_id()}")
        target = user_dir / safe_name
        if target.exists():
            target = user_dir / f"{target.stem}-{self._new_id()[:8]}{target.suffix}"
        return target

    def put_artifact(self, artifact_id: str, raw_target: str) -> Path:
        record = self.get_artifact(artifact_id)
        if record is None:
            raise ArtifactError(f"Artifact not found: {artifact_id}")
        source = Path(record.path)
        if not source.exists() or not source.is_file():
            raise ArtifactError(f"Artifact file is missing: {artifact_id}")
        target = self.resolve_path(raw_target)
        if target.exists() and target.is_dir():
            target = target / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return target

    def task_report_markdown(self, task_id: str) -> str:
        if self.task_store is None:
            raise ArtifactError("Task store is not attached.")
        task = self.task_store.get_task(task_id)
        if task is None:
            raise ArtifactError(f"Task not found: {task_id}")
        events = self.task_store.list_events(task.id, limit=500)
        lines = [
            f"# JAKATA Task Report",
            "",
            f"- Task: `{task.id}`",
            f"- Status: `{task.status}`",
            f"- Goal: {task.goal}",
            f"- Created: {task.created_at}",
            f"- Updated: {task.updated_at}",
        ]
        if task.result_summary:
            lines.append(f"- Result: {task.result_summary}")
        if task.last_error:
            lines.append(f"- Error: {task.last_error}")
        lines.extend(["", "## Final Report", "", task.final_report or "No final report is available yet."])
        if task.pending_approval:
            lines.extend(["", "## Pending Approval", "", "```json", json.dumps(self.redact_payload(task.pending_approval), indent=2), "```"])
        if events:
            lines.extend(["", "## Events"])
            for event in events:
                payload = json.dumps(self.redact_payload(event.payload), ensure_ascii=False, default=str)
                lines.append(f"- `{event.created_at}` `{event.event_type}` {payload[:700]}")
        return self.redact_text("\n".join(lines))

    def task_logs_payload(self, task_id: str) -> dict[str, Any]:
        if self.task_store is None:
            raise ArtifactError("Task store is not attached.")
        task = self.task_store.get_task(task_id)
        if task is None:
            raise ArtifactError(f"Task not found: {task_id}")
        runs = self.task_store.list_agent_runs(task.id)
        messages = self.task_store.list_agent_messages_for_task(task.id)
        events = self.task_store.list_events(task.id, limit=1000)
        return self.redact_payload(
            {
                "task": self._task_to_dict(task),
                "events": [asdict(event) for event in events],
                "agent_runs": [asdict(run) for run in runs],
                "agent_messages": [asdict(message) for message in messages],
            }
        )

    def export_task(self, task_id: str, fmt: str) -> ArtifactRecord:
        fmt = fmt.lower().strip()
        if fmt == "md":
            return self.create_text_artifact(f"task-{task_id}-report", self.task_report_markdown(task_id), suffix=".md")
        if fmt == "json":
            return self.create_json_artifact(f"task-{task_id}-export", self.task_logs_payload(task_id), kind="task_export")
        if fmt == "zip":
            markdown = self.task_report_markdown(task_id)
            logs = json.dumps(self.task_logs_payload(task_id), ensure_ascii=False, indent=2, default=str)
            return self.create_zip_artifact(
                f"task-{task_id}-export",
                {
                    "report.md": markdown,
                    "logs.json": logs,
                },
                kind="task_export_zip",
            )
        raise ArtifactError("Usage: /export <task_id> md|json|zip")

    def sendable_or_manifest(self, record: ArtifactRecord) -> ArtifactRecord:
        if record.size_bytes <= self.max_upload_bytes:
            return record
        return self.oversize_manifest(record.path)

    @staticmethod
    def redact_payload(value: Any) -> Any:
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for key, item in value.items():
                if SECRET_KEY_RE.search(str(key)):
                    cleaned[str(key)] = "[REDACTED]"
                else:
                    cleaned[str(key)] = TelegramArtifactService.redact_payload(item)
            return cleaned
        if isinstance(value, list):
            return [TelegramArtifactService.redact_payload(item) for item in value]
        if isinstance(value, str):
            return TelegramArtifactService.redact_text(value)
        return value

    @staticmethod
    def redact_text(text: str) -> str:
        patterns = [
            r"(?i)(NVIDIA_API_KEY|OPENAI_API_KEY|TAVILY_API_KEY|OPENWEATHER_API_KEY|JAKATA_TELEGRAM_BOT_TOKEN|JAKATA_TELEGRAM_ADMIN_PASSWORD)\s*=\s*[^\s]+",
            r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._\-]+",
        ]
        redacted = text
        for pattern in patterns:
            redacted = re.sub(pattern, lambda match: f"{match.group(1)}=[REDACTED]" if "=" in match.group(0) else f"{match.group(1)}[REDACTED]", redacted)
        return redacted

    def _collect_directory_files(self, directory: Path, limit: int = 5000) -> list[tuple[Path, int]]:
        files: list[tuple[Path, int]] = []
        try:
            iterator = directory.rglob("*")
            for item in iterator:
                if len(files) >= limit:
                    break
                try:
                    if item.is_file():
                        files.append((item, item.stat().st_size))
                except OSError:
                    continue
        except OSError as exc:
            raise ArtifactError(f"Could not read directory: {exc}") from exc
        return files

    def _directory_manifest(self, directory: Path, files: list[tuple[Path, int]], *, reason: str) -> ArtifactRecord:
        total = sum(size for _, size in files)
        lines = [
            f"Directory: {directory}",
            f"Reason: {reason}",
            f"Total file bytes scanned: {self._human_size(total)}",
            f"Telegram limit: {self.settings.telegram_max_upload_mb} MB",
            "",
            "Files:",
        ]
        for path, size in files[:1000]:
            try:
                label = path.relative_to(directory)
            except ValueError:
                label = path
            lines.append(f"- {label} ({self._human_size(size)})")
        if len(files) > 1000:
            lines.append(f"... {len(files) - 1000} more file(s)")
        return self.create_text_artifact(f"{directory.name} manifest", "\n".join(lines), suffix=".txt", kind="manifest")

    def _load_index(self) -> list[dict[str, Any]]:
        if not self.index_path.exists():
            return []
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return data if isinstance(data, list) else []

    def _save_index(self, records: list[dict[str, Any]]) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.index_path)

    def _upsert(self, record: ArtifactRecord) -> None:
        records = [item for item in self._load_index() if item.get("id") != record.id]
        records.append(asdict(record))
        self._save_index(records[-500:])

    @staticmethod
    def _dict_to_record(item: dict[str, Any]) -> ArtifactRecord:
        return ArtifactRecord(
            id=str(item.get("id", "")),
            kind=str(item.get("kind", "")),
            title=str(item.get("title", "")),
            path=str(item.get("path", "")),
            size_bytes=int(item.get("size_bytes", 0) or 0),
            mime_type=str(item.get("mime_type", "application/octet-stream")),
            source=str(item.get("source", "")),
            created_at=str(item.get("created_at", "")),
            extra=item.get("extra") if isinstance(item.get("extra"), dict) else {},
        )

    @staticmethod
    def _task_to_dict(task: TaskRecord) -> dict[str, Any]:
        return {name: getattr(task, name) for name in TaskRecord.__dataclass_fields__}

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex[:12]

    @staticmethod
    def _slug(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
        return cleaned[:80] or f"artifact-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    @staticmethod
    def _safe_filename(value: str) -> str:
        name = Path(value).name
        cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip()
        return cleaned or "upload.bin"

    @staticmethod
    def _human_size(size: int) -> str:
        value = float(size)
        for unit in ["B", "KB", "MB", "GB"]:
            if value < 1024 or unit == "GB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{size} B"
