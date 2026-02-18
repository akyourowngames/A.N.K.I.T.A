import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm import client as llm_client


class LLMClientTests(unittest.TestCase):
    def test_derive_copilot_base_url(self) -> None:
        token = "abc;proxy-ep=proxy.copilot.example;xyz"
        base = llm_client._derive_copilot_base_url(token)
        self.assertEqual(base, "https://api.copilot.example")

    def test_build_runtime_groq(self) -> None:
        env = {
            "LLM_PROVIDER": "groq",
            "GROQ_API_KEY": "k",
            "GROQ_MODEL": "llama-test",
            "LLM_MAX_TOKENS": "200",
        }
        with patch.dict("os.environ", env, clear=True):
            runtime = llm_client.build_runtime_from_env()
        self.assertEqual(runtime.provider, "groq")
        self.assertEqual(runtime.model, "llama-test")
        self.assertEqual(runtime.api_key, "k")
        self.assertEqual(runtime.max_tokens, 200)

    def test_build_runtime_copilot_direct_api_key(self) -> None:
        env = {
            "LLM_PROVIDER": "copilot",
            "COPILOT_API_KEY": "copilot-token;proxy-ep=proxy.demo.example;",
            "COPILOT_MODEL": "gpt-4o",
            "LLM_MAX_TOKENS": "150",
        }
        with patch.dict("os.environ", env, clear=True):
            runtime = llm_client.build_runtime_from_env()
        self.assertEqual(runtime.provider, "copilot")
        self.assertEqual(runtime.model, "gpt-4o")
        self.assertEqual(runtime.base_url, "https://api.demo.example")
        self.assertEqual(runtime.max_tokens, 150)

    def test_exchange_github_to_copilot_token(self) -> None:
        class FakeResponse:
            ok = True
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"token": "fresh;proxy-ep=proxy.mock.example;", "expires_at": 4102444800}

        with tempfile.TemporaryDirectory() as td:
            cache_path = Path(td) / "cache.json"
            with patch("llm.client.requests.get", return_value=FakeResponse()) as mock_get:
                payload = llm_client._exchange_github_to_copilot_token("gh", cache_path)
            self.assertEqual(payload["token"], "fresh;proxy-ep=proxy.mock.example;")
            self.assertTrue(cache_path.exists())
            self.assertEqual(mock_get.call_count, 1)

    def test_build_runtime_copilot_uses_cached_github_token(self) -> None:
        env = {
            "LLM_PROVIDER": "copilot",
            "COPILOT_MODEL": "gpt-4o",
            "LLM_MAX_TOKENS": "140",
        }
        with patch.dict("os.environ", env, clear=True):
            with patch("llm.client._load_cached_github_token", return_value="gh_cached_token"):
                with patch(
                    "llm.client._exchange_github_to_copilot_token",
                    return_value={"token": "cp;proxy-ep=proxy.cached.example;", "expires_at": 4102444800},
                ):
                    runtime = llm_client.build_runtime_from_env()
        self.assertEqual(runtime.provider, "copilot")
        self.assertEqual(runtime.base_url, "https://api.cached.example")
        self.assertEqual(runtime.max_tokens, 140)

    def test_call_chat_once_sets_copilot_headers(self) -> None:
        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

        runtime = llm_client.LLMRuntime(
            provider="copilot",
            model="gpt-4o",
            api_key="cp_token",
            base_url="https://api.individual.githubcopilot.com",
            max_tokens=120,
        )
        with patch("llm.client.requests.post", return_value=FakeResponse()) as mock_post:
            llm_client.call_chat_once(runtime, [{"role": "user", "content": "hi"}], tools=None, max_tokens=120)
        headers = mock_post.call_args.kwargs["headers"]
        self.assertIn("Editor-Version", headers)
        self.assertIn("User-Agent", headers)
        self.assertIn("Editor-Plugin-Version", headers)


if __name__ == "__main__":
    unittest.main(verbosity=2)
