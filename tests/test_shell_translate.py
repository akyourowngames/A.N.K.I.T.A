"""Shell unix->PS translation (Friday pattern, ls-flag hardened)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shelltool import translate_to_powershell


def test_ls_la_becomes_force_not_broken_flag():
    out = translate_to_powershell("ls -la")
    assert "Get-ChildItem" in out
    assert "-la" not in out
    assert "-Force" in out


def test_ls_path_kept():
    out = translate_to_powershell("ls C:/Users/anime")
    assert "Get-ChildItem" in out and "C:/Users/anime" in out


def test_common_unix_mapped():
    assert "Get-Content" in translate_to_powershell("cat file.txt")
    assert "Get-Location" in translate_to_powershell("pwd")
    assert "Select-String" in translate_to_powershell("grep foo bar.txt")
    assert "Remove-Item" in translate_to_powershell("rm -rf ./x")
    assert "Get-Command" in translate_to_powershell("which python")


def test_powershell_passthrough():
    cmd = "Get-ChildItem -Recurse"
    assert translate_to_powershell(cmd) == cmd


def test_run_ls_la_actually_works():
    import shelltool
    res = shelltool.run("ls -la", timeout_s=20)
    assert res.get("exit_code") == 0, res
    assert "ERROR" not in (res.get("stdout") or "")[:6] or "exit=0" in shelltool.format_result(res)


def test_soul_intent_and_typo_hint():
    import main
    assert main._soul_show_intent("list me what you have drafted") is True
    assert main._soul_show_intent("show my soul") is True
    assert main._soul_show_intent("hello there") is False
    import difflib
    assert difflib.get_close_matches("/sould", ["/soul", "/models"], n=1, cutoff=0.6)
