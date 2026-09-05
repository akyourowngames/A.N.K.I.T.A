import json
from pathlib import Path

import pytest

import mcpclient.config as cfg


@pytest.fixture
def home_config(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setattr(cfg, "home_config_path", lambda: home / ".zumba" / "mcp.json")
    return home / ".zumba" / "mcp.json"


def test_list_servers_empty(home_config):
    assert cfg.list_servers() == {}


def test_add_and_get_server(home_config):
    cfg.add_server("fs", {"command": "npx", "args": ["-y", "x"]})
    servers = cfg.list_servers()
    assert "fs" in servers
    entry = cfg.get_server("fs")
    assert entry["transport"] == "stdio"
    assert entry["command"] == "npx"
    assert entry["enabled"] is True
    assert entry["timeout"] == 60
    assert entry["name"] == "fs"


def test_add_server_persists_claude_desktop_format(home_config):
    cfg.add_server("r", {"url": "https://mcp.example.com/mcp"})
    data = json.loads(home_config.read_text(encoding="utf-8"))
    assert "mcpServers" in data and "r" in data["mcpServers"]
    assert data["mcpServers"]["r"]["transport"] == "http"


def test_add_server_invalid_raises(home_config):
    with pytest.raises(ValueError):
        cfg.add_server("bad", {"args": []})


def test_remove_server(home_config):
    cfg.add_server("x", {"command": "python", "args": ["s.py"]})
    assert cfg.remove_server("x") is True
    assert cfg.remove_server("x") is False
    assert "x" not in cfg.list_servers()


def test_disabled_entry_and_project_override(monkeypatch, tmp_path, home_config):
    cfg.add_server("a", {"command": "python", "args": []})
    cfg.add_server("b", {"command": "node", "args": [], "enabled": False})
    proj = tmp_path / ".mcp.json"
    proj.write_text(json.dumps({"mcpServers": {"a": {"command": "overridden"}}}), encoding="utf-8")
    monkeypatch.setattr(cfg, "project_config_path", lambda: proj)
    servers = cfg.list_servers()
    assert servers["a"]["command"] == "overridden"
    assert servers["b"]["enabled"] is False
