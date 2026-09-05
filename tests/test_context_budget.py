"""Tests for the context window manager (no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import Message
import context_budget as cb


def _user(i: int) -> Message:
    return Message(role="user", content=f"user message number {i} " + "x" * 200)


def _asst(i: int) -> Message:
    return Message(role="assistant", content=f"assistant reply number {i} " + "y" * 200)


def _convo(n_turns: int = 25) -> list:
    msgs = [Message(role="system", content="system prompt")]
    for i in range(n_turns):
        msgs.append(_user(i))
        msgs.append(_asst(i))
    return msgs


def test_estimator_monotonic_and_code_aware():
    a = cb.estimate_tokens("hello world, this is a test sentence")
    b = cb.estimate_tokens("hello world, this is a test sentence plus more words here")
    assert b > a > 0
    assert cb.estimate_tokens("") == 0.0
    code = cb.estimate_tokens("```" + "z" * 350 + "```")
    prose = cb.estimate_tokens("z" * 350)
    assert code > prose  # denser: more tokens per char


def test_long_session_collapses_under_limit():
    msgs = _convo(25)
    calls = {"n": 0}

    def fake_summarizer(dropped):
        calls["n"] += 1
        return "covered %d turns" % len(dropped)

    out = cb.build_window(msgs, model_limit=3000, reserve_out=500, cache={}, summarizer=fake_summarizer)
    total = sum(cb.message_tokens(m) for m in out)
    assert total <= 3000 - 500, total
    assert len(out) < len(msgs)
    assert calls["n"] == 1


def test_system_anchor_and_last_turns_survive():
    msgs = _convo(25)
    out = cb.build_window(msgs, model_limit=3000, reserve_out=500, cache={}, summarizer=lambda d: "s")
    texts = [m.content for m in out]
    assert "system prompt" in texts
    assert any(t.startswith("user message number 0 ") for t in texts)  # anchor
    assert any(t.startswith("user message number 24 ") for t in texts)  # last turn
    assert any(t.startswith("assistant reply number 24 ") for t in texts)
    assert any("rolling summary" in t for t in texts)


def test_summary_cached_and_rebuilt_on_gap():
    msgs = _convo(25)
    calls = {"n": 0}
    cache: dict = {}

    def fake_summarizer(dropped):
        calls["n"] += 1
        return "v%d" % calls["n"]

    cb.build_window(msgs, model_limit=3000, reserve_out=500, cache=cache, summarizer=fake_summarizer)
    assert calls["n"] == 1
    cb.build_window(msgs, model_limit=3000, reserve_out=500, cache=cache, summarizer=fake_summarizer)
    assert calls["n"] == 1, "same dropped span must reuse the cached summary"
    grown = msgs + [_user(100 + i) for i in range(12)]
    out = cb.build_window(grown, model_limit=3000, reserve_out=500, cache=cache, summarizer=fake_summarizer)
    assert calls["n"] == 2, ">=6 newly dropped turns must trigger a rebuild"
    assert sum(1 for m in out if "rolling summary" in m.content) == 1


def test_stale_tool_transcripts_truncated():
    msgs = [Message(role="system", content="sys"), Message(role="user", content="go")]
    for i in range(4):
        msgs.append(Message(role="assistant", content="", tool_calls=[{"id": str(i), "function": {"name": "t", "arguments": "{}"}}]))
        msgs.append(Message(role="tool", content="R" * 1000, tool_call_id=str(i), name="t"))
    msgs.append(Message(role="user", content="continue"))
    out = cb.truncate_stale_tools(msgs)
    tools = [m for m in out if m.role == "tool"]
    assert len(tools[0].content) <= 250, "oldest tool exchange truncated"
    assert len(tools[-1].content) == 1000, "last 2 exchanges intact"
    assert len(tools[-2].content) == 1000


def test_short_session_untouched():
    msgs = [Message(role="system", content="sys"), Message(role="user", content="hi"), Message(role="assistant", content="hello")]
    out = cb.build_window(msgs, model_limit=8192, cache={}, summarizer=lambda d: (_ for _ in ()).throw(AssertionError("no summary needed")))
    assert [m.content for m in out] == ["sys", "hi", "hello"]
