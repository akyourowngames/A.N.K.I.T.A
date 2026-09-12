"""Tests for god-tier filesystem tools (tmp dirs; rg stubbed where hermetic)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import filesystem as F


def _mk(tmp_path, name="a.txt", content="line1\nline2\nline3\n"):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


# ---- reads ----

def test_read_window_and_errors(tmp_path):
    p = _mk(tmp_path, content="".join(f"L{i}\n" for i in range(1, 11)))
    out = F.fs_read(p, start_line=3, num_lines=3)
    assert "L3" in out and "L5" in out and "more lines below" in out
    assert F.fs_read(str(tmp_path / "nope.txt")).startswith("ERROR")
    assert F.fs_read("").startswith("ERROR")


def test_read_symbol_context(tmp_path):
    p = _mk(tmp_path, "m.py", "import os\n\n\ndef foo():\n    pass\n\n\ndef bar():\n    x = 1\n" * 4)
    out = F.fs_read(p, start_line=20, num_lines=3)
    assert "scope" in out and "import" in out


def test_grep_python_fallback(tmp_path, monkeypatch):
    _mk(tmp_path, "a.py", "hello world\nfoo bar\n")
    _mk(tmp_path, "b.txt", "nothing here\n")
    monkeypatch.setattr(F, "_rg", lambda: "")
    out = F.fs_grep("hello", str(tmp_path))
    assert "a.py:1" in out
    assert F.fs_grep("", str(tmp_path)).startswith("ERROR")
    assert F.fs_grep("hello", str(tmp_path / "nope")).startswith("ERROR")


def test_grep_rg_path_if_available(tmp_path):
    import shutil
    if not shutil.which("rg"):
        return
    _mk(tmp_path, "a.py", "needle here\n")
    out = F.fs_grep("needle", str(tmp_path))
    assert "a.py:1" in out


def test_find_ranking(tmp_path, monkeypatch):
    (tmp_path / "builtin.py").write_text("x")
    (tmp_path / "my_builtin_helper.py").write_text("x")
    (tmp_path / "other.txt").write_text("x")
    monkeypatch.setattr(F, "_find_rg", lambda root: None)
    out = F.fs_find("builtin", str(tmp_path))
    first = out.index("builtin.py")
    assert first < out.index("my_builtin_helper.py")
    assert "other.txt" not in out
    assert F.fs_find("", str(tmp_path)).startswith("ERROR")


def test_list_info_glob_tree(tmp_path):
    _mk(tmp_path, "a.py", "x")
    (tmp_path / "sub").mkdir()
    assert "[file] a.py" in F.fs_list(str(tmp_path))
    assert "[dir]  sub/" in F.fs_list(str(tmp_path))
    assert "Type: file" in F.fs_info(str(tmp_path / "a.py"))
    assert "a.py" in F.fs_glob("*.py", str(tmp_path))
    tree = F.fs_tree(str(tmp_path), max_depth=2)
    assert "sub/" in tree and "a.py" in tree
    assert F.fs_list(str(tmp_path / "nope")).startswith("ERROR")
    assert F.fs_glob("", str(tmp_path)).startswith("ERROR")


# ---- writes ----

def test_write_create_overwrite_dryrun(tmp_path):
    p = str(tmp_path / "n.txt")
    assert "Created" in F.fs_write(p, "hi\n")
    assert "Overwrote" in F.fs_write(p, "hi\nthere\n")
    assert "DRY RUN" in F.fs_write(p, "other\n", dry_run=True)
    assert Path(p).read_text() == "hi\nthere\n"
    assert F.fs_write("", "x").startswith("ERROR")


def test_edit_unique_repeat_occurrence(tmp_path):
    p = _mk(tmp_path, content="foo bar\nfoo baz\n")
    out = F.fs_edit(p, "foo", "qux")
    assert out.startswith("ERROR") and "2 locations" in out
    out2 = F.fs_edit(p, "foo", "qux", occurrence=2)
    assert out2.startswith("Edited")
    assert Path(p).read_text() == "foo bar\nqux baz\n"
    assert "DRY RUN" in F.fs_edit(p, "qux", "q", dry_run=True)
    assert F.fs_edit(p, "zzz-nope", "q").startswith("ERROR")


def test_edit_suggest_closest(tmp_path):
    p = _mk(tmp_path, content="alpha\nbeta\ngamma\ndelta\n")
    out = F.fs_edit(p, "beta\ngamma\nGAMMA-typo", "x")
    assert "Did you mean" in out and "beta" in out


def test_insert_replace_lines(tmp_path):
    p = _mk(tmp_path, content="a\nb\nc\n")
    assert "Inserted after line 1" in F.fs_insert(p, 1, "a2")
    assert Path(p).read_text() == "a\na2\nb\nc\n"
    assert "Replaced lines 2-3" in F.fs_replace_lines(p, 2, 3, "B\nC")
    assert Path(p).read_text() == "a\nB\nC\nc\n"
    assert F.fs_replace_lines(p, 9, 9, "x").startswith("ERROR")
    assert F.fs_insert(p, 99, "x").startswith("ERROR")


def test_apply_patch_add_update_delete(tmp_path):
    a = str(tmp_path / "pa.txt")
    out = F.fs_apply_patch(f"*** Add File: {a}\n+one\n+two\n")
    assert "Created" in out and Path(a).read_text() == "one\ntwo\n"
    out2 = F.fs_apply_patch(f"*** Update File: {a}\n@@ one\n-one\n+uno\n two\n")
    assert "Patched" in out2 and Path(a).read_text() == "uno\ntwo\n"
    # atomic failure: bad anchor leaves file untouched
    bad = f"*** Update File: {a}\n@@ nope-anchor\n-x\n+y\n"
    assert F.fs_apply_patch(bad).startswith("ERROR")
    assert Path(a).read_text() == "uno\ntwo\n"
    # add existing refused
    assert F.fs_apply_patch(f"*** Add File: {a}\n+z\n").startswith("ERROR")
    # dry run validates only
    assert "DRY RUN" in F.fs_apply_patch(f"*** Delete File: {a}\n", dry_run=True)
    assert Path(a).exists()
    assert "Deleted" in F.fs_apply_patch(f"*** Delete File: {a}\n")
    assert not Path(a).exists()
    assert F.fs_apply_patch("").startswith("ERROR")


def test_batch_success_and_rollback(tmp_path):
    b, c = str(tmp_path / "b.txt"), str(tmp_path / "c.txt")
    out = F.fs_batch([{"action": "write", "path": b, "content": "1"},
                      {"action": "write", "path": c, "content": "2"}])
    assert "2 operation(s)" in out
    bad = F.fs_batch([{"action": "write", "path": b, "content": "CHANGED"},
                      {"action": "edit", "path": c, "old_text": "zzz", "new_text": "y"}])
    assert bad.startswith("ERROR") and "rolled back" in bad
    assert Path(b).read_text() == "1"
    assert F.fs_batch("nope").startswith("ERROR")


def test_undo_mkdir_move_delete(tmp_path):
    p = _mk(tmp_path, content="v1\n")
    F.fs_write(p, "v2\n")
    assert "Restored" in F.fs_undo(p)
    assert Path(p).read_text() == "v1\n"
    d = str(tmp_path / "sub" / "deep")
    assert "Created directory" in F.fs_mkdir(d)
    m = str(tmp_path / "moved.txt")
    assert "Moved" in F.fs_move(p, m)
    assert F.fs_delete(m).startswith("ERROR")  # confirm required
    assert "Deleted" in F.fs_delete(m, confirm=True)
    assert F.fs_undo(str(tmp_path / "never.txt")).startswith("ERROR")


def test_kill_switch_and_dispatch(monkeypatch):
    import asyncio
    import mcpclient.builtin as _b
    monkeypatch.delenv("ZUMBA_NO_FS", raising=False)
    names = [t["function"]["name"] for t in _b.visible_tools()]
    for n in ("__fs_read", "__fs_grep", "__fs_find", "__fs_edit", "__fs_apply_patch", "__fs_delete"):
        assert any(x.endswith(n) for x in names), n
    monkeypatch.setenv("ZUMBA_NO_FS", "1")
    names2 = [t["function"]["name"] for t in _b.visible_tools()]
    assert not any("__fs_" in n for n in names2)

    class _Mgr:
        meta_state = {}

    async def go():
        assert (await _b.handle(_Mgr(), "fs_read", {"path": ""})).startswith("ERROR")
        assert (await _b.handle(_Mgr(), "fs_grep", {"pattern": ""})).startswith("ERROR")
        assert (await _b.handle(_Mgr(), "fs_find", {"name": ""})).startswith("ERROR")
        monkeypatch.setattr(F, "fs_list", lambda *a, **k: "[Directory: .]")
        assert "Directory" in await _b.handle(_Mgr(), "fs_list", {})
        monkeypatch.setattr(F, "fs_write", lambda *a, **k: "Created x")
        assert "Created" in await _b.handle(_Mgr(), "fs_write", {"path": "x", "content": "y"})
        assert (await _b.handle(_Mgr(), "fs_edit", {"path": "x"})).startswith("ERROR")
        assert (await _b.handle(_Mgr(), "fs_delete", {"path": "x"})).startswith("ERROR")
    monkeypatch.delenv("ZUMBA_NO_FS", raising=False)
    asyncio.run(go())
