import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import engine
from tools import fs_ops
from tools import terminal_ops

class FsOpsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "a.txt").write_text("hello\nworld\n", encoding="utf-8")
        (self.root / "dir").mkdir(parents=True, exist_ok=True)
        (self.root / "dir" / "b.txt").write_text("groq key\n", encoding="utf-8")
        (self.root / ".venv").mkdir(parents=True, exist_ok=True)
        (self.root / ".venv" / "hidden.txt").write_text("secret groq\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_search_text(self) -> None:
        out = fs_ops.search_text(self.root, "groq", ".", 20)
        self.assertTrue(any("b.txt" in m for m in out["matches"]))

    def test_write_edit_read(self) -> None:
        fs_ops.write_file(self.root, "x.txt", "alpha beta", overwrite=True)
        fs_ops.edit_file(self.root, "x.txt", "beta", "gamma", replace_all=False)
        read = fs_ops.read_file(self.root, "x.txt")
        self.assertIn("gamma", read["content"])

    def test_rename_move_copy_delete(self) -> None:
        fs_ops.rename_path(self.root, "a.txt", "a1.txt")
        self.assertTrue((self.root / "a1.txt").exists())

        fs_ops.move_path(self.root, "a1.txt", "moved/a2.txt")
        self.assertTrue((self.root / "moved" / "a2.txt").exists())

        fs_ops.copy_path(self.root, "moved/a2.txt", "copy/a2.txt", overwrite=True)
        self.assertTrue((self.root / "copy" / "a2.txt").exists())

        fs_ops.delete_path(self.root, "copy/a2.txt")
        self.assertFalse((self.root / "copy" / "a2.txt").exists())

    def test_path_escape_blocked(self) -> None:
        with self.assertRaises(ValueError):
            fs_ops.read_file(self.root, "../outside.txt")

    def test_default_ignores_heavy_dirs(self) -> None:
        listed = fs_ops.list_files(self.root, ".", 200)
        paths = [e["path"] for e in listed["entries"]]
        self.assertFalse(any(p.startswith(".venv/") for p in paths))

        searched = fs_ops.search_text(self.root, "secret", ".", 50)
        self.assertFalse(any(".venv/" in m for m in searched["matches"]))

    def test_apply_patch_multi_file(self) -> None:
        patch = """*** Begin Patch
*** Update File: a.txt
@@
-hello
+hello patched
*** Add File: new.txt
+new line
*** Move to: moved.txt
*** Update File: dir/b.txt
@@
-groq key
+groq secret
*** End Patch"""
        # The add + move hunk above is invalid because Move belongs to update hunk.
        # Use a proper multi-hunk patch:
        patch = """*** Begin Patch
*** Update File: a.txt
@@
-hello
+hello patched
*** Add File: new.txt
+new line
*** Update File: dir/b.txt
*** Move to: dir/b2.txt
@@
-groq key
+groq secret
*** Delete File: dir/b2.txt
*** End Patch"""
        summary = fs_ops.apply_patch(self.root, patch)
        self.assertIn("a.txt", summary["modified"])
        self.assertIn("new.txt", summary["added"])
        self.assertIn("dir/b2.txt", summary["deleted"])
        self.assertIn("hello patched", (self.root / "a.txt").read_text(encoding="utf-8"))


class EngineTests(unittest.TestCase):
    def test_local_search_parsing_removes_for_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "data.txt").write_text("groq token", encoding="utf-8")
            out = engine.try_direct_local_command("search for groq", workspace_root=root)
            self.assertIsNotNone(out)
            self.assertIn("groq", out.lower())

    def test_local_list_typo_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "z.txt").write_text("z", encoding="utf-8")
            out = engine.try_direct_local_command("list file in workspave", workspace_root=root)
            self.assertIsNotNone(out)
            self.assertIn("z.txt", out)

    def test_non_file_chat_does_not_trigger_local_read(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = engine.try_direct_local_command("how are yu", workspace_root=root)
            self.assertIsNone(out)

    def test_local_run_command_intent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = engine.try_direct_local_command("run echo hello", workspace_root=root)
            self.assertIsNotNone(out)
            self.assertIn("stdout:", out.lower())
            self.assertIn("hello", out.lower())

    def test_local_run_python_snippet(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = engine.try_direct_local_command('run print("hi")', workspace_root=root)
            self.assertIsNotNone(out)
            self.assertIn("hi", out.lower())

    def test_local_run_help(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = engine.try_direct_local_command("run", workspace_root=root)
            self.assertIsNotNone(out)
            self.assertIn("usage: run <command>", out.lower())

    def test_open_file_prefers_read(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("hello readme", encoding="utf-8")
            out = engine.try_direct_local_command("open README.md", workspace_root=root)
            self.assertIsNotNone(out)
            self.assertIn("file: README.md", out)
            self.assertIn("hello readme", out)

    def test_open_app_maps_to_launch_tool(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parsed = engine._parse_local_intent("open notepad", root)
            self.assertIsNotNone(parsed)
            name, args = parsed
            self.assertEqual(name, "launch_app")
            self.assertEqual(args.get("app"), "notepad")

    def test_close_app_maps_to_terminate_tool(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parsed = engine._parse_local_intent("close notepad", root)
            self.assertIsNotNone(parsed)
            name, args = parsed
            self.assertEqual(name, "terminate_app")
            self.assertEqual(args.get("app"), "notepad")


class TerminalOpsTests(unittest.TestCase):
    def test_run_command_argv(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = engine._call(
                "run_command",
                {"command": sys.executable, "args": ["-c", "print('ok')"], "cwd": "."},
                root,
            )
            self.assertEqual(result["exit_code"], 0)
            self.assertIn("ok", result["stdout"])

    def test_launch_app_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(FileNotFoundError):
                engine._call("launch_app", {"app": "definitely_not_a_real_app_123"}, root)

    def test_candidate_aliases_cover_vs_code_and_chrome(self) -> None:
        vs = terminal_ops._candidate_app_names("vs code")
        ch = terminal_ops._candidate_app_names("chrome")
        self.assertTrue(any("code" in c.lower() for c in vs))
        self.assertTrue(any("chrome" in c.lower() for c in ch))


if __name__ == "__main__":
    unittest.main(verbosity=2)

