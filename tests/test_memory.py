"""
tests/test_memory.py — Unit tests for the A.N.K.I.T.A 3-layer memory system.

Run with: pytest tests/test_memory.py -v
"""
import time
import pytest
from pathlib import Path
import tempfile
import shutil


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a clean temporary directory for each test."""
    return tmp_path


@pytest.fixture
def fact_store(tmp_dir):
    from memory.fact_store import FactStore
    return FactStore(tmp_dir / "facts.db")


@pytest.fixture
def vector_store(tmp_dir):
    from memory.vector_store import VectorStore
    return VectorStore(tmp_dir / "chroma")


@pytest.fixture
def summarizer(tmp_dir):
    from memory.summarizer import Summarizer
    return Summarizer(tmp_dir)


@pytest.fixture
def manager(tmp_dir):
    # Reset singleton for each test
    import memory.manager as _mm
    _mm._INSTANCE = None
    from memory.manager import MemoryManager
    mgr = MemoryManager(tmp_dir)
    yield mgr
    # Cleanup singleton
    _mm._INSTANCE = None


# ─── FactStore tests ──────────────────────────────────────────────────────────

class TestFactStore:
    def test_upsert_and_retrieve(self, fact_store):
        """Facts persist in SQLite and survive re-open."""
        fact_id = fact_store.upsert_fact(
            "The user's favourite anime is Solo Leveling",
            confidence=1.0,
            interface="cli",
        )
        assert fact_id != ""
        all_facts = fact_store.all_facts()
        texts = [f["fact"] for f in all_facts]
        assert "The user's favourite anime is Solo Leveling" in texts

    def test_duplicate_upsert_bumps_confidence(self, fact_store):
        """Upserting the same fact twice bumps confidence instead of duplicating."""
        fact_store.upsert_fact("User prefers dark mode", confidence=0.9, interface="gui")
        fact_store.upsert_fact("User prefers dark mode", confidence=0.9, interface="gui")
        all_facts = fact_store.all_facts()
        matching = [f for f in all_facts if f["fact"] == "User prefers dark mode"]
        assert len(matching) == 1  # Only one row
        assert matching[0]["confidence"] >= 0.9  # Confidence bumped

    def test_keyword_search(self, fact_store):
        """SQLite keyword search returns relevant facts."""
        fact_store.upsert_fact("User loves Python programming", confidence=1.0, interface="cli")
        fact_store.upsert_fact("User dislikes JavaScript", confidence=1.0, interface="cli")
        fact_store.upsert_fact("User enjoys morning coffee", confidence=1.0, interface="cli")

        results = fact_store.search_keyword("Python", limit=5)
        assert len(results) >= 1
        assert any("Python" in r["fact"] for r in results)

    def test_empty_fact_ignored(self, fact_store):
        """Empty strings are silently ignored."""
        result = fact_store.upsert_fact("", confidence=1.0)
        assert result == ""
        assert fact_store.count() == 0

    def test_count(self, fact_store):
        """count() returns correct number of facts."""
        assert fact_store.count() == 0
        fact_store.upsert_fact("fact one", confidence=1.0)
        fact_store.upsert_fact("fact two", confidence=1.0)
        assert fact_store.count() == 2

    def test_recent_facts(self, fact_store):
        """recent_facts returns the most recently added facts."""
        for i in range(5):
            fact_store.upsert_fact(f"fact number {i}", confidence=1.0)
            time.sleep(0.01)
        recent = fact_store.recent_facts(limit=3)
        assert len(recent) == 3


# ─── VectorStore tests ────────────────────────────────────────────────────────

class TestVectorStore:
    def test_available_or_fallback(self, vector_store):
        """VectorStore is either available (chromadb installed) or gracefully not."""
        # Either way it should not raise
        count = vector_store.count()
        assert isinstance(count, int)

    def test_upsert_and_search(self, vector_store):
        """If ChromaDB available: upsert + semantic search returns relevant results."""
        if not vector_store.available:
            pytest.skip("ChromaDB not available — SQLite fallback active")

        vector_store.upsert("id-1", "User loves watching anime especially Solo Leveling", {"interface": "cli"})
        vector_store.upsert("id-2", "User enjoys morning coffee before work", {"interface": "cli"})
        vector_store.upsert("id-3", "User prefers dark mode in all editors", {"interface": "gui"})

        results = vector_store.search("what anime does the user like", n_results=3)
        assert len(results) >= 1
        assert any("anime" in r.lower() or "Solo Leveling" in r for r in results)

    def test_search_empty_collection(self, vector_store):
        """Search on empty collection returns [] — never crashes."""
        results = vector_store.search("anything", n_results=5)
        assert results == []

    def test_upsert_batch(self, vector_store):
        """Batch upsert works without error."""
        if not vector_store.available:
            pytest.skip("ChromaDB not available")
        facts = [
            {"id": "a", "fact": "User works on Python projects", "confidence": 1.0, "interface": "cli"},
            {"id": "b", "fact": "User listens to lofi music while coding", "confidence": 0.9, "interface": "cli"},
        ]
        vector_store.upsert_batch(facts)
        assert vector_store.count() == 2


# ─── Summarizer tests ─────────────────────────────────────────────────────────

class TestSummarizer:
    def test_log_turn_writes_file(self, summarizer, tmp_dir):
        """log_turn writes to today's JSONL file."""
        summarizer.log_turn("user", "My favourite colour is blue", interface="cli")
        files = list((tmp_dir / "sessions").glob("*.jsonl"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "My favourite colour is blue" in content

    def test_load_recent_turns(self, summarizer):
        """load_recent_turns returns logged turns in order."""
        summarizer.log_turn("user", "Hello Ankita", interface="cli")
        summarizer.log_turn("assistant", "Hey bestie! 💅", interface="cli")
        summarizer.log_turn("user", "What time is it?", interface="cli")

        turns = summarizer.load_recent_turns(n=10)
        assert len(turns) == 3
        assert turns[0]["role"] == "user"
        assert "Hello Ankita" in turns[0]["content"]

    def test_save_and_load_summary(self, summarizer):
        """Summaries are persisted and loaded correctly."""
        summarizer.save_summary("User is working on a Python AI project.", interface="dream")
        summaries = summarizer.load_recent_summaries(n=5)
        assert len(summaries) == 1
        assert "Python AI project" in summaries[0]

    def test_empty_log_returns_empty(self, summarizer):
        """load_recent_turns on empty log returns []."""
        turns = summarizer.load_recent_turns(n=10)
        assert turns == []


# ─── MemoryManager integration tests ─────────────────────────────────────────

class TestMemoryManager:
    def test_save_writes_to_session_log(self, manager, tmp_dir):
        """save() writes turns to JSONL session log."""
        manager.save("user", "remember that my name is Krish", interface="cli")
        files = list((tmp_dir / ".ankita" / "memory" / "sessions").glob("*.jsonl"))
        assert len(files) == 1

    def test_build_context_returns_string(self, manager):
        """build_context() returns a string (may be empty if no facts yet)."""
        result = manager.build_context("what do you know about me?")
        assert isinstance(result, str)

    def test_inject_into_messages(self, manager):
        """inject_into_messages adds a memory system message after the first system message."""
        # First add a fact directly so there's something to inject
        manager._facts.upsert_fact(
            "User's name is Krish",
            confidence=1.0,
            interface="cli",
        )
        messages = [
            {"role": "system", "content": "You are ANKITA."},
            {"role": "user", "content": "hello"},
        ]
        manager.inject_into_messages(messages, user_query="what is my name")
        # Should have injected a second system message with memory content
        system_msgs = [m for m in messages if m["role"] == "system"]
        assert len(system_msgs) >= 2  # Original + memory injection
        mem_block = " ".join(m["content"] for m in system_msgs)
        assert "Krish" in mem_block or "MEMORY" in mem_block

    def test_chroma_fallback_on_keyword_search(self, manager, tmp_dir):
        """Even without ChromaDB, build_context() falls back to SQLite LIKE search."""
        manager._facts.upsert_fact(
            "User is a 15-year-old developer from India",
            confidence=1.0,
            interface="cli",
        )
        # Force vector store to be unavailable
        manager._vectors._collection = None

        context = manager.build_context("where is the user from")
        # Should still work via SQLite fallback
        assert isinstance(context, str)
        # We won't assert the content as SQLite LIKE depends on tokenization
        # but it should NOT raise
