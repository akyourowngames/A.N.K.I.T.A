import json
from unittest.mock import MagicMock, patch
from api_client import KiloError, chat_completion, list_models, stream_chat_completion
from models import Message


def _resp(payload, status=200):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = payload
    m.text = json.dumps(payload)
    return m


def test_list_models_parses_free():
    payload = {"data": [{"id": "kilo-auto/free", "name": "Auto Free", "isFree": True}, {"id": "a/b", "pricing": {"prompt": "1", "completion": "1"}}]}
    with patch("api_client.requests.request", return_value=_resp(payload)):
        models = list_models(base_url="https://x")
    assert models[0].id == "kilo-auto/free"
    assert models[0].is_free


def test_chat_completion_success():
    payload = {"model": "m", "choices": [{"message": {"content": "hello"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}
    with patch("api_client.requests.request", return_value=_resp(payload)):
        r = chat_completion([Message("user", "hi")], "m", api_key="k", base_url="https://x")
    assert r.content == "hello"
    assert r.usage.total_tokens == 3


def test_chat_completion_401_raises():
    with patch("api_client.requests.request", return_value=_resp({"error": {"message": "bad key"}}, status=401)):
        try:
            chat_completion([Message("user", "hi")], "m", api_key="k", base_url="https://x")
        except KiloError as e:
            assert e.status_code == 401
            return
    raise AssertionError("should have raised")


def test_chat_completion_503_retries_once():
    ok = _resp({"model": "m", "choices": [{"message": {"content": "recovered"}}]})
    bad = _resp({"error": {"message": "try again"}}, status=503)
    with patch("api_client.requests.request", side_effect=[bad, ok]) as req, patch("time.sleep", return_value=None):
        r = chat_completion([Message("user", "hi")], "m", api_key="k", base_url="https://x")
    assert r.content == "recovered"
    assert req.call_count == 2


def test_stream_parses_sse():
    chunks = [
        'data: {"model":"m","choices":[{"delta":{"content":"hel"}}]}',
        "",
        'data: {"model":"m","choices":[{"delta":{"content":"lo"}}]}',
        "data: [DONE]",
    ]
    m = MagicMock()
    m.status_code = 200
    m.iter_lines.return_value = chunks
    m.close.return_value = None
    with patch("api_client.requests.post", return_value=m):
        out = list(stream_chat_completion([Message("user", "hi")], "m", api_key="k", base_url="https://x"))
    assert "".join(out) == "hello"
