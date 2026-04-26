from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jakata_agent.llm import TextCompletionClient
from jakata_agent.prompts import load_prompt


COMPANION_PROMPT = load_prompt("companion/starter.md")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat()


def parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(slots=True)
class CompanionDecision:
    should_speak: bool
    message_id: str = ""
    text: str = ""
    category: str = ""
    reason: str = ""
    score: float = 0.0
    skipped_reason: str = ""
    due_after_seconds: int = 0


class CompanionStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS companion_messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    category TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    score REAL NOT NULL,
                    model TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS companion_feedback (
                    id TEXT PRIMARY KEY,
                    message_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    note TEXT NOT NULL,
                    user_reply TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS companion_preferences (
                    session_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, key)
                )
                """
            )

    def record_message(
        self,
        *,
        session_id: str,
        text: str,
        category: str,
        reason: str,
        score: float,
        model: str,
        raw: dict[str, Any],
    ) -> str:
        message_id = str(uuid.uuid4())
        now = utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO companion_messages (
                    id, session_id, text, category, reason, score, model,
                    raw_json, status, created_at, delivered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    session_id,
                    text,
                    category,
                    reason,
                    score,
                    model,
                    json.dumps(raw, ensure_ascii=False),
                    "delivered",
                    now,
                    now,
                ),
            )
        return message_id

    def record_feedback(
        self,
        *,
        session_id: str,
        message_id: str,
        signal: str,
        note: str = "",
        user_reply: str = "",
    ) -> dict[str, Any]:
        normalized = signal.strip().lower()
        if normalized not in {
            "love",
            "like",
            "more_like_this",
            "reply",
            "boring",
            "less_like_this",
            "snooze",
            "stop",
            "dismiss",
        }:
            normalized = "note"
        now = utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO companion_feedback (
                    id, message_id, session_id, signal, note, user_reply, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), message_id, session_id, normalized, note, user_reply, now),
            )
            if normalized in {"love", "like", "more_like_this", "reply"}:
                conn.execute("UPDATE companion_messages SET status = ? WHERE id = ?", ("positive", message_id))
            elif normalized in {"boring", "less_like_this", "dismiss"}:
                conn.execute("UPDATE companion_messages SET status = ? WHERE id = ?", ("negative", message_id))
            elif normalized == "snooze":
                self._set_preference(conn, session_id, "quiet_until", (utcnow() + timedelta(hours=2)).isoformat())
            elif normalized == "stop":
                self._set_preference(conn, session_id, "enabled", "false")
        return {"signal": normalized, "message_id": message_id}

    def set_enabled(self, session_id: str, enabled: bool) -> None:
        with self._connect() as conn:
            self._set_preference(conn, session_id, "enabled", "true" if enabled else "false")

    def is_enabled(self, session_id: str, default: bool = True) -> bool:
        value = self.preference(session_id, "enabled")
        if not value:
            return default
        return value.strip().lower() not in {"0", "false", "off", "no"}

    def quiet_until(self, session_id: str) -> datetime | None:
        return parse_iso(self.preference(session_id, "quiet_until"))

    def preference(self, session_id: str, key: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM companion_preferences WHERE session_id = ? AND key = ?",
                (session_id, key),
            ).fetchone()
        return str(row[0]) if row else ""

    def last_delivered_at(self, session_id: str) -> datetime | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT delivered_at FROM companion_messages
                WHERE session_id = ?
                ORDER BY delivered_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        return parse_iso(str(row[0])) if row else None

    def delivered_count_since(self, session_id: str, since: datetime) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM companion_messages
                WHERE session_id = ? AND delivered_at >= ?
                """,
                (session_id, since.isoformat()),
            ).fetchone()
        return int(row[0]) if row else 0

    def feedback_summary(self, session_id: str, limit: int = 12) -> str:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT m.category, f.signal, f.note, f.user_reply, m.text, f.created_at
                FROM companion_feedback f
                LEFT JOIN companion_messages m ON m.id = f.message_id
                WHERE f.session_id = ?
                ORDER BY f.created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        if not rows:
            return "No companion feedback yet."
        lines = []
        for category, signal, note, user_reply, text, _created_at in rows:
            parts = [f"{signal} on {category or 'unknown'}"]
            if text:
                parts.append(f"message={str(text)[:120]}")
            if note:
                parts.append(f"note={str(note)[:120]}")
            if user_reply:
                parts.append(f"user_reply={str(user_reply)[:120]}")
            lines.append("- " + "; ".join(parts))
        return "\n".join(lines)

    def recent_messages(self, session_id: str, limit: int = 5) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, text, category, reason, score, status, delivered_at
                FROM companion_messages
                WHERE session_id = ?
                ORDER BY delivered_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [
            {
                "id": row[0],
                "text": row[1],
                "category": row[2],
                "reason": row[3],
                "score": row[4],
                "status": row[5],
                "delivered_at": row[6],
            }
            for row in rows
        ]

    @staticmethod
    def _set_preference(conn: sqlite3.Connection, session_id: str, key: str, value: str) -> None:
        conn.execute(
            """
            INSERT INTO companion_preferences (session_id, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id, key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (session_id, key, value, utcnow_iso()),
        )


class ProactiveCompanionEngine:
    def __init__(
        self,
        *,
        client: TextCompletionClient,
        store: CompanionStore,
        enabled_default: bool = True,
        min_interval_seconds: int = 300,
        max_per_day: int = 12,
        min_score: float = 0.62,
    ) -> None:
        self.client = client
        self.store = store
        self.enabled_default = enabled_default
        self.min_interval_seconds = max(30, int(min_interval_seconds))
        self.max_per_day = max(1, int(max_per_day))
        self.min_score = float(min_score)

    def next_message(
        self,
        *,
        session_id: str,
        conversation_context: str,
        memory_context: str = "",
        force: bool = False,
    ) -> CompanionDecision:
        allowed = self._allowed(session_id=session_id, force=force)
        if not allowed.should_speak:
            return allowed

        model, raw_text = self.client.complete_text(
            COMPANION_PROMPT,
            self._build_user_prompt(
                session_id=session_id,
                conversation_context=conversation_context,
                memory_context=memory_context,
            ),
            temperature=0.85,
        )
        payload = self._parse_payload(raw_text)
        text = str(payload.get("text", "")).strip()
        if not text:
            return CompanionDecision(should_speak=False, skipped_reason="empty_model_output")
        category = str(payload.get("category", "check_in")).strip() or "check_in"
        reason = str(payload.get("reason", "companion initiative")).strip()
        score = self._coerce_score(payload.get("score", 0.72))
        if not force and score < self.min_score:
            return CompanionDecision(
                should_speak=False,
                skipped_reason="low_score",
                score=score,
                reason=reason,
            )
        message_id = self.store.record_message(
            session_id=session_id,
            text=text,
            category=category,
            reason=reason,
            score=score,
            model=model,
            raw=payload,
        )
        return CompanionDecision(
            should_speak=True,
            message_id=message_id,
            text=text,
            category=category,
            reason=reason,
            score=score,
        )

    def _allowed(self, *, session_id: str, force: bool) -> CompanionDecision:
        if force:
            return CompanionDecision(should_speak=True)
        if not self.store.is_enabled(session_id, default=self.enabled_default):
            return CompanionDecision(should_speak=False, skipped_reason="disabled")
        quiet_until = self.store.quiet_until(session_id)
        now = utcnow()
        if quiet_until and quiet_until > now:
            return CompanionDecision(
                should_speak=False,
                skipped_reason="snoozed",
                due_after_seconds=max(1, int((quiet_until - now).total_seconds())),
            )
        delivered_today = self.store.delivered_count_since(session_id, now - timedelta(hours=24))
        if delivered_today >= self.max_per_day:
            return CompanionDecision(should_speak=False, skipped_reason="daily_limit")
        last = self.store.last_delivered_at(session_id)
        if last:
            wait = self.min_interval_seconds - int((now - last).total_seconds())
            if wait > 0:
                return CompanionDecision(should_speak=False, skipped_reason="too_soon", due_after_seconds=wait)
        return CompanionDecision(should_speak=True)

    def _build_user_prompt(self, *, session_id: str, conversation_context: str, memory_context: str) -> str:
        return (
            "User profile hint: Krish is 15. Keep it age-appropriate, supportive, and non-manipulative.\n\n"
            f"Recent conversation:\n{conversation_context.strip() or 'No recent chat in this session.'}\n\n"
            f"Memory context:\n{memory_context.strip() or 'No extra memory context.'}\n\n"
            f"Recent companion feedback:\n{self.store.feedback_summary(session_id)}\n\n"
            f"Recent companion messages:\n{json.dumps(self.store.recent_messages(session_id), ensure_ascii=False)}\n\n"
            "Create one message that feels alive and worth saying now."
        )

    @staticmethod
    def _parse_payload(raw_text: str) -> dict[str, Any]:
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                payload = json.loads(text[start : end + 1])
            else:
                payload = {"text": text, "category": "check_in", "reason": "model returned plain text", "score": 0.5}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _coerce_score(value: Any) -> float:
        try:
            return max(0.0, min(float(value), 1.0))
        except (TypeError, ValueError):
            return 0.72
