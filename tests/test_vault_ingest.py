"""Vault ingest: incremental hash-skip, re-chunk on change, failed status."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vault import db as _db
from vault import ingest as _ing
from vault.service import Vault


def _home(tmp_path, monkeypatch):
    home = tmp_path / "ihome"
    home.mkdir()
    monkeypatch.setattr(_db, "vault_home", lambda: home)
    monkeypatch.setattr(_db, "vault_db_path", lambda: home / "vault.db")
    monkeypatch.setattr(_db, "vault_raw_dir", lambda: home / "raw")
    monkeypatch.setattr("core.store.zumba_home", lambda: home)
    return home


def test_incremental_skip_and_rechunk(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    v = Vault(con=_db.connect())
    f = tmp_path / "note.md"
    f.write_text("# Pets\n\nDogs allowed.", encoding="utf-8")
    r1 = v.add([str(f)], use_llm=False)
    assert r1["ingested"] == 1
    con = v._open()
    n1 = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    r2 = v.add([str(f)], use_llm=False)
    assert r2["duplicates"] == 1
    f.write_text("# Pets\n\nDogs allowed with deposit 200.", encoding="utf-8")
    r3 = v.add([str(f)], use_llm=False)
    assert r3["ingested"] == 1
    n3 = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    assert n3 >= n1
    v.close()
    con.close()


def test_corrupt_pdf_failed_status_no_crash(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    v = Vault(con=_db.connect())
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 garbage \x00\xff not real")
    r = v.add([str(bad)], use_llm=False)
    assert r["ingested"] == 0 and r["failed"]
    st = v.status()
    assert st["failed"] >= 1
    v.close()


def test_forget_and_doc_inspect(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    v = Vault(con=_db.connect())
    f = tmp_path / "contract.md"
    f.write_text("# Contract March\n\nClient approved the design.", encoding="utf-8")
    v.add([str(f)], use_llm=False)
    assert "Contract March" in v.doc("contract")
    assert "Client approved" in v.read_section("contract", "Contract March")
    assert v.forget("contract")["forgot"] is True
    assert v.status()["docs"] == 0
    v.close()
