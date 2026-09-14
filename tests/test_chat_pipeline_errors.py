import pytest

from core.models import Message


def test_provider_failure_keeps_tool_evidence_without_saving_error_as_conversation(monkeypatch):
    from core import chat_pipeline as pipeline, config, api_client
    import memory
    saved = []
    monkeypatch.setattr(config, 'get_api_key', lambda **kw: 'test')
    monkeypatch.setattr(pipeline.store, 'get_session', lambda sid: {'id': sid})
    monkeypatch.setattr(pipeline.store, 'add_message', lambda sid, role, content: saved.append((role, content)))
    monkeypatch.setattr(pipeline, 'build_messages', lambda *args: [Message(role='user', content='question')])
    monkeypatch.setattr(pipeline, 'recall_block', lambda *args: '')
    def unavailable(*args, transcript=None, **kwargs):
        transcript.append(Message(role='tool', content='verified result'))
        raise pipeline.ModelUnavailableError('provider still unavailable')
    monkeypatch.setattr(pipeline, '_agent_answer', unavailable)
    monkeypatch.setattr(api_client, 'chat_completion', lambda *a, **kw: pytest.fail('must not restart failed tool turn'))
    monkeypatch.setattr(memory, 'get_memory', lambda: pytest.fail('error must not become saved conversation'))
    with pytest.raises(pipeline.ModelUnavailableError):
        pipeline.answer('test', 'question', system='test')
    assert saved == [('user', 'question'), ('tool', 'verified result')]


def test_plain_answer_retries_provider_overload(monkeypatch):
    from core import api_client, chat_pipeline as pipeline
    from core.models import ChatResult
    calls = []
    def provider(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise api_client.KiloError('overloaded', status_code=503)
        return ChatResult(content='recovered')
    monkeypatch.setattr(api_client, 'chat_completion', provider)
    monkeypatch.setattr('time.sleep', lambda seconds: None)
    stages = []
    result = pipeline._plain_answer([Message(role='user', content='question')], 'm', 'test', 100, 0, on_stage=stages.append)
    assert result.content == 'recovered'
    assert len(calls) == 2
    assert 'attempt 1' in stages[0] and 'attempt 2' in stages[1]
