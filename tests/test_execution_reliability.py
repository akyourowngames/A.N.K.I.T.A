import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.models import ChatResult
from mcpclient.agent import run_agent_loop


def calls(*names):
    return ChatResult(content='', raw={'choices': [{'message': {'tool_calls': [
        {'id': str(i), 'type': 'function', 'function': {'name': n, 'arguments': '{}'}}
        for i, n in enumerate(names)]}}]})


def test_cancel_after_first_tool_prevents_second_side_effect():
    from core.execution import ExecutionControl, ExecutionCancelled
    control = ExecutionControl()
    executed = []
    def execute(name, args):
        executed.append(name)
        control.cancel()
        return 'first result'
    transcript = []
    with pytest.raises(ExecutionCancelled):
        run_agent_loop([], 'model', lambda *a, **k: calls('first', 'second'), execute, [],
                       control=control, transcript_out=transcript)
    assert executed == ['first']
    assert any(m.role == 'tool' and m.content == 'first result' for m in transcript)


def test_real_tool_events_wrap_execution_and_include_failure():
    from core.execution import ExecutionControl
    events = []
    control = ExecutionControl(on_event=lambda kind, data: events.append((kind, data)))
    responses = iter([calls('read'), ChatResult(content='Tool failed')])
    def execute(name, args):
        assert events[-1][0] == 'tool_start'
        raise TimeoutError('network timeout')
    result = run_agent_loop([], 'model', lambda *a, **k: next(responses), execute, [], control=control)
    assert result.content == 'Tool failed'
    assert [k for k, _ in events if k.startswith('tool_')] == ['tool_start', 'tool_end']
    assert events[[k for k, _ in events].index('tool_end')][1]['failed'] is True


def test_run_store_deduplicates_and_keeps_terminal_state(tmp_path, monkeypatch):
    from core import run_store, store
    monkeypatch.setattr(store, 'db_path', lambda: tmp_path / 'zumba.db')
    first = run_store.create('telegram', '42', 7, {'message': {'text': 'hello'}})
    again = run_store.create('telegram', '42', 7, {'message': {'text': 'hello'}})
    assert first['id'] == again['id']
    assert run_store.claim(first['id'])
    assert not run_store.claim(first['id'])
    run_store.finish(first['id'], 'cancelled', 'Cancelled')
    run_store.finish(first['id'], 'completed', 'Late worker result')
    assert run_store.get(first['id'])['status'] == 'cancelled'
    assert run_store.get(first['id'])['reply'] == 'Cancelled'


def test_restart_marks_inflight_interrupted_without_replaying(tmp_path, monkeypatch):
    from core import run_store, store
    monkeypatch.setattr(store, 'db_path', lambda: tmp_path / 'zumba.db')
    queued = run_store.create('telegram', '42', 8, {})
    active = run_store.create('telegram', '42', 9, {})
    run_store.claim(active['id'])
    run_store.record(active['id'], 'tool_start', {'name': 'purchase'})
    run_store.recover('telegram')
    assert run_store.get(active['id'])['status'] == 'interrupted'
    assert [r['id'] for r in run_store.queued('telegram')] == [queued['id']]
    assert run_store.events(active['id'])[0]['kind'] == 'tool_start'


def test_mcp_sync_bridge_accepts_concurrent_callers(monkeypatch):
    import mcpclient.manager as bridge
    import asyncio
    bridge.shutdown()
    monkeypatch.setattr(bridge, 'list_servers', lambda: {})
    async def call(self, name, args, timeout=None):
        await asyncio.sleep(.02)
        return args['value']
    monkeypatch.setattr(bridge.MCPManager, 'call_tool', call)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda n: bridge.run_tool('test__read', {'value': str(n)}), range(2)))
        assert results == ['0', '1']
    finally:
        bridge.shutdown()


def test_repeat_reads_are_allowed_but_identical_writes_are_not_replayed():
    from core.execution import ExecutionControl
    for access, expected in [('read', 2), ('approval', 1)]:
        control = ExecutionControl()
        control.access = lambda name: access
        executed = []
        responses = iter([calls('tool'), calls('tool'), ChatResult(content='done')])
        run_agent_loop([], 'model', lambda *a, **k: next(responses),
                       lambda *a: executed.append(a) or 'result', [], control=control)
        assert len(executed) == expected


def test_unknown_tool_requires_approval_but_declared_read_does_not():
    from mcpclient.manager import MCPManager
    mgr = MCPManager(config={})
    assert mgr.tool_access('unknown__action') == 'approval'
    assert mgr.tool_access('zumba__web_search') == 'read'
    assert mgr.tool_access('zumba__shell_run') == 'approval'
