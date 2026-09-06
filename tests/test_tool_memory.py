"""Tool-transcript memory across turns: DB persistence + resume folding."""

import pathlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main
from core import store
from core.models import Message


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def _transcript():
    return [
        Message(role="assistant", content="", tool_calls=[{"id": "c1", "function": {"name": "s__run", "arguments": "{}"}}]),
        Message(role="tool", content="Python 3.12.10", tool_call_id="c1", name="s__run"),
        Message(role="assistant", content="", tool_calls=[{"id": "c2", "function": {"name": "s__jobs", "arguments": "{}"}}]),
        Message(role="tool", content="running job d69f", tool_call_id="c2", name="s__jobs"),
    ]


def test_save_and_fold_roundtrip(isolated_home):
    sid = store.new_session_id()
    store.create_session(sid, "m", "sys")
    store.add_message(sid, "user", "check python")
    main._save_tool_transcript(sid, _transcript())
    store.add_message(sid, "assistant", "Python is 3.12.10, job running.")

    data = store.get_session(sid)
    assert any(m["role"] == "tool" for m in data["messages"])

    conv = [Message(role=m["role"], content=m["content"]) for m in data["messages"] if m["role"] != "system"]
    folded = main._fold_saved_tool_context(conv)
    assert not [m for m in folded if m.role == "tool"], "bare tool messages must not reach the API"
    digests = [m for m in folded if m.role == "system" and "Prior tool context" in m.content]
    assert len(digests) == 1
    assert "Python 3.12.10" in digests[0].content and "job d69f" in digests[0].content
    roles = [m.role for m in folded]
    assert roles[0] == "system" and roles[1] == "user" and roles[-1] == "assistant"


def test_fold_no_tools_is_noop():
    msgs = [Message(role="user", content="hi"), Message(role="assistant", content="hello")]
    assert main._fold_saved_tool_context(msgs) == msgs


def test_save_empty_transcript_safe(isolated_home):
    sid = store.new_session_id()
    store.create_session(sid, "m", "sys")
    main._save_tool_transcript(sid, [])
    main._save_tool_transcript(sid, None)
    assert store.get_session(sid) is not None
