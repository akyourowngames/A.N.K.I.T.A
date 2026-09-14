# Scoped local file tools

The built-in file tools read, list, search, create and edit files directly. They
are available to the tool planner without sending file work through a shell.
`fs_read`, `fs_list`, `fs_grep`, `fs_find`, `fs_info`, `fs_glob` and `fs_tree` use
the `read` policy; mutations use the existing `local` policy.

## Workspace and private data

The workspace defaults to the process working directory. Set `ZUMBA_FS_ROOT` to
another directory before starting Zumba to choose the file workspace. Relative
tool paths are interpreted from that directory. Absolute paths must stay inside
it. Parent traversal, symlinks and Windows junctions cannot escape the workspace,
including when creating a new file through a linked parent directory.

The complete `~/.zumba` directory and any `ZUMBA_MEMORY_HOME` directory are private
even when they sit inside the workspace. This covers databases, SQLite sidecar
files, chat logs and future private store files. Both their named paths and their
resolved locations are blocked. Files with multiple hard links are also blocked
because a hard link has no canonical target with which to establish scope.
Search and directory tools omit inaccessible entries. Moving an ancestor of a
private store, or moving/deleting the workspace itself, is refused.

The policy also applies to backups, undo, batches, patches and the other existing
file tools. Existing audit logging remains internal to Zumba. This is a file-tool
policy, not an operating-system sandbox for shell commands or other processes.
It does not provide isolation from a concurrent process that changes links while
a file operation is running.

## Examples

- Read a window: `fs_read(path="notes.txt", start_line=1, num_lines=80)`.
- List: `fs_list(path=".")`.
- Search content: `fs_grep(pattern="TODO", path="src")`; a file path searches
  only that file.
- Write: `fs_write(path="notes.txt", content="Meeting notes\n")`.
- Edit: `fs_edit(path="notes.txt", old_text="Meeting notes", new_text="Decisions")`.

Edits fail with `ERROR:` when text is missing or ambiguous, including multiple
whitespace-normalized matches. An explicit `occurrence` can select an exact
repeated match; otherwise add surrounding text to make the match unique. Write
tools retain their existing dry-run, backup and diff behavior. All file-tool
failures use the `ERROR:` convention.

Set either `ZUMBA_NO_FILES=1` or its existing alias `ZUMBA_NO_FS=1` to hide and
disable all file tools. The flags also block direct calls to the Python helpers.

## Verification

Run `python -m pytest tests/test_filesystem.py tests/test_filesystem_scope.py`.
Tests establish temporary scoped workspaces and cover windowed reads, discovery,
both search backends, unique and ambiguous edits, existing mutations, parent and
absolute escapes, symlinks/junctions, hard links, private stores, backup escapes,
patch validation, and both kill switches through direct and registered calls.
