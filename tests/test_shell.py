"""Tests for the god-mode shell tool (real powershell, no network)."""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shelltool
from shelltool import ShellSession


def _fresh() -> ShellSession:
    s = ShellSession()
    s.start()
    return s


def test_cwd_persists_across_calls(tmp_path):
    s = _fresh()
    try:
        target = str(tmp_path)
        r = s.run(f"Set-Location -LiteralPath '{target}'; Write-Output ok")
        assert r["exit_code"] == 0, r
        r2 = s.run("Write-Output $PWD")
        assert target.lower() in r2["stdout"].lower(), r2
        assert s.cwd.lower() == target.lower()
    finally:
        s.close()


def test_env_var_persists_across_calls():
    s = _fresh()
    try:
        assert s.run('$env:ZUMBA_TEST_SHELL_X = "persist-42"')["exit_code"] == 0
        r = s.run('Write-Output $env:ZUMBA_TEST_SHELL_X')
        assert "persist-42" in r["stdout"], r
    finally:
        s.close()


def test_timeout_returns_partial_and_recovers():
    s = _fresh()
    try:
        t0 = time.time()
        r = s.run('Start-Sleep -Seconds 30; Write-Output "never-seen"', timeout_s=3)
        assert time.time() - t0 < 25, "session-death/timeout path must not wait out the sleep"
        assert r["timed_out"] is True
        assert "timed out" in r["stdout"].lower() or "restarted" in r["stdout"].lower()
        r2 = s.run('Write-Output "alive-again"')
        assert r2["exit_code"] == 0 and "alive-again" in r2["stdout"], r2
    finally:
        s.close()


def test_truncation_head_tail():
    text = "x" * 5000 + "MID" + "y" * 5000
    out, trunc = shelltool.truncate_output(text, cap=1000)
    assert trunc is True
    assert len(out) < len(text)
    assert out.startswith("x" * 100) and out.rstrip().endswith("y" * 100)
    short, trunc2 = shelltool.truncate_output("tiny", cap=1000)
    assert trunc2 is False and short == "tiny"


def test_background_job_lifecycle():
    s = _fresh()
    try:
        r = s.run('Write-Output "bg-hello"', run_in_background=True)
        assert r.get("job_id"), r
        jid = r["job_id"]
        assert any(j["job_id"] == jid for j in s.job_list())
        deadline = time.time() + 20
        while time.time() < deadline:
            st = [j for j in s.job_list() if j["job_id"] == jid][0]
            if not st["running"]:
                break
            time.sleep(0.3)
        out = s.job_output(jid)
        assert "bg-hello" in out, out
        assert "unknown job" in s.job_kill("nope-123")
    finally:
        s.close()


def test_no_shell_hides_tools(monkeypatch):
    from mcpclient import builtin

    monkeypatch.setenv("ZUMBA_NO_SHELL", "1")
    names = [t["function"]["name"] for t in builtin.visible_tools()]
    assert names and not any(n.endswith(("__shell_run", "__shell_jobs", "__shell_kill")) for n in names)
    monkeypatch.delenv("ZUMBA_NO_SHELL", raising=False)
    names2 = [t["function"]["name"] for t in builtin.visible_tools()]
    assert any(n.endswith("__shell_run") for n in names2)


def test_audit_log_written(tmp_path, monkeypatch):
    log = tmp_path / "audit.log"
    monkeypatch.setattr(shelltool, "_audit_log_path", lambda: str(log))
    s = _fresh()
    try:
        s.run('Write-Output "audit-me"')
    finally:
        s.close()
    content = log.read_text(encoding="utf-8", errors="replace")
    assert "audit-me" in content and "exit=" in content


def test_format_result_conventions():
    ok = shelltool.format_result({"exit_code": 0, "stdout": "hi\n", "stderr": "", "truncated": False, "duration_ms": 12, "timed_out": False})
    assert not ok.startswith("ERROR") and "exit=0" in ok
    bad = shelltool.format_result({"exit_code": 3, "stdout": "nope\n", "stderr": "", "truncated": False, "duration_ms": 5, "timed_out": False})
    assert bad.startswith("ERROR:")
    to = shelltool.format_result({"exit_code": None, "stdout": "partial", "stderr": "", "truncated": False, "duration_ms": 5, "timed_out": True})
    assert to.startswith("ERROR:")
