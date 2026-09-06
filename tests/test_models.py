from core.models import Message, ModelInfo


def test_message_roundtrip():
    m = Message(role="user", content="hi")
    assert Message.from_dict(m.to_dict()) == m


def test_model_info_free_detection():
    free = ModelInfo.from_dict({"id": "x/y:free", "name": "Y", "pricing": {"prompt": "0", "completion": "0"}})
    assert free.is_free
    paid = ModelInfo.from_dict({"id": "a/b", "pricing": {"prompt": "0.001", "completion": "0.002"}})
    assert not paid.is_free
    auto = ModelInfo.from_dict({"id": "kilo-auto/free", "isFree": True})
    assert auto.is_free
    assert auto.owned_by == "kilo-auto"
