from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from daemon.config import DaemonConfig
from daemon.analyzer import DaemonAnalyzer
from daemon.llm import DaemonLLM
from daemon.report import build_report
from daemon.tools import DaemonTools


class ProjectDaemon:
    def __init__(
        self,
        config: DaemonConfig,
        tools: DaemonTools | None = None,
        analyzer: DaemonAnalyzer | None = None,
    ) -> None:
        self.config = config
        self.tools = tools or DaemonTools(config.project_root)
        self.analyzer = analyzer if analyzer is not None else DaemonAnalyzer(DaemonLLM(config))
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.config.state_dir / "events.jsonl"
        self.snapshot_path = self.config.state_dir / "last_snapshot.json"

    @classmethod
    def from_root(cls, project_root: Path) -> "ProjectDaemon":
        config = DaemonConfig.from_root(project_root)
        return cls(config)

    def run_once(self) -> dict[str, Any]:
        snapshot = self.tools.snapshot()
        snapshot_hash = self._hash(snapshot)
        last = self._read_last_snapshot()
        changed = snapshot_hash != last.get("snapshot_hash")
        if self.config.run_tests:
            snapshot["validation"] = self.tools.test_summary()

        event = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "snapshot_hash": snapshot_hash,
            "changed": changed,
            "summary": self._summary(snapshot, changed),
            "snapshot": snapshot,
        }

        if changed:
            self._append_event(event)
            self._write_last_snapshot(snapshot_hash, snapshot)

        events = self.read_events()
        self.write_report(snapshot=snapshot, events=events)
        return event

    def run_forever(self) -> None:
        while True:
            self.run_once()
            time.sleep(self.config.interval_seconds)

    def read_events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events

    def write_report(self, snapshot: dict[str, Any], events: list[dict[str, Any]]) -> Path:
        self.config.report_path.parent.mkdir(parents=True, exist_ok=True)
        llm_sections = self.analyzer.analyze(snapshot, events)
        self.config.report_path.write_text(build_report(snapshot, events, llm_sections), encoding="utf-8")
        return self.config.report_path

    def _read_last_snapshot(self) -> dict[str, Any]:
        if not self.snapshot_path.exists():
            return {}
        try:
            return json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _write_last_snapshot(self, snapshot_hash: str, snapshot: dict[str, Any]) -> None:
        self.snapshot_path.write_text(
            json.dumps({"snapshot_hash": snapshot_hash, "snapshot": snapshot}, indent=2),
            encoding="utf-8",
        )

    def _append_event(self, event: dict[str, Any]) -> None:
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    @staticmethod
    def _hash(snapshot: dict[str, Any]) -> str:
        stable = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()

    @staticmethod
    def _summary(snapshot: dict[str, Any], changed: bool) -> str:
        files = snapshot.get("changed_files") or []
        if not changed:
            return "No meaningful project changes detected."
        if files:
            return f"Project changed with {len(files)} changed file(s)."
        return "Project metadata changed."
