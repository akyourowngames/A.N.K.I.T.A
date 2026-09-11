import json
from unittest.mock import MagicMock, patch
from core.api_client import (
    GatewayError,
    KiloError,
    _chat_payload,
    chat_completion,
    list_models,
    stream_chat_completion,
)
from core.models import Message


def _resp(payload, status=200):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = payload
    m.text = json.dumps(payload)
    return m


def test_nim_is_default_provider():
    from core import config as config_mod

    assert "nvidia.com" in config_mod.DEFAULT_BASE_URL
    assert config_mod.DEFAULT_MODEL == "nvidia/nemotron-3-super-120b-a12b"
    assert KiloError is GatewayError  # legacy alias kept


def test_chat_payload_strips_unsupported_name_and_zero_temperature():
    payload = _chat_payload(
        [Message(role="tool", content="ok", tool_call_id="1", name="srv__tool"), Message("user", "hi")],
        "openai/gpt-oss-120b",
        temperature=0.0,
    )
    assert all("name" not in m for m in payload["messages"])
    assert payload["temperature"] == 1e-8


def test_list_models_parses_openai_shape():
    payload = {"data": [{"id": "nvidia/nemotron-3-super-120b-a12b", "object": "model", "created": 1, "owned_by": "nvidia"}]}
    with patch("core.api_client.requests.request", return_value=_resp(payload)):
        models = list_models(base_url="https://x")
    assert models[0].id == "nvidia/nemotron-3-super-120b-a12b"
    assert models[0].owned_by == "nvidia"


def test_list_models_sends_auth_header():
    payload = {"data": []}
    with patch("core.api_client.requests.request", return_value=_resp(payload)) as req:
        list_models(base_url="https://x", api_key="gsk-test")
    _, kwargs = req.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer gsk-test"


def test_list_models_legacy_free_shape_still_parses():
    payload = {"data": [{"id": "kilo-auto/free", "name": "Auto Free", "isFree": True}, {"id": "a/b", "pricing": {"prompt": "1", "completion": "1"}}]}
    with patch("core.api_client.requests.request", return_value=_resp(payload)):
        models = list_models(base_url="https://x")
    assert models[0].id == "a/b"
    assert models[1].id == "kilo-auto/free"
    assert models[1].is_free


def test_chat_completion_success():
    payload = {"model": "m", "choices": [{"message": {"content": "hello"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}
    with patch("core.api_client.requests.request", return_value=_resp(payload)):
        r = chat_completion([Message("user", "hi")], "m", api_key="k", base_url="https://x")
    assert r.content == "hello"
    assert r.usage.total_tokens == 3


def test_chat_completion_401_raises():
    with patch("core.api_client.requests.request", return_value=_resp({"error": {"message": "bad key"}}, status=401)):
        try:
            chat_completion([Message("user", "hi")], "m", api_key="k", base_url="https://x")
        except KiloError as e:
            assert e.status_code == 401
            return
    raise AssertionError("should have raised")


def test_chat_completion_503_retries_once():
    ok = _resp({"model": "m", "choices": [{"message": {"content": "recovered"}}]})
    bad = _resp({"error": {"message": "try again"}}, status=503)
    with patch("core.api_client.requests.request", side_effect=[bad, ok]) as req, patch("time.sleep", return_value=None):
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
    with patch("core.api_client.requests.post", return_value=m):
        out = list(stream_chat_completion([Message("user", "hi")], "m", api_key="k", base_url="https://x"))
    assert "".join(out) == "hello"
