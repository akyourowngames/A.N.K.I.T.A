import tempfile
from pathlib import Path

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
