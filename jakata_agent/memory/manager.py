from __future__ import annotations

import json
from pathlib import Path

from jakata_agent.memory.extractor import MemoryExtractor
from jakata_agent.memory.knowledge_loader import KnowledgeLoader
from jakata_agent.memory.models import RetrievedContext
from jakata_agent.memory.retriever import MemoryRetriever
from jakata_agent.memory.store import MemoryStore


class MemoryManager:
    def __init__(self, data_dir: Path, session_id: str) -> None:
        self.data_dir = data_dir
        self.session_id = session_id
        self.chats_dir = self.data_dir / "chats"
        self.knowledge_dir = self.data_dir / "knowledge"
        self.memory_dir = self.data_dir / "memory"
        self.db_path = self.memory_dir / "jakata.db"

        self.chats_dir.mkdir(parents=True, exist_ok=True)
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        self.store = MemoryStore(self.db_path)
        self.extractor = MemoryExtractor()
        self.knowledge_loader = KnowledgeLoader(self.knowledge_dir)
        self.knowledge_chunks = self.knowledge_loader.load_chunks()
        self._backfill_archived_memories()
        self.retriever = MemoryRetriever(self.store, self.chats_dir, self.knowledge_chunks)

    def bootstrap_system_note(self) -> str:
        sources: list[str] = []
        if self.knowledge_chunks:
            sources.append(f"{len(self.knowledge_chunks)} knowledge chunk(s)")
        recent_memories = self.store.recent(limit=5)
        if recent_memories:
            sources.append(f"{len(recent_memories)} permanent memory item(s)")
        archived_sessions = len(list(self.chats_dir.glob("session_*.json")))
        if archived_sessions:
            sources.append(f"{archived_sessions} archived session(s)")
        if not sources:
            return "Memory is empty. Learn from this conversation."
        return "Loaded memory: " + ", ".join(sources) + "."

    def retrieve(self, query: str) -> RetrievedContext:
        return self.retriever.retrieve(query, session_id=self.session_id)

    def persist_turn(self, messages: list[dict[str, str]]) -> None:
        path = self.chats_dir / f"session_{self.session_id}.json"
        payload = {"session_id": self.session_id, "messages": messages}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def load_session_messages(self) -> list[dict[str, str]]:
        path = self.chats_dir / f"session_{self.session_id}.json"
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            return []
        cleaned: list[dict[str, str]] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role in {"system", "user", "assistant"} and isinstance(content, str):
                cleaned.append({"role": role, "content": content})
        return cleaned

    def learn_from_user_message(self, user_message: str) -> None:
        for record in self.extractor.extract(user_message, session_id=self.session_id):
            self.store.upsert(record)

    def _backfill_archived_memories(self) -> None:
        for path in sorted(self.chats_dir.glob("session_*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            session_id = str(payload.get("session_id", path.stem.replace("session_", "")))
            for item in payload.get("messages", []):
                if not isinstance(item, dict) or item.get("role") != "user":
                    continue
                content = item.get("content")
                if not isinstance(content, str):
                    continue
                for record in self.extractor.extract(content, session_id=session_id):
                    self.store.upsert(record)
