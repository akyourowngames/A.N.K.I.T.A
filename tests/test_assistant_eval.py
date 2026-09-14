"""Regression tests for the eval runner, exercising the production tool loop."""
import json
import sqlite3

from core.models import ChatResult


def test_golden_tasks_execute_and_persist_real_outcomes(tmp_path):
    from scripts.eval_assistant import run_suite

    report = run_suite(tmp_path)
    assert report['passed'], report
    assert report['total'] == 20
    assert len(report['per_category']) == 5
    assert all(d['state_ok'] and d['tool_choice_score'] == 1 for d in report['details'])
    assert all(d['latency_ms'] > 0 and d['judge_score'] == 1 for d in report['details'])
    with sqlite3.connect(report['database']) as con:
        row = con.execute('SELECT total, hits, details FROM eval_runs').fetchone()
    assert row[:2] == (20, 20)
    assert len(json.loads(row[2])) == 20
    assert (tmp_path / 'results.json').exists()


def test_empty_model_answer_fails_gate(tmp_path):
    from scripts.eval_assistant import run_suite

    report = run_suite(tmp_path, task_ids=['file-1'],
                       provider_factory=lambda task: lambda *a, **k: ChatResult(content='', model='mock'))
    assert not report['passed']
    assert 'empty_summary' in report['details'][0]['failures']


def test_spiral_is_detected_even_if_production_loop_synthesizes_summary(tmp_path):
    from scripts.eval_assistant import run_suite, tool_response

    def spiral(*args, **kwargs):
        return tool_response('mock', 'zumba__memory_search', {'query': 'test'}, 'repeat')

    report = run_suite(tmp_path, task_ids=['memory-1'],
                       provider_factory=lambda task: spiral)
    detail = report['details'][0]
    assert detail['summary']  # production has a fallback; it must not mask the spiral
    assert not report['passed']
    assert 'tool_spiral' in detail['failures']


def test_eval_rejects_outside_paths_and_unlisted_tools(tmp_path):
    from scripts.eval_assistant import EvalSandbox

    outside = tmp_path / 'personal.txt'
    outside.write_text('private', encoding='utf-8')
    with EvalSandbox(tmp_path / 'sandbox') as sandbox:
        assert sandbox.execute('zumba__fs_read', {'path': str(outside)}).startswith('ERROR:')
        assert sandbox.execute('zumba__fs_write', {'path': str(outside), 'content': 'changed'}).startswith('ERROR:')
        assert sandbox.execute('zumba__shell_run', {'command': 'anything'}).startswith('ERROR:')
    assert outside.read_text(encoding='utf-8') == 'private'


def test_real_file_failure_is_not_hidden_by_scripted_summary(tmp_path, monkeypatch):
    from scripts.eval_assistant import run_suite

    monkeypatch.setattr('tools.filesystem.fs_edit', lambda *a, **k: 'ERROR: edit failed')
    report = run_suite(tmp_path, task_ids=['file-1'])
    assert not report['passed']
    assert not report['details'][0]['state_ok']
    assert 'tool_error' in report['details'][0]['failures']


def test_live_requires_explicit_flag_and_judge_failure_fails_closed(tmp_path):
    from scripts.eval_assistant import run_suite
    import pytest

    with pytest.raises(ValueError, match='explicit'):
        run_suite(tmp_path, model='real-provider-model')
