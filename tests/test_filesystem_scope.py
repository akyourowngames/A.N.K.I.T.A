"""File tools must never cross their configured workspace or private stores."""

import os
from pathlib import Path

import pytest

from tools import filesystem as F


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.delenv("ZUMBA_FS_ROOT", raising=False)
    monkeypatch.delenv("ZUMBA_NO_FS", raising=False)
    monkeypatch.delenv("ZUMBA_NO_FILES", raising=False)
    monkeypatch.setattr(F, "_audit", lambda *args: None)
    return root


def test_default_scope_rejects_parent_and_absolute_paths(workspace):
    outside = workspace.parent / "outside.txt"
    outside.write_text("private needle")
    for path in ("../outside.txt", str(outside)):
        assert F.fs_read(path).startswith("ERROR:")
        assert F.fs_write(path, "changed").startswith("ERROR:")
        assert F.fs_edit(path, "private", "changed").startswith("ERROR:")
        assert F.fs_info(path).startswith("ERROR:")
        assert F.fs_grep("needle", path).startswith("ERROR:")
    assert F.fs_list("..").startswith("ERROR:")
    assert F.fs_grep("needle", "..").startswith("ERROR:")
    assert outside.read_text() == "private needle"


def test_configured_scope_is_base_for_relative_paths(workspace, monkeypatch):
    project = workspace / "project"
    project.mkdir()
    monkeypatch.setenv("ZUMBA_FS_ROOT", str(project))
    assert "Created" in F.fs_write("notes.txt", "hello needle")
    assert (project / "notes.txt").read_text() == "hello needle"
    assert "hello needle" in F.fs_read("notes.txt")
    assert "notes.txt" in F.fs_list()
    assert "notes.txt:1" in F.fs_grep("needle")
    assert F.fs_write("../escape.txt", "x").startswith("ERROR:")


@pytest.mark.parametrize("backend", ["rg", "python"])
def test_search_file_does_not_search_its_siblings(workspace, monkeypatch, backend):
    if backend == "python":
        monkeypatch.setattr(F, "_rg", lambda: "")
    (workspace / "public.txt").write_text("needle public")
    (workspace / "other.txt").write_text("needle unrelated")
    out = F.fs_grep("needle", "public.txt")
    assert "needle public" in out
    assert "unrelated" not in out


@pytest.mark.parametrize("backend", ["rg", "python"])
def test_private_stores_hidden_even_when_inside_scope(workspace, monkeypatch, backend):
    if backend == "python":
        monkeypatch.setattr(F, "_rg", lambda: "")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: workspace))
    private = workspace / ".zumba"
    private.mkdir()
    (private / "zumba.db").write_text("private needle")
    memory = workspace / "memory-store"
    memory.mkdir()
    (memory / "ChatLog.json").write_text("private needle")
    monkeypatch.setenv("ZUMBA_MEMORY_HOME", str(memory))
    (workspace / "public.txt").write_text("public needle")
    for store, filename in ((private, "zumba.db"), (memory, "ChatLog.json")):
        assert F.fs_read(str(store / filename)).startswith("ERROR:")
        assert F.fs_write(str(store / filename), "x").startswith("ERROR:")
        assert F.fs_list(str(store)).startswith("ERROR:")
    for out in (F.fs_list(), F.fs_tree(), F.fs_glob("*"), F.fs_find("zumba.db"), F.fs_grep("needle")):
        assert "private needle" not in out
        assert "[dir]  .zumba/" not in out
        assert "ChatLog.json" not in out
    assert "public needle" in F.fs_grep("needle")
    assert F.fs_move(str(workspace), str(workspace.parent / "moved")).startswith("ERROR:")


def _directory_link(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            raise


@pytest.mark.parametrize("backend", ["rg", "python"])
def test_link_escape_blocked_for_reads_writes_and_discovery(workspace, monkeypatch, backend):
    if backend == "python":
        monkeypatch.setattr(F, "_rg", lambda: "")
    outside = workspace.parent / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("private needle")
    _directory_link(workspace / "escape", outside)
    assert F.fs_read("escape/secret.txt").startswith("ERROR:")
    assert F.fs_write("escape/new.txt", "x").startswith("ERROR:")
    assert F.fs_edit("escape/secret.txt", "private", "x").startswith("ERROR:")
    assert F.fs_grep("needle", "escape").startswith("ERROR:")
    assert F.fs_list("escape").startswith("ERROR:")
    for out in (F.fs_tree(), F.fs_glob("*"), F.fs_find("secret"), F.fs_grep("needle")):
        assert "secret.txt" not in out
        assert "private needle" not in out
    assert not (outside / "new.txt").exists()
    assert (outside / "secret.txt").read_text() == "private needle"


def test_backup_link_cannot_escape_workspace(workspace):
    outside = workspace.parent / "outside"
    outside.mkdir()
    _directory_link(workspace / ".zumba_backups", outside)
    (workspace / "note.txt").write_text("before")
    assert F.fs_write("note.txt", "after").startswith("ERROR:")
    assert (workspace / "note.txt").read_text() == "before"
    assert list(outside.iterdir()) == []


def test_normalized_ambiguous_edit_fails_without_changing_file(workspace):
    target = workspace / "note.txt"
    target.write_text("alpha   \nalpha  \n")
    out = F.fs_edit("note.txt", "alpha\t", "changed")
    assert out.startswith("ERROR:") and "2 locations" in out
    assert target.read_text() == "alpha   \nalpha  \n"


@pytest.mark.parametrize("flag", ["ZUMBA_NO_FS", "ZUMBA_NO_FILES"])
def test_kill_switch_blocks_direct_calls(workspace, monkeypatch, flag):
    monkeypatch.setenv(flag, "1")
    assert not F.enabled()
    assert F.fs_write("note.txt", "blocked").startswith("ERROR:")
    assert F.fs_list().startswith("ERROR:")
    assert not (workspace / "note.txt").exists()


def test_patch_rejects_escape_before_any_write(workspace):
    out = F.fs_apply_patch("*** Add File: public.txt\n+okay\n*** Add File: ../outside.txt\n+escape\n")
    assert out.startswith("ERROR:")
    assert not (workspace / "public.txt").exists()
    assert not (workspace.parent / "outside.txt").exists()


def test_hardlink_to_private_file_is_not_readable(workspace):
    outside = workspace.parent / "private.db"
    outside.write_text("private needle")
    os.link(outside, workspace / "alias.txt")
    assert F.fs_read("alias.txt").startswith("ERROR:")
    assert F.fs_write("alias.txt", "changed").startswith("ERROR:")
    assert "private needle" not in F.fs_grep("needle")
    assert "alias.txt" not in F.fs_list()
    assert outside.read_text() == "private needle"


def test_custom_private_store_alias_and_ancestor_cannot_be_moved(workspace, monkeypatch):
    parent = workspace / "container"
    parent.mkdir()
    private = parent / "memory"
    private.mkdir()
    (private / "ChatLog.json").write_text("private needle")
    monkeypatch.setenv("ZUMBA_MEMORY_HOME", str(private))
    _directory_link(workspace / "alias", private)
    assert F.fs_read("alias/ChatLog.json").startswith("ERROR:")
    assert F.fs_move("container", "moved").startswith("ERROR:")
    assert F.fs_batch([{"action": "move", "source": "container", "destination": "moved"}]).startswith("ERROR:")
    assert (private / "ChatLog.json").read_text() == "private needle"


def test_extended_mutations_cannot_escape_scope(workspace):
    outside = workspace.parent / "outside.txt"
    outside.write_text("before\n")
    (workspace / "inside.txt").write_text("inside\n")
    for result in (
        F.fs_insert(str(outside), 1, "changed"),
        F.fs_replace_lines(str(outside), 1, 1, "changed"),
        F.fs_undo(str(outside)),
        F.fs_delete(str(outside), confirm=True),
        F.fs_move("inside.txt", str(outside)),
        F.fs_move(str(outside), "moved.txt"),
        F.fs_mkdir("../new-dir"),
    ):
        assert result.startswith("ERROR:")
    assert outside.read_text() == "before\n"
    assert (workspace / "inside.txt").read_text() == "inside\n"


def test_both_kill_switches_hide_and_block_registered_tools(workspace, monkeypatch):
    import asyncio
    import mcpclient.builtin as builtin

    class Manager:
        meta_state = {}

    for flag in ("ZUMBA_NO_FS", "ZUMBA_NO_FILES"):
        monkeypatch.setenv(flag, "1")
        assert not any("__fs_" in tool["function"]["name"] for tool in builtin.visible_tools())
        result = asyncio.run(builtin.handle(Manager(), "fs_write", {"path": "new.txt", "content": "x"}))
        assert result.startswith("ERROR:")
        assert not (workspace / "new.txt").exists()
        monkeypatch.delenv(flag)
