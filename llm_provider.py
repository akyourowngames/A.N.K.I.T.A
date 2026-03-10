#!/usr/bin/env python3
"""
Provider selection for ANKITA chat backends.
"""

import os
import json
import glob
import shutil
import sys
import threading
import time
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import requests
from dotenv import load_dotenv

from copilot_auth import CopilotAuth


load_dotenv()


@dataclass
class ProviderConfig:
    provider: str
    api_url: str
    model: str


class BaseProvider:
    """Common interface for chat providers."""

    def __init__(self, config: ProviderConfig):
        self.config = config

    @property
    def provider_name(self) -> str:
        return self.config.provider

    @property
    def api_url(self) -> str:
        return self.config.api_url

    @property
    def model(self) -> str:
        return self.config.model

    def load_token(self) -> bool:
        return True

    def authenticate(self) -> bool:
        return True

    def get_headers(self) -> dict:
        raise NotImplementedError

    def test_connection(self) -> Tuple[bool, str]:
        raise NotImplementedError

    def run_cli_prompt(self, prompt: str, cwd: Optional[str] = None) -> str:
        raise NotImplementedError

    def get_reasoning_effort(self) -> Optional[str]:
        return None

    def set_reasoning_effort(self, level: str) -> bool:
        return False


class CopilotProvider(BaseProvider):
    """GitHub Copilot chat backend."""

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.auth = CopilotAuth()

    def load_token(self) -> bool:
        return self.auth.load_token()

    def authenticate(self) -> bool:
        return self.auth.authenticate()

    def get_headers(self) -> dict:
        return self.auth.get_headers()

    def test_connection(self) -> Tuple[bool, str]:
        try:
            response = requests.get(
                "https://api.githubcopilot.com/models",
                headers=self.get_headers(),
                timeout=10,
            )
            if response.status_code == 200:
                return True, "Connection successful!"
            return False, f"Connection failed: {response.status_code}"
        except Exception as err:
            return False, f"Connection test failed: {err}"


class OpenAIProvider(BaseProvider):
    """OpenAI API backend for Codex/GPT models."""

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()

    def get_headers(self) -> dict:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not set.")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def test_connection(self) -> Tuple[bool, str]:
        try:
            base_url = self.api_url.rsplit("/v1/", 1)[0]
            response = requests.get(
                f"{base_url}/v1/models",
                headers=self.get_headers(),
                timeout=10,
            )
            if response.status_code == 200:
                return True, "Connection successful!"
            return False, f"Connection failed: {response.status_code}"
        except Exception as err:
            return False, f"Connection test failed: {err}"


class CodexCLIProvider(BaseProvider):
    """Codex CLI backend using ChatGPT sign-in or API-key login managed by Codex."""
    VALID_REASONING_LEVELS = {"low", "medium", "high", "xhigh"}

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.auth_file = Path.home() / ".codex" / "auth.json"
        self.codex_command = self._resolve_codex_command()
        default_level = (os.getenv("CODEX_REASONING_EFFORT", "xhigh").strip().lower() or "xhigh")
        self.reasoning_effort = default_level if default_level in self.VALID_REASONING_LEVELS else "xhigh"

    def _resolve_codex_command(self) -> List[str]:
        env_command = os.getenv("CODEX_COMMAND", "").strip()
        if env_command:
            env_path = shutil.which(env_command) or env_command
            if Path(env_path).exists():
                return [env_path]

        candidates: List[str] = []

        def add_candidate(path: Optional[str]) -> None:
            if not path:
                return
            normalized = os.path.normcase(os.path.abspath(path))
            if normalized not in seen and Path(path).exists():
                seen.add(normalized)
                candidates.append(path)

        seen = set()

        appdata = os.getenv("APPDATA", "").strip()
        userprofile = os.getenv("USERPROFILE", "").strip()

        add_candidate(shutil.which("codex.cmd"))
        add_candidate(shutil.which("codex.exe"))
        add_candidate(shutil.which("codex"))

        if appdata:
            add_candidate(os.path.join(appdata, "npm", "codex.cmd"))
            add_candidate(os.path.join(appdata, "npm", "codex.exe"))

        if userprofile:
            for match in sorted(
                glob.glob(
                    os.path.join(
                        userprofile,
                        ".vscode",
                        "extensions",
                        "openai.chatgpt-*",
                        "bin",
                        "windows-x86_64",
                        "codex.exe",
                    )
                ),
                reverse=True,
            ):
                add_candidate(match)

        try:
            where_result = subprocess.run(
                ["where.exe", "codex"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if where_result.returncode == 0:
                for line in (where_result.stdout or "").splitlines():
                    add_candidate(line.strip())
        except Exception:
            pass

        if candidates:
            return [candidates[0]]

        return ["codex"]

    def _read_auth_cache(self) -> dict:
        if not self.auth_file.exists():
            return {}
        try:
            return json.loads(self.auth_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _build_codex_env(self) -> dict:
        env = os.environ.copy()
        # Codex CLI should use its own stored login state rather than inheriting
        # chatbot-level OpenAI env vars from .env, which can switch it onto a bad path.
        for key in list(env.keys()):
            if key.startswith("OPENAI_"):
                env.pop(key, None)
        env.pop("ANKITA_PROVIDER", None)
        return env

    def _has_auth_cache(self) -> bool:
        data = self._read_auth_cache()
        tokens = data.get("tokens", {}) if isinstance(data, dict) else {}
        return bool(tokens.get("access_token") or tokens.get("refresh_token") or data.get("OPENAI_API_KEY"))

    def get_reasoning_effort(self) -> Optional[str]:
        return self.reasoning_effort

    def set_reasoning_effort(self, level: str) -> bool:
        normalized = (level or "").strip().lower()
        if normalized not in self.VALID_REASONING_LEVELS:
            return False
        self.reasoning_effort = normalized
        return True

    def load_token(self) -> bool:
        try:
            result = subprocess.run(
                self.codex_command + ["login", "status"],
                capture_output=True,
                text=True,
                timeout=15,
                env=self._build_codex_env(),
                check=False,
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass

        return self._has_auth_cache()

    def authenticate(self) -> bool:
        if self.load_token():
            return True

        use_device_auth = os.getenv("CODEX_DEVICE_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}
        command = self.codex_command + (["login", "--device-auth"] if use_device_auth else ["login"])

        try:
            result = subprocess.run(command, timeout=600, env=self._build_codex_env(), check=False)
            if result.returncode == 0:
                return True
        except Exception:
            pass

        return self._has_auth_cache()

    def get_headers(self) -> dict:
        raise RuntimeError("Codex CLI provider does not use direct HTTP headers.")

    def test_connection(self) -> Tuple[bool, str]:
        try:
            version_result = subprocess.run(
                self.codex_command + ["--version"],
                capture_output=True,
                text=True,
                timeout=10,
                env=self._build_codex_env(),
                check=False,
            )
            if version_result.returncode != 0:
                return False, "Codex CLI is not available."

            login_result = subprocess.run(
                self.codex_command + ["login", "status"],
                capture_output=True,
                text=True,
                timeout=15,
                env=self._build_codex_env(),
                check=False,
            )
            if login_result.returncode != 0:
                if self._has_auth_cache():
                    return True, "Using cached Codex auth from ~/.codex/auth.json"
                detail = (login_result.stderr or login_result.stdout or "").strip()
                if detail:
                    return False, f"Codex CLI is installed but login status failed: {detail}"
                return False, "Codex CLI is installed but not logged in."

            version = (version_result.stdout or version_result.stderr).strip() or "codex"
            return True, f"Connection successful via {version}"
        except FileNotFoundError:
            return False, "Codex CLI is not installed."
        except Exception as err:
            return False, f"Connection test failed: {err}"

    def run_cli_prompt(self, prompt: str, cwd: Optional[str] = None) -> str:
        output_path = Path(tempfile.mkstemp(prefix="ankita_codex_", suffix=".txt")[1])
        cmd = [
            *self.codex_command,
            "-c",
            f'model_reasoning_effort="{self.reasoning_effort}"',
            "exec",
            "--ephemeral",
            "--color",
            "never",
            "-m",
            self.model,
            "-o",
            str(output_path),
            "-",
        ]

        sandbox = (os.getenv("CODEX_SANDBOX", "workspace-write").strip() or "workspace-write")
        if sandbox:
            cmd.extend(["-s", sandbox])

        if os.getenv("CODEX_SKIP_GIT_REPO_CHECK", "").strip().lower() in {"1", "true", "yes", "on"}:
            cmd.append("--skip-git-repo-check")

        timeout_sec = int(os.getenv("CODEX_EXEC_TIMEOUT_SEC", "180") or "180")

        spinner = self._maybe_start_spinner()
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,
                timeout=timeout_sec,
                env=self._build_codex_env(),
                check=False,
            )

            if result.returncode != 0:
                error_message = self._summarize_cli_error(result.stderr or "", result.stdout or "")
                raise RuntimeError(error_message or f"codex exec failed with exit code {result.returncode}")

            if not output_path.exists():
                raise RuntimeError("codex exec completed without producing a final message")

            return output_path.read_text(encoding="utf-8").strip()
        finally:
            self._stop_spinner(spinner)
            try:
                if output_path.exists():
                    output_path.unlink()
            except Exception:
                pass

    def _maybe_start_spinner(self) -> Optional[Dict[str, Any]]:
        enabled = os.getenv("ANKITA_STATUS_UI", "true").strip().lower() in {"1", "true", "yes", "on"}
        if not enabled:
            return None

        label = os.getenv("ANKITA_STATUS_UI_LABEL", "ANKITA").strip() or "ANKITA"
        interval = float(os.getenv("ANKITA_STATUS_UI_INTERVAL_SEC", "0.15") or "0.15")

        stop_event = threading.Event()

        def spin():
            frames = ["|", "/", "-", "\\"]
            idx = 0
            while not stop_event.is_set():
                sys.stdout.write(f"\r{label}: processing {frames[idx % len(frames)]}")
                sys.stdout.flush()
                time.sleep(interval)
                idx += 1
            sys.stdout.write("\r" + (" " * (len(label) + 14)) + "\r")
            sys.stdout.flush()

        thread = threading.Thread(target=spin, name="AnkitaSpinner", daemon=True)
        thread.start()
        return {"event": stop_event, "thread": thread}

    def _stop_spinner(self, spinner: Optional[Dict[str, Any]]) -> None:
        if not spinner:
            return
        event = spinner.get("event")
        thread = spinner.get("thread")
        if isinstance(event, threading.Event):
            event.set()
        if isinstance(thread, threading.Thread):
            thread.join(timeout=1.0)

    def _summarize_cli_error(self, stderr: str, stdout: str) -> str:
        """Extract a concise Codex CLI error without echoing the full prompt."""
        combined = "\n".join(part for part in [stderr, stdout] if part).strip()
        if not combined:
            return ""

        lines = [line.strip() for line in combined.splitlines() if line.strip()]

        for line in reversed(lines):
            if line.startswith("ERROR:"):
                return line

        for line in reversed(lines):
            lowered = line.lower()
            if "usage limit" in lowered or "not valid utf-8" in lowered:
                return line

        for line in reversed(lines):
            lowered = line.lower()
            if "failed" in lowered or "error" in lowered:
                return line

        return lines[-1]


def build_provider_from_env() -> BaseProvider:
    provider = (os.getenv("ANKITA_PROVIDER", "copilot").strip() or "copilot").lower()

    if provider in {"codex", "codex_cli"}:
        config = ProviderConfig(
            provider="codex_cli",
            api_url="",
            model=os.getenv("CODEX_MODEL", "gpt-5.4").strip() or "gpt-5.4",
        )
        return CodexCLIProvider(config)

    if provider == "openai":
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip() or "https://api.openai.com/v1"
        config = ProviderConfig(
            provider="openai",
            api_url=f"{base_url.rstrip('/')}/chat/completions",
            model=os.getenv("OPENAI_MODEL", "gpt-5.2-codex").strip() or "gpt-5.2-codex",
        )
        return OpenAIProvider(config)

    config = ProviderConfig(
        provider="copilot",
        api_url="https://api.githubcopilot.com/chat/completions",
        model=os.getenv("COPILOT_MODEL", "gpt-4o").strip() or "gpt-4o",
    )
    return CopilotProvider(config)
