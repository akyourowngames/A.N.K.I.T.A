from __future__ import annotations

import re
from typing import Any


class GraphExtractor:
    def extract_from_user_message(self, user_message: str) -> list[dict[str, Any]]:
        text = " ".join(user_message.split())
        if not text:
            return []

        events: list[dict[str, Any]] = []
        patterns: list[tuple[str, re.Pattern[str], str, str]] = [
            ("project", re.compile(r"\b(?:i am|i'm|we are|we're) (?:building|making|working on) ([A-Za-z][\w\s-]{2,40})", re.IGNORECASE), "person", "works_on"),
            ("preference", re.compile(r"\bmy favorite ([\w\s]{1,20}) is ([A-Za-z][\w\s-]{1,30})", re.IGNORECASE), "person", "prefers"),
            ("goal", re.compile(r"\bi want to ([A-Za-z][\w\s-]{2,60})", re.IGNORECASE), "person", "targets"),
            ("device", re.compile(r"\bi use ([A-Za-z][\w\s.-]{1,30})", re.IGNORECASE), "person", "uses"),
        ]

        for label, pattern, source_type, edge_type in patterns:
            match = pattern.search(text)
            if not match:
                continue
            if label == "preference":
                category = match.group(1).strip()
                value = match.group(2).strip()
                events.append(
                    {
                        "source_type": source_type,
                        "source_label": "user",
                        "edge_type": edge_type,
                        "target_type": "preference",
                        "target_label": f"{category}: {value}",
                        "metadata": {"source": "chat"},
                    }
                )
                continue
            target = match.group(1).strip()
            events.append(
                {
                    "source_type": source_type,
                    "source_label": "user",
                    "edge_type": edge_type,
                    "target_type": label,
                    "target_label": target,
                    "metadata": {"source": "chat"},
                }
            )
        return events

    def extract_from_task_event(self, task_id: str, goal: str, event_type: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = [
            {
                "source_type": "task",
                "source_label": task_id,
                "edge_type": "targets",
                "target_type": "goal",
                "target_label": goal,
                "metadata": {"source": "task"},
            }
        ]
        app_name = payload.get("app") or payload.get("window_title")
        if isinstance(app_name, str) and app_name.strip():
            events.append(
                {
                    "source_type": "task",
                    "source_label": task_id,
                    "edge_type": "active_in",
                    "target_type": "app",
                    "target_label": app_name.strip(),
                    "metadata": {"event_type": event_type},
                }
            )
        website = payload.get("url")
        if isinstance(website, str) and website.strip():
            events.append(
                {
                    "source_type": "task",
                    "source_label": task_id,
                    "edge_type": "active_in",
                    "target_type": "website",
                    "target_label": website.strip(),
                    "metadata": {"event_type": event_type},
                }
            )
        return events
