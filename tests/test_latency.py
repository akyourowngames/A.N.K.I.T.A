"""Regressions for observable delays and durable short-term memory."""
import json
import sqlite3
import threading
import time
import pytest

from core.models import ChatResult, Message


def test_tool_start_precedes_actual_execution():
    from mcpclient.agent import run_agent_loop
    order = []
    responses = iter([
        ChatResult(content="", raw={"choices": [{"message": {"tool_calls": [{"id": "a", "type": "function", "function": {"name": "test__read", "arguments": "{}"}}]}}]}),
        ChatResult(content="Finished")])
    result = run_agent_loop([], "test", lambda *a, **k: next(responses),
        lambda name, args: order.append("execution") or "read result", [],
        on_tool_start=lambda name, args: order.append("start"),
        on_tool=lambda name, args, result: order.append("end"))
    assert result.content == "Finished"
    assert order == ["start", "execution", "end"]


def test_streaming_delivers_text_before_response_finishes_and_assembles_tools(monkeypatch):
    from core import api_client
    assert hasattr(api_client, "stream_agent_completion")
    received = []
    class Response:
        status_code = 200
        def iter_lines(self, **kwargs):
            yield b'data: {"choices":[{"delta":{"content":"Hello "}}]}'
            assert received == ["Hello "]
            yield b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"a","function":{"name":"test__read","arguments":"{\\"path\\":"}}]}}]}'
            yield b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"notes.txt\\"}"}}]}}]}'
            yield b'data: [DONE]'
        def close(self):
            pass
    monkeypatch.setattr(api_client.requests, "post", lambda *a, **k: Response())
    result = api_client.stream_agent_completion([], "test", api_key="test", on_token=received.append, tools=[])
    assert result.content == "Hello "
    call = result.raw["choices"][0]["message"]["tool_calls"][0]
    assert call["function"] == {"name": "test__read", "arguments": '{"path":"notes.txt"}'}


def test_recent_memory_is_available_before_enrichment(tmp_path, monkeypatch):
    from memory import inbox
    monkeypatch.setattr(inbox.db, "memory_home", lambda: tmp_path)
    inbox.save("My project is called Cedar.", "Assistant invented something.", "session", "chat")
    assert hasattr(inbox, "recent_context")
    context = inbox.recent_context()
    assert "My project is called Cedar." in context
    assert "Assistant invented" not in context


def test_failed_captures_can_be_retried_without_losing_original(tmp_path, monkeypatch):
    from memory import inbox
    monkeypatch.setattr(inbox.db, "memory_home", lambda: tmp_path)
    ident = inbox.save("Remember Cedar.", "", "session", "chat")
    inbox.finish(ident, "provider unavailable")
    assert not inbox.pending()
    assert hasattr(inbox, "retry_failed")
    assert inbox.retry_failed() == 1
    assert inbox.pending()[0][1] == "Remember Cedar."


def test_long_chat_does_not_wait_for_summary_generation(monkeypatch):
    from core import chat_pipeline, context_budget
    release = threading.Event()
    monkeypatch.setattr(chat_pipeline.store, "get_session", lambda sid: {"messages": [{"role": "user" if i % 2 == 0 else "assistant", "content": "context " * 800} for i in range(18)]})
    def summarize(dropped):
        release.wait(.7)
        return "Earlier decision: Cedar."
    monkeypatch.setattr(context_budget, "_default_summarizer", summarize)
    start = time.monotonic()
    try:
        result = chat_pipeline.build_messages("latency-test-session", "system", "Continue")
        assert result[-1].content == "Continue"
        assert time.monotonic() - start < .3
    finally:
        release.set()


def test_core_memory_does_not_close_callers_connection():
    from memory.service import Memory
    memory = object.__new__(Memory)
    memory._con = None
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE core_blocks(key TEXT,content TEXT)")
    con.execute("INSERT INTO core_blocks VALUES('identity','Cedar')")
    assert "Cedar" in memory._core_text(con)
    assert con.execute("SELECT COUNT(*) FROM core_blocks").fetchone()[0] == 1
    con.close()


def test_local_recall_retains_core_and_original_evidence(tmp_path, monkeypatch):
    from memory import fast_recall
    path = tmp_path / "memory.db"
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE core_blocks(key TEXT,content TEXT); CREATE TABLE episodes(id INTEGER PRIMARY KEY,user_text TEXT,assistant_text TEXT,created_at REAL); CREATE VIRTUAL TABLE fts_episodes USING fts5(user_text,assistant_text,content='episodes',content_rowid='id');")
    con.execute("INSERT INTO core_blocks VALUES('identity','Project Cedar')")
    con.execute("INSERT INTO episodes VALUES(1,'Cedar launches Friday','Made up assistant claim',1)")
    con.execute("INSERT INTO fts_episodes(rowid,user_text,assistant_text) VALUES(1,'Cedar launches Friday','Made up assistant claim')")
    con.commit()
    con.close()
    monkeypatch.setattr(fast_recall.db, "memory_db_path", lambda: path)
    text = fast_recall.local_context("Cedar")
    assert "Project Cedar" in text and "Cedar launches Friday" in text
    assert "Made up assistant claim" not in text


def test_capture_status_shows_real_saved_user_text(tmp_path, monkeypatch):
    from memory import inbox
    monkeypatch.setattr(inbox.db, "memory_home", lambda: tmp_path)
    ident = inbox.save("Cedar is my project.", "Unsupported claim.", "session", "chat")
    assert hasattr(inbox, "status")
    status = inbox.status()
    assert status["counts"]["pending"] == 1
    assert status["recent"][0]["user_text"] == "Cedar is my project."
    assert "Unsupported claim." not in json.dumps(status)
    inbox.finish(ident, "provider unavailable")
    assert inbox.status()["counts"]["failed"] == 1


def test_interrupted_stream_never_returns_executable_tool_calls(monkeypatch):
    from core import api_client
    class Response:
        status_code = 200
        def iter_lines(self, **kwargs):
            yield b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"a","function":{"name":"test__read","arguments":"{}"}}]}}]}'
        def close(self):
            pass
    monkeypatch.setattr(api_client.requests, "post", lambda *a, **k: Response())
    with pytest.raises(api_client.KiloError, match="ended before"):
        api_client.stream_agent_completion([], "test", api_key="test")


def test_sse_metadata_precedes_context_work(monkeypatch):
    import asyncio
    from server import app as server
    entered = []
    monkeypatch.setattr(server, "get_api_key", lambda **kw: "test")
    monkeypatch.setattr(server.store, "get_session", lambda sid: {"id": sid})
    monkeypatch.setattr(server, "_build_messages", lambda *a: entered.append("context") or [])
    response = server.chat_agent(server.ChatRequest(message="hello", model="test", session_id="latency"))
    async def check():
        event = await anext(response.body_iterator)
        assert "event: meta" in event
        assert entered == []
        await response.body_iterator.aclose()
    asyncio.run(check())


def test_recent_memory_budget_preserves_newest_statement(tmp_path, monkeypatch):
    from memory import inbox
    monkeypatch.setattr(inbox.db, "memory_home", lambda: tmp_path)
    for i in range(6):
        inbox.save(f"Older note {i} " + "details " * 100, "", "session", "chat")
    inbox.save("Latest correction: the launch moved to Monday.", "", "session", "chat")
    assert "Latest correction: the launch moved to Monday." in inbox.recent_context(max_chars=900)


def test_remember_tool_does_not_wait_for_enrichment(monkeypatch):
    import asyncio
    from mcpclient import builtin
    saved = []
    class Memory:
        def capture_async(self, *args):
            saved.append(args)
        def flush(self, *args):
            raise AssertionError('Enrichment must not block the tool acknowledgement')
    monkeypatch.setattr('memory.get_memory', lambda: Memory())
    result = asyncio.run(builtin.handle(None, 'memory_remember', {'text': 'Cedar is my project'}))
    assert saved[0][0] == 'Cedar is my project'
    assert 'background' in result


def test_truncated_tool_stream_is_not_executable(monkeypatch):
    from core import api_client
    class Response:
        status_code = 200
        def iter_lines(self, **kwargs):
            yield b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"a","function":{"name":"test__write","arguments":"{}"}}]},"finish_reason":"length"}]}'
            yield b'data: [DONE]'
        def close(self):
            pass
    monkeypatch.setattr(api_client.requests, 'post', lambda *a, **k: Response())
    with pytest.raises(api_client.KiloError, match='Incomplete tool call'):
        api_client.stream_agent_completion([], 'test', api_key='test')
