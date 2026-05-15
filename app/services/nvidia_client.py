import json
import logging
from typing import Dict, Iterator, List, Optional

import requests

logger = logging.getLogger("J.A.R.V.I.S")


class NvidiaApiError(Exception):
    pass


class NvidiaClient:
    def __init__(self, api_key: str, base_url: str, timeout: int = 60):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def chat(
        self,
        model: str,
        messages: List[dict],
        temperature: float = 0.4,
        max_tokens: int = 1024,
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        response = self.session.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        if not response.ok:
            raise NvidiaApiError(f"NVIDIA API error {response.status_code}: {response.text[:500]}")

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        return (message.get("content") or "").strip()

    def embeddings(
        self,
        model: str,
        inputs: List[str],
        input_type: str,
        embedding_type: str = "",
        dimensions: str = "",
    ) -> List[List[float]]:
        payload = {
            "model": model,
            "input": inputs,
            "input_type": input_type,
            "modality": "text",
        }
        if embedding_type:
            payload["embedding_type"] = embedding_type
        if dimensions:
            payload["dimensions"] = int(dimensions)

        response = self.session.post(
            f"{self.base_url}/embeddings",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        if not response.ok:
            raise NvidiaApiError(f"NVIDIA embeddings API error {response.status_code}: {response.text[:500]}")

        rows = response.json().get("data") or []
        ordered = sorted(rows, key=lambda row: row.get("index", 0))
        return [row.get("embedding") or [] for row in ordered]

    def stream_chat(
        self,
        model: str,
        messages: List[dict],
        temperature: float = 0.4,
        max_tokens: int = 1024,
    ) -> Iterator[str]:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        with self.session.post(
            f"{self.base_url}/chat/completions",
            headers={**self._headers(), "Accept": "text/event-stream"},
            json=payload,
            timeout=self.timeout,
            stream=True,
        ) as response:
            if not response.ok:
                raise NvidiaApiError(f"NVIDIA API error {response.status_code}: {response.text[:500]}")

            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue

                data = line[5:].strip()
                if data == "[DONE]":
                    break

                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    logger.debug("[NVIDIA] Skipping non-JSON stream payload: %s", data[:120])
                    continue

                for choice in payload.get("choices") or []:
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content

    def list_models(self) -> Optional[List[str]]:
        response = self.session.get(
            f"{self.base_url}/models",
            headers=self._headers(),
            timeout=30,
        )
        if not response.ok:
            logger.warning("[NVIDIA] Model list failed: %s %s", response.status_code, response.text[:200])
            return None
        return [m.get("id", "") for m in response.json().get("data", []) if m.get("id")]
