from __future__ import annotations

from pathlib import Path

import pytest

from jakata_agent.prompts import PromptLoadError, load_prompt


PROMPT_MARKERS = {
    "agent/system.md": "You are JAKATA, a personal AI assistant.",
    "agent/casual.md": "Reply in one or two sentences maximum.",
    "agent/synthesis.md": "You have tool and memory results.",
    "router/planner.md": "You are the JAKATA task planner.",
    "tasks/role_selector.md": "multi-agent orchestrator",
    "tasks/verifier.md": "JAKATA task verifier",
    "os_agent/planner.md": "internal JAKATA OS action planner",
    "os_agent/spec_builder.md": "JAKATA OS task spec builder",
    "os_agent/verifier.md": "JAKATA OS verifier",
    "os_agent/modal_recovery.md": "modal recovery planner",
    "telegram/guest.md": "public Telegram guest mode",
    "camera/vision.md": "live camera frames",
    "coding_agent/planner.md": "internal JAKATA coding action planner",
    "coding_agent/verifier.md": "JAKATA coding task verifier",
}


def test_prompt_files_load_from_default_prompt_root():
    load_prompt.cache_clear()
    for relative_path, marker in PROMPT_MARKERS.items():
        prompt = load_prompt(relative_path)
        assert marker in prompt
        assert (Path("prompts") / relative_path).is_file()


def test_prompt_loader_supports_custom_prompt_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    custom_root = tmp_path / "custom_prompts"
    (custom_root / "agent").mkdir(parents=True)
    (custom_root / "agent" / "system.md").write_text("Custom JAKATA system prompt", encoding="utf-8")

    monkeypatch.setenv("JAKATA_PROMPTS_DIR", str(custom_root))
    load_prompt.cache_clear()

    assert load_prompt("agent/system.md") == "Custom JAKATA system prompt"


def test_prompt_loader_rejects_paths_outside_prompt_root():
    load_prompt.cache_clear()
    with pytest.raises(PromptLoadError):
        load_prompt("../.env")
