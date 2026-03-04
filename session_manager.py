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
            # Sanitize restored messages — strip any base64 blobs that would
            # cause a 400 Bad Request loop on every startup turn.
            clean_msgs = [self._sanitize_message(m) for m in msgs]
            with self._lock:
                self._messages = clean_msgs
                self._workspace = data.get("workspace", str(self.workspace_root))
                self._active_tasks = data.get("active_tasks", [])
                self._restored = True
            print(
                f"[SessionManager] ✅ Restored {len(clean_msgs)} messages from previous session.",
                flush=True,
            )
            return list(clean_msgs)
        except Exception as err:
            print(f"[SessionManager] ⚠️  Could not load session: {err}", flush=True)
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # Sanitization helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _sanitize_content(content: Any) -> str:
        """
        Strip base64 image blobs and oversized content from a message before
        persisting or sending to the LLM.

        Protects against:
        - 400 Bad Request loops caused by restored sessions with embedded base64 images
        - Context window overflow from huge tool-result strings
        """
        if not isinstance(content, str):
            # Multimodal content (list of blocks) — flatten to text only
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "image_url":
                            text_parts.append("[image: stripped for storage]")
                return " ".join(text_parts).strip()
            return str(content)

        # Strip inline base64 data URIs (data:image/...;base64,<blob>)
        import re as _re
        sanitized = _re.sub(
            r"data:image/[^;]+;base64,[A-Za-z0-9+/=]{100,}",
            "[base64_image_stripped]",
            content,
        )
        # Strip raw base64 blobs that appear without a data URI prefix
        # (long runs of base64 chars ≥ 500 chars with no spaces)
        sanitized = _re.sub(
            r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/=]{500,}(?![A-Za-z0-9+/=])",
            "[large_blob_stripped]",
            sanitized,
        )
        # Hard cap: if content is still >50KB after sanitization, truncate it
        _MAX_CONTENT_BYTES = 50_000
        if len(sanitized.encode("utf-8", errors="replace")) > _MAX_CONTENT_BYTES:
            sanitized = sanitized[:_MAX_CONTENT_BYTES] + "\n…[truncated — content too large to persist]"
        return sanitized

    @staticmethod
    def _sanitize_message(msg: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy of msg with sanitized content."""
        sanitized = dict(msg)
        sanitized["content"] = SessionManager._sanitize_content(msg.get("content", ""))
        return sanitized

    def add_message(self, role: str, content: str) -> None:
        """
        Append a single message to the in-memory history and immediately
        persist to disk. Thread-safe.
        """
        if not content or not str(content).strip():
            return
        safe_content = self._sanitize_content(content)
        msg = {"role": role, "content": safe_content, "ts": time.time()}
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
        """
        Call the LLM to produce an intelligent summary (UPGRADE 11).
        
        Instead of basic truncation, this extracts:
        - Active tasks and their status
        - Key decisions made
        - File paths mentioned
        - Agent actions taken
        - Important context for future turns
        """
        if self.runtime is None:
            return "(summary unavailable — no LLM runtime attached)"

        try:
            from llm import call_chat_once

            summary_msgs = [
                {
                    "role": "system",
                    "content": (
                        "You are A.N.K.I.T.A's Memory Compressor. Summarize this conversation excerpt into a compact context block.\n\n"
                        "Extract and preserve:\n"
                        "- Active tasks: what was being worked on, current status\n"
                        "- Key decisions: choices made, approaches selected\n"
                        "- File paths: any files created, edited, or referenced\n"
                        "- Agent actions: which agents were used and what they did\n"
                        "- Important context: facts needed for future turns\n\n"
                        "Format as a structured block (max 200 words):\n"
                        "```\n"
                        "CONTEXT SUMMARY:\n"
                        "Active Tasks: <list>\n"
                        "Files: <paths>\n"
                        "Decisions: <key choices>\n"
                        "Status: <current state>\n"
                        "```\n\n"
                        "Write in past tense. Be specific with file paths and task names. "
                        "Omit pleasantries and filler. Focus on actionable context."
                    ),
                },
                {"role": "user", "content": f"Summarize this conversation:\n\n{transcript}"},
            ]
            result = call_chat_once(self.runtime, summary_msgs, tools=None, max_tokens=300)
            summary = (result.get("content") or "").strip()
            
            if not summary:
                return "(empty summary)"
            
            # Ensure summary is compact
            if len(summary) > 1000:
                summary = summary[:1000] + "..."
            
            return summary
            
        except Exception as err:
            print(f"[SessionManager] ⚠️  LLM summary failed: {err}", flush=True)
            return f"(summary error: {err})"
