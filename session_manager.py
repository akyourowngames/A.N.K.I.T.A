"""
A.N.K.I.T.A — Session Manager (Black Box / Flight Recorder) ✈️
==============================================================
Persists conversation state to disk so Ankita remembers everything
across restarts, crashes, and reboots.

Vault:   <workspace>/.ankita/current_session.json
Format:  {
    "messages":      [...],   # last N user/assistant turns
    "workspace":     str,     # current focused folder
    "active_tasks":  [...]    # IDs of hive drone tasks (informational)
}

Thread-safety: all writes go through a Lock + atomic rename (write .tmp → replace).
Compression: when history > MAX_TURNS, oldest 10 messages are summarised by the LLM
             and replaced with a single system summary message.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_TURNS = 20          # compress when history exceeds this many messages
COMPRESS_COUNT = 10     # how many old messages to summarise in one go


class SessionManager:
    """
    Manages persistent session state for A.N.K.I.T.A.

    Usage:
        sm = SessionManager(workspace_root, runtime=runtime)
        sm.load()                          # call once at startup
        sm.add_message("user", "hello")    # after every user input
        sm.add_message("assistant", "hi")  # after every reply
        sm.compress_if_needed()            # call after each assistant turn
        sm.clear()                         # on /reset
    """

    def __init__(self, workspace_root: Path, runtime: Any = None) -> None:
        self.workspace_root = workspace_root
        self.runtime = runtime          # LLMRuntime — used for compression
        self._lock = threading.Lock()

        vault_dir = workspace_root / ".ankita"
        vault_dir.mkdir(parents=True, exist_ok=True)
        self._vault = vault_dir / "current_session.json"
        self._tmp   = vault_dir / "current_session.json.tmp"

        # In-memory state
        self._messages: List[Dict[str, Any]] = []
        self._workspace: str = str(workspace_root)
        self._active_tasks: List[str] = []
        self._restored: bool = False   # True if we loaded a previous session

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def restored(self) -> bool:
        """True if a previous session was successfully loaded from disk."""
        return self._restored

    @property
    def messages(self) -> List[Dict[str, Any]]:
        """Current persisted conversation history (user/assistant only)."""
        with self._lock:
            return list(self._messages)

    def load(self) -> Optional[List[Dict[str, Any]]]:
        """
        Load the last session from disk.

        Returns the list of persisted messages on success, or None if no
        previous session exists. Call once at startup before building
        the initial messages list.
        """
        if not self._vault.exists():
            return None
        try:
            with open(self._vault, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            msgs = data.get("messages", [])
            if not isinstance(msgs, list) or len(msgs) == 0:
                return None
            with self._lock:
                self._messages = msgs
                self._workspace = data.get("workspace", str(self.workspace_root))
                self._active_tasks = data.get("active_tasks", [])
                self._restored = True
            print(
                f"[SessionManager] ✅ Restored {len(msgs)} messages from previous session.",
                flush=True,
            )
            return list(msgs)
        except Exception as err:
            print(f"[SessionManager] ⚠️  Could not load session: {err}", flush=True)
            return None

    def add_message(self, role: str, content: str) -> None:
        """
        Append a single message to the in-memory history and immediately
        persist to disk. Thread-safe.
        """
        if not content or not content.strip():
            return
        msg = {"role": role, "content": content.strip(), "ts": time.time()}
        with self._lock:
            self._messages.append(msg)
        self._persist()

    def update_active_tasks(self, task_ids: List[str]) -> None:
        """Update the list of active hive drone task IDs and save."""
        with self._lock:
            self._active_tasks = list(task_ids)
        self._persist()

    def set_workspace(self, path: str) -> None:
        """Update the current focused workspace path and save."""
        with self._lock:
            self._workspace = path
        self._persist()

    def compress_if_needed(self) -> None:
        """
        If message history > MAX_TURNS, compress the oldest COMPRESS_COUNT
        messages into a single summary paragraph using the LLM.
        Runs the compression in the calling thread (meant to be called from
        a background thread so chat stays responsive).
        """
        with self._lock:
            count = len(self._messages)
        if count <= MAX_TURNS:
            return

        print(
            f"[SessionManager] 🗜️  History at {count} msgs — compressing oldest {COMPRESS_COUNT}…",
            flush=True,
        )
        self._compress()

    def clear(self) -> None:
        """Delete the session vault and reset in-memory state (for /reset)."""
        with self._lock:
            self._messages = []
            self._active_tasks = []
            self._restored = False
        try:
            if self._vault.exists():
                self._vault.unlink()
            if self._tmp.exists():
                self._tmp.unlink()
        except Exception as err:
            print(f"[SessionManager] ⚠️  Could not delete vault: {err}", flush=True)
        print("[SessionManager] 🗑️  Session vault cleared.", flush=True)

    def build_restored_messages(self, system_prompt_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Merge the system prompt message(s) with the restored history.

        Call this after load() returns non-None.

        Returns a messages list ready for the LLM: [system_msg, ...history]
        """
        with self._lock:
            history = list(self._messages)

        # Strip internal 'ts' keys so the LLM doesn't see them
        clean_history = [
            {k: v for k, v in m.items() if k != "ts"}
            for m in history
        ]
        return list(system_prompt_messages) + clean_history

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Atomically write current state to disk under the lock."""
        with self._lock:
            data = {
                "messages":     self._messages,
                "workspace":    self._workspace,
                "active_tasks": self._active_tasks,
                "saved_at":     time.time(),
            }
        try:
            # Write to .tmp first, then atomic rename — prevents partial-write corruption
            with open(self._tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(str(self._tmp), str(self._vault))
        except Exception as err:
            print(f"[SessionManager] ❌ persist() failed: {err}", flush=True)

    def _compress(self) -> None:
        """
        Summarise the oldest COMPRESS_COUNT messages with the LLM and replace
        them with a single system-level summary message.
        """
        with self._lock:
            if len(self._messages) <= MAX_TURNS:
                return  # someone else already compressed
            to_compress = self._messages[:COMPRESS_COUNT]
            rest        = self._messages[COMPRESS_COUNT:]

        # Build a mini-transcript for the LLM to summarise
        transcript_lines = []
        for m in to_compress:
            role = m.get("role", "?")
            content = m.get("content", "")[:400]   # cap each snippet
            transcript_lines.append(f"{role.upper()}: {content}")
        transcript = "\n".join(transcript_lines)

        summary_text = self._call_llm_for_summary(transcript)

        summary_msg: Dict[str, Any] = {
            "role":    "system",
            "content": f"[Conversation summary — earlier context]: {summary_text}",
            "ts":      time.time(),
        }

        with self._lock:
            # Prepend summary, keep the rest
            self._messages = [summary_msg] + rest

        self._persist()
        print(
            f"[SessionManager] ✅ Compressed {COMPRESS_COUNT} old messages into summary.",
            flush=True,
        )

    def _call_llm_for_summary(self, transcript: str) -> str:
        """Call the LLM to produce a short summary paragraph of the transcript."""
        if self.runtime is None:
            return "(summary unavailable — no LLM runtime attached)"

        try:
            from llm import call_chat_once

            summary_msgs = [
                {
                    "role": "system",
                    "content": (
                        "You are a concise archivist. Summarise the following conversation "
                        "excerpt into ONE short paragraph (max 120 words). Capture the key "
                        "topics discussed, decisions made, and any files or tasks involved. "
                        "Write in past tense, third person."
                    ),
                },
                {"role": "user", "content": transcript},
            ]
            result = call_chat_once(self.runtime, summary_msgs, tools=None)
            return (result.get("content") or "").strip() or "(empty summary)"
        except Exception as err:
            print(f"[SessionManager] ⚠️  LLM summary failed: {err}", flush=True)
            return f"(summary error: {err})"
