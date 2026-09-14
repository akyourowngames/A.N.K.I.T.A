"""Jarvis-style memory: a bounded log of original conversation messages."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid

_lock = threading.RLock()
_cache = {}


def chat_log_path() -> Path:
    return Path(os.getenv("ZUMBA_MEMORY_HOME") or Path.home() / ".zumba") / "ChatLog.json"


class Memory:
    def __init__(self, con=None, *, path=None, max_messages=80):
        self.path = Path(path) if path is not None else chat_log_path()
        self.max_messages = max(2, int(max_messages))
        # Only explicit task/reminder commands use this database connection.
        self._con, self._own = con, con is None

    @contextmanager
    def _writing(self):
        """Serialize CLI/server writes, including separate processes."""
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.with_suffix(".lock").open("a+b") as lock:
                if lock.tell() == 0:
                    lock.write(b"0")
                    lock.flush()
                lock.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    lock.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock, fcntl.LOCK_UN)

    def messages(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        if not isinstance(data, list) or any(
            not isinstance(m, dict) or m.get("role") not in ("user", "assistant")
            or not isinstance(m.get("content"), str) for m in data
        ):
            raise ValueError("Invalid chat log; clear it explicitly to start again")
        return data[-self.max_messages:]

    def _save(self, messages):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix="ChatLog-", suffix=".tmp", delete=False) as file:
                temporary = Path(file.name)
                json.dump(messages[-self.max_messages:], file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def ingest_episode(self, user_text, assistant_text, session_id="", kind="chat"):
        if os.getenv("ZUMBA_NO_MEMORY") == "1":
            return {"stored": False, "reason": "disabled"}
        if not user_text and not assistant_text:
            return {"stored": False, "reason": "empty"}
        ident, now = uuid.uuid4().hex[:12], time.time()
        with self._writing():
            messages = self.messages()
            for role, content in (("user", user_text), ("assistant", assistant_text)):
                if content:
                    messages.append({"id": ident, "role": role, "content": str(content),
                                     "session_id": session_id, "kind": kind, "created_at": now})
            self._save(messages)
        return {"stored": True, "id": ident}

    def capture_async(self, user_text, assistant_text, session_id="", kind="chat"):
        """Compatibility name: the local save finishes before returning."""
        return self.ingest_episode(user_text, assistant_text, session_id, kind)

    def recall_with_hits(self, query="", top_k=8, max_bytes=5000, *, exclude_session=""):
        if os.getenv("ZUMBA_NO_MEMORY") == "1" or top_k <= 0 or max_bytes <= 0:
            return "", []
        rows = [m for m in self.messages() if not exclude_session or m.get("session_id") != exclude_session]
        groups = []
        for row in rows:
            if not groups or groups[-1][0].get("id") != row.get("id"):
                groups.append([])
            groups[-1].append(row)
        blocks, hits, remaining = [], [], int(max_bytes)
        for group in reversed(groups[-int(top_k):]):
            # Share the budget so a long assistant answer cannot hide its user.
            allowance = min(1200, remaining // len(group) - 1)
            if allowance < 100 and blocks:
                break
            if allowance <= 0:
                break
            lines, evidence = [], []
            for row in group:
                stamp = datetime.fromtimestamp(row.get("created_at", 0)).astimezone().isoformat(timespec="minutes")
                line = f"[{row['role']} {stamp} id={row.get('id', '')}] {row['content']}"
                encoded = line.encode("utf-8")
                if len(encoded) > allowance:
                    line = encoded[:max(0, allowance - 3)].decode("utf-8", errors="ignore") + "..."
                lines.append(line)
                evidence.append({"kind": "message", "score": 0.0,
                                 "meta": {"id": row.get("id"), "role": row["role"]}, "snippet": line[:200]})
            block = "\n".join(lines)
            blocks.insert(0, block)
            hits[0:0] = evidence
            remaining -= len(block.encode("utf-8")) + 1
        return "\n".join(blocks), hits

    def recall(self, query="", top_k=8, max_bytes=5000, **kwargs):
        return self.recall_with_hits(query, top_k, max_bytes, **kwargs)[0]

    def stats(self):
        rows = self.messages()
        return {"mode": "chat history", "messages": len(rows),
                "exchanges": len({m.get("id") for m in rows}),
                "max_messages": self.max_messages, "file": str(self.path)}

    def status(self):
        rows = self.messages()
        recent = [{"id": m.get("id", ""), "user_text": m["content"], "status": "saved",
                   "error": "", "created_at": m.get("created_at", 0)} for m in rows if m["role"] == "user"]
        return {"mode": "chat history", "counts": {"saved": len(recent)}, "recent": list(reversed(recent[-12:]))}

    def forget(self, target):
        """Delete an exact exchange ID; no inferred entity matching."""
        with self._writing():
            rows = self.messages()
            kept = [m for m in rows if m.get("id") != target]
            self._save(kept)
        return {"forgot": len(kept) != len(rows), "reason": "Use an exchange ID from saved history"}

    def clear(self):
        with self._writing():
            self._save([])
        return {"cleared": True}

    def flush(self, timeout=30.0):
        return True  # Saves are synchronous; there is no background queue.

    def close(self):
        pass

    def _open(self):
        """Explicit task/reminder storage, never used for chat recall."""
        from . import db
        return self._con if self._con is not None else db.connect()


def get_memory():
    with _lock:
        path = chat_log_path()
        if "mem" not in _cache or _cache["mem"].path != path:
            _cache["mem"] = Memory(path=path)
        return _cache["mem"]
