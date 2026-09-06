"""Vault chunker: headings, atomic fence/table, overlap, token estimates."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vault import chunker


def test_heading_boundaries_and_overlap():
    md = "# Lease\n\nPets are allowed with deposit.\n\n## Rent\n\nRent is 1000.\n\n## Insurance\n\nMust insure."
    chunks = chunker.chunk_markdown(md, target_tokens=12, overlap=4)
    assert len(chunks) >= 2
    assert any(c["heading"] == "Rent" for c in chunks)
    assert all(c["text"].strip() for c in chunks)
    assert chunker.estimate_tokens("abcd") == 1.0


def test_fence_never_splits():
    code = "```python\n" + "\n".join(f"line{i} = {i}" for i in range(60)) + "\n```"
    md = "# Doc\n\nIntro para.\n\n" + code + "\n\nTail para."
    chunks = chunker.chunk_markdown(md, target_tokens=40, overlap=10)
    joined = "\n".join(c["text"] for c in chunks)
    assert "line0 = 0" in joined and "line59 = 59" in joined
    fenced = [c for c in chunks if "```python" in c["text"]]
    assert fenced and "line59 = 59" in fenced[0]["text"]


def test_table_stays_whole():
    table = "\n".join(f"| a{i} | b{i} |" for i in range(30))
    md = "# T\n\n" + table
    chunks = chunker.chunk_markdown(md, target_tokens=30, overlap=10)
    assert any("| a29 | b29 |" in c["text"] and "| a0 | b0 |" in c["text"] for c in chunks)
