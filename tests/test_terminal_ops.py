import tempfile
from pathlib import Path
import pytest

from tools import terminal_ops


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_fast_file_search_finds_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "config.yaml"
        _write(target, "ok")
        _write(root / "notes.txt", "nope")

        result = terminal_ops.fast_file_search(pattern="config", path=str(root))
        assert result["ok"] is True
        assert result["matches_found"] >= 1
        assert str(target) in result["results"]


def test_fast_file_search_respects_max_results() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for i in range(5):
            _write(root / f"match_{i}.txt", "x")

        result = terminal_ops.fast_file_search(pattern="match_", path=str(root), max_results=2)
        assert result["ok"] is True
        assert result["matches_found"] == 5
        assert len(result["results"]) == 2
        assert result["truncated"] is True


def test_fast_file_search_missing_path() -> None:
    result = terminal_ops.fast_file_search(pattern="x", path="Z:\\does_not_exist")
    assert result["ok"] is False
    assert "Search path does not exist" in result["error"]


def test_fast_file_search_case_sensitivity() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "CaseFile.TXT"
        _write(target, "x")

        insensitive = terminal_ops.fast_file_search(pattern="casefile", path=str(root), case_sensitive=False)
        assert insensitive["ok"] is True
        assert str(target) in insensitive["results"]

        sensitive = terminal_ops.fast_file_search(pattern="casefile", path=str(root), case_sensitive=True)
        assert sensitive["ok"] is True
        assert str(target) not in sensitive["results"]


def test_resolve_local_target_returns_best_existing_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "screenshots" / "final_landing_page.html"
        _write(target, "<!DOCTYPE html><html></html>")
        _write(root / "notes" / "landing_page_notes.md", "# notes")

        result = terminal_ops.resolve_local_target(
            query="final landing page",
            roots=[str(root)],
            extensions=[".html"],
        )

        assert result["ok"] is True
        assert result["best_path"] == str(target)
        assert result["FILE_PATH"] == str(target)
        assert result["target_kind"] == "file"
        assert result["results"][0]["path"] == str(target)


def test_resolve_local_target_accepts_existing_direct_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "gateway.py"
        _write(target, "print('ok')")

        result = terminal_ops.resolve_local_target(query=str(target))

        assert result["ok"] is True
        assert result["best_path"] == str(target)
        assert result["confidence"] == "high"


def test_prepare_launch_args_rejects_fake_local_placeholder() -> None:
    with pytest.raises(FileNotFoundError):
        terminal_ops._prepare_launch_args(
            "chrome.exe",
            ["file:///C:/path/to/desktop/fake.html"],
        )
