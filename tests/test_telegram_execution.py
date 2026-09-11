import asyncio
import pathlib
import pytest
from core import run_store
from server.telegram_channel import TelegramChannel


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.setenv('ZUMBA_TG_ALLOWED_CHAT_IDS', '42')
    monkeypatch.setenv('ZUMBA_TG_VOICE_REPLY', '0')


class API:
    def __init__(self):
        self.sent = []
        self.edits = []
        self.callbacks = []

    async def send_message(self, chat, text, **kwargs):
        self.sent.append((chat, text, kwargs))
        return len(self.sent)

    async def edit_message(self, chat, message, text, **kwargs):
        self.edits.append((chat, message, text))

    async def answer_callback(self, query, text):
        self.callbacks.append((query, text))

    async def send_chat_action(self, *args):
        pass

    async def close(self):
        pass


def message(text, uid=1, actor=42):
    return {'update_id': uid, 'message': {'message_id': uid, 'chat': {'id': 42},
            'from': {'id': actor}, 'text': text}}


def test_dispatch_does_not_block_and_duplicate_executes_once(monkeypatch):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def answer(sid, text, **kwargs):
            calls.append(text)
            started.set()
            await release.wait()
            kwargs['control'].emit('tool_start', id=1, name='test.read', args={})
            kwargs['control'].emit('tool_end', id=1, name='test.read', result='actual evidence', failed=False)
            return 'done'
        monkeypatch.setattr('core.chat_pipeline.aanswer', answer)
        api = API()
        channel = TelegramChannel(api)
        await asyncio.wait_for(channel.dispatch_update(message('do work')), .5)
        await asyncio.wait_for(started.wait(), 1)
        await channel.dispatch_update(message('do work'))
        await channel.dispatch_update(message('/status', 2))
        assert any('running' in text.lower() for _, text, _ in api.sent)
        release.set()
        await channel.drain()
        assert calls == ['do work']
        run = run_store.recent('telegram', 42)[0]
        assert run['status'] == 'completed'
        assert run['delivered'] == 1
        assert any(e['kind'] == 'tool_end' for e in run_store.events(run['id']))
    asyncio.run(scenario())


def test_cancel_is_immediate_and_prevents_late_success(monkeypatch):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        async def answer(sid, text, **kwargs):
            started.set()
            await release.wait()
            return 'late success'
        monkeypatch.setattr('core.chat_pipeline.aanswer', answer)
        api = API()
        channel = TelegramChannel(api)
        await channel.dispatch_update(message('do work'))
        await started.wait()
        await asyncio.wait_for(channel.dispatch_update(message('/cancel', 2)), .5)
        assert run_store.recent('telegram', 42)[0]['status'] == 'cancelled'
        release.set()
        await channel.drain()
        assert not any(text == 'late success' for _, text, _ in api.sent)
    asyncio.run(scenario())


def test_callback_must_belong_to_original_actor(monkeypatch):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        async def answer(*args, **kwargs):
            started.set()
            await release.wait()
            return 'done'
        monkeypatch.setattr('core.chat_pipeline.aanswer', answer)
        api = API()
        channel = TelegramChannel(api)
        await channel.dispatch_update(message('work'))
        await started.wait()
        run = run_store.recent('telegram', 42)[0]
        await channel.dispatch_update({'update_id': 2, 'callback_query': {
            'id': 'callback', 'from': {'id': 99}, 'message': {'chat': {'id': 42}},
            'data': 'cancel:' + run['id']}})
        assert run_store.get(run['id'])['status'] == 'running'
        assert 'owner' in api.callbacks[-1][1].lower()
        release.set()
        await channel.drain()
    asyncio.run(scenario())


def test_failed_delivery_keeps_result_for_status_without_replaying_actions(monkeypatch):
    async def scenario():
        async def answer(*args, **kwargs):
            return 'saved outcome'
        monkeypatch.setattr('core.chat_pipeline.aanswer', answer)
        class FailedAPI(API):
            async def send_message(self, chat, text, **kwargs):
                if text == 'saved outcome':
                    raise TimeoutError('ambiguous send')
                return await super().send_message(chat, text, **kwargs)
        channel = TelegramChannel(FailedAPI())
        await channel.dispatch_update(message('work'))
        await channel.drain()
        run = run_store.recent('telegram', 42)[0]
        assert run['status'] == 'completed'
        assert run['reply'] == 'saved outcome'
        assert run['delivered'] == 0
        assert not run_store.queued('telegram')
    asyncio.run(scenario())


def test_approval_is_owner_bound_one_shot_and_precedes_action(monkeypatch):
    async def scenario():
        prompted = asyncio.Event()
        effects = []
        class ApprovalAPI(API):
            async def send_message(self, chat, text, **kwargs):
                result = await super().send_message(chat, text, **kwargs)
                if text.startswith('Approval needed'):
                    prompted.set()
                return result
        async def answer(sid, text, control):
            await asyncio.to_thread(control.request_approval, 'external__write', {'value': 1})
            effects.append('executed')
            return 'done'
        monkeypatch.setattr('core.chat_pipeline.aanswer', answer)
        api = ApprovalAPI()
        channel = TelegramChannel(api)
        await channel.dispatch_update(message('work'))
        await asyncio.wait_for(prompted.wait(), 2)
        assert effects == []
        _, _, kwargs = next(s for s in api.sent if s[1].startswith('Approval needed'))
        data = kwargs['reply_markup']['inline_keyboard'][0][0]['callback_data']
        callback = {'id': 'approval', 'from': {'id': 99}, 'message': {'chat': {'id': 42}}, 'data': data}
        await channel.dispatch_update({'update_id': 2, 'callback_query': callback})
        assert effects == []
        callback['from']['id'] = 42
        await channel.dispatch_update({'update_id': 3, 'callback_query': callback})
        await channel.drain()
        assert effects == ['executed']
        await channel.dispatch_update({'update_id': 4, 'callback_query': callback})
        assert 'expired' in api.callbacks[-1][1].lower()
    asyncio.run(scenario())


def test_slow_telegram_ack_does_not_delay_model_start(monkeypatch):
    async def scenario():
        started = asyncio.Event()
        class SlowAPI(API):
            async def send_message(self, chat, text, **kwargs):
                if text.startswith('Starting'):
                    await asyncio.Event().wait()
                return await super().send_message(chat, text, **kwargs)
        async def answer(*args, **kwargs):
            started.set()
            return 'done'
        monkeypatch.setattr('core.chat_pipeline.aanswer', answer)
        channel = TelegramChannel(SlowAPI())
        await channel.dispatch_update(message('hello'))
        await asyncio.wait_for(started.wait(), .5)
        await asyncio.wait_for(channel.drain(), .5)
    asyncio.run(scenario())


def test_cancel_during_voice_transcription_does_not_start_agent(monkeypatch):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        called = []
        async def transcribe(*args):
            started.set()
            await release.wait()
            return 'do work'
        async def answer(*args, **kwargs):
            called.append(True)
            return 'done'
        monkeypatch.setattr('core.chat_pipeline.aanswer', answer)
        channel = TelegramChannel(API())
        monkeypatch.setattr(channel, '_handle_voice', transcribe)
        update = message('')
        update['message']['voice'] = {'file_id': 'test', 'duration': 1}
        await channel.dispatch_update(update)
        await started.wait()
        await channel.dispatch_update(message('/cancel', 2))
        release.set()
        await channel.drain()
        assert called == []
    asyncio.run(scenario())
