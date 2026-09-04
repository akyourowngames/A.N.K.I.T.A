from pathlib import Path
import tempfile
from chat import Conversation


def test_conversation_system_first():
    c = Conversation(model="kilo-auto/free", system="sys")
    assert c.messages[0].role == "system"
    c.add_user("hello")
    c.add_assistant("hi")
    assert len(c.messages) == 3
    assert c.estimate_tokens() > 0


def test_conversation_save_load():
    c = Conversation(model="kilo-auto/free", system="sys")
    c.add_user("hello")
    c.add_assistant("hi")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s.json"
        c.save(p)
        loaded = Conversation.load(p)
        assert loaded.model == c.model
        assert len(loaded.messages) == 3


def test_clear_keeps_system():
    c = Conversation(model="m", system="sys")
    c.add_user("hi")
    c.clear()
    assert len(c.messages) == 1
    assert c.messages[0].role == "system"
