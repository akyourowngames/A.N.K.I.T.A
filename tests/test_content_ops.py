from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools import content_ops


def test_infer_effective_format_detects_document_type_from_topic() -> None:
    effective = content_ops._infer_effective_format(
        "content",
        "write a report on dog breeds",
        "",
    )
    assert effective == "report"
    assert content_ops._extension_for_format(effective) == ".md"


def test_write_content_rejects_landing_page_requests() -> None:
    with TemporaryDirectory() as tmp:
        result = content_ops.write_and_save_content(
            workspace_root=Path(tmp),
            topic="build me a landing page for a coffee shop",
            format_type="report",
            extra_context="Include a hero and menu section.",
            output_dir=tmp,
        )
    assert result["ok"] is False
    assert result["preferred_tool"] == "write_code_artifact"


def test_write_content_uses_format_specific_prompt_for_letter() -> None:
    captured: dict[str, object] = {}

    def fake_call_chat_once(runtime, messages, tools, max_tokens):  # type: ignore[no-untyped-def]
        del runtime, tools, max_tokens
        captured["messages"] = messages
        return {"content": "Dear Sarah,\n\nThank you.\n\nSincerely,\nAnkita"}

    with TemporaryDirectory() as tmp:
        with patch("llm.build_runtime_from_env", return_value=object()):
            with patch("llm.call_chat_once", side_effect=fake_call_chat_once):
                result = content_ops.write_and_save_content(
                    workspace_root=Path(tmp),
                    topic="thank Sarah for the interview",
                    format_type="letter",
                    extra_context="Keep it warm and professional.",
                    output_dir=tmp,
                )

    assert result["ok"] is True
    assert result["FILE_PATH"].endswith(".txt")
    user_prompt = captured["messages"][1]["content"]  # type: ignore[index]
    assert "salutation, body, and sign-off" in user_prompt


def test_resolve_output_dir_rejects_placeholder_desktop() -> None:
    resolved = content_ops._resolve_output_dir(r"C:\home\user\Desktop")
    assert resolved == content_ops._resolve_output_dir(None)
