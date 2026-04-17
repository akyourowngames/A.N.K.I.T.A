from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from llm import LLMRuntime
from tools import code_writer_ops


def test_write_code_artifact_saves_html_landing_page() -> None:
    plan_json = (
        '{"title":"Tea Shop Landing Page","artifact_type":"landing_page","extension":".html",'
        '"filename_stem":"tea_shop_landing_page","framework":"vanilla html","language":"html",'
        '"implementation_notes":["single file"],"visual_goals":["hero"],"acceptance_checks":["opens locally"]}'
    )
    html = "<!DOCTYPE html><html><body><h1>Tea Shop</h1></body></html>"
    base_runtime = LLMRuntime(
        provider="nvidia",
        model="meta/llama-3.1-8b-instruct",
        api_key="test-key",
        base_url="https://integrate.api.nvidia.com/v1",
        max_tokens=2048,
    )

    with TemporaryDirectory() as tmp:
        with patch("tools.code_writer_ops.build_runtime_from_env", return_value=base_runtime):
            with patch("tools.code_writer_ops.call_chat_once", side_effect=[{"content": plan_json}, {"content": html}]):
                result = code_writer_ops.write_code_artifact(
                    workspace_root=Path(tmp),
                    task="build me a landing page for a tea shop",
                    artifact_type="landing_page",
                    extra_context="Include testimonials and pricing.",
                    output_dir=tmp,
                )
        assert result["ok"] is True
        assert result["FILE_PATH"].endswith(".html")
        saved = Path(result["FILE_PATH"])
        assert saved.exists()
        assert saved.read_text(encoding="utf-8") == html

    assert result["coding_model"] == code_writer_ops.DEFAULT_NVIDIA_CODEWRITER_MODEL
    assert result["reasoning_model"] == code_writer_ops.DEFAULT_NVIDIA_CODEWRITER_REASONING_MODEL


def test_write_code_artifact_infers_html_type_from_task() -> None:
    assert code_writer_ops._normalize_artifact_type("", "create a homepage for my cafe", "") == "landing_page"
