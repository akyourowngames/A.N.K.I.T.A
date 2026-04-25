from __future__ import annotations

from pathlib import Path

from jakata_agent.memory.graph_store import GraphStore
from jakata_agent.memory.knowledge_loader import KnowledgeLoader
from jakata_agent.memory.retriever import MemoryRetriever
from jakata_agent.memory.store import MemoryStore


class FakeEmbedder:
    def similarity(self, query: str, text: str) -> float:
        query_l = query.lower()
        text_l = text.lower()
        if "call me" in query_l and "name is krish" in text_l:
            return 0.92
        return 0.0


def test_knowledge_loader_splits_lines_for_precise_retrieval(tmp_path: Path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "userdata.txt").write_text("user name is krish\nfavorite editor is VS Code", encoding="utf-8")

    chunks = KnowledgeLoader(knowledge).load_chunks()

    assert "user name is krish" in chunks
    assert "favorite editor is VS Code" in chunks


def test_retriever_uses_semantic_match_when_words_do_not_overlap(tmp_path: Path):
    chats = tmp_path / "chats"
    chats.mkdir()
    store = MemoryStore(tmp_path / "memory" / "jakata.db")
    graph = GraphStore(tmp_path / "memory" / "jakata.db")
    retriever = MemoryRetriever(
        store=store,
        chat_dir=chats,
        knowledge_chunks=["user name is krish"],
        embedder=FakeEmbedder(),
        graph_store=graph,
    )

    retrieved = retriever.retrieve("what should you call me", session_id="default")

    assert retrieved.knowledge_chunks == ["user name is krish"]
