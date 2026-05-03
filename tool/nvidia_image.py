from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tool.local_paths import allowed_roots, ensure_allowed_path


@dataclass(frozen=True)
class NvidiaImageTool:
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    name: str = "image_generation"
    description: str = "Generates images with NVIDIA visual generative AI models."

    def run(
        self,
        prompt: str,
        output_path: str = "",
        size: str = "",
        n: int = 1,
        seed: int | None = None,
        open_after_save: bool | None = None,
    ) -> str:
        prompt = prompt.strip()
        if not prompt:
            return "FAILED: image prompt is required."

        n = max(1, min(int(n or 1), 4))
        try:
            body = self._request(prompt=prompt, n=n, size=size.strip(), seed=seed)
            return self._save_or_report(
                body=body,
                prompt=prompt,
                output_path=output_path,
                n=n,
                size=size.strip(),
                seed=seed,
                open_after_save=open_after_save,
            )
        except Exception as error:
            return f"FAILED: NVIDIA image generation failed: {error}"

    def run_stream(
        self,
        prompt: str,
        output_path: str = "",
        size: str = "",
        n: int = 1,
        seed: int | None = None,
        open_after_save: bool | None = None,
    ):
        prompt = prompt.strip()
        if not prompt:
            return "FAILED: image prompt is required."

        n = max(1, min(int(n or 1), 4))
        size = size.strip()
        saved_paths: list[Path] = []
        urls: list[str] = []
        try:
            for index in range(1, n + 1):
                image_seed = self._seed_for_index(seed=seed, index=index, total=n)
                yield f"Generating image {index}/{n}...\n"
                body = self._request(prompt=prompt, n=1, size=size, seed=image_seed)
                batch_paths, batch_urls = self._save_images(
                    body=body,
                    prompt=prompt,
                    output_path=output_path,
                    start_index=index,
                    total=n,
                    size=size,
                    seed=seed,
                )
                saved_paths.extend(batch_paths)
                urls.extend(batch_urls)

            self._open_paths_if_enabled(saved_paths, open_after_save=open_after_save)
            return self._format_result(saved_paths=saved_paths, urls=urls)
        except Exception as error:
            return f"FAILED: NVIDIA image generation failed: {error}"

    def _request(self, prompt: str, n: int, size: str = "", seed: int | None = None) -> dict[str, Any]:
        key = self.api_key or os.getenv("NVIDIA_IMAGE_API_KEY", "").strip() or os.getenv("NVIDIA_API_KEY", "").strip()
        if not key:
            raise ValueError("Missing NVIDIA_API_KEY or NVIDIA_IMAGE_API_KEY.")

        endpoint = self._endpoint()
        max_per_request = self._max_images_per_request(endpoint)
        remaining = n
        offset = 0
        responses: list[dict[str, Any]] = []

        while remaining > 0:
            batch_size = min(remaining, max_per_request)
            batch_seed = seed + offset if seed is not None and n > 1 else seed
            payload = self._payload(prompt=prompt, n=batch_size, size=size, seed=batch_seed, endpoint=endpoint)
            responses.append(self._post_with_retry(endpoint=endpoint, key=key, payload=payload))
            remaining -= batch_size
            offset += batch_size

        return responses[0] if len(responses) == 1 else self._merge_responses(responses)

    def _post_with_retry(self, endpoint: str, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            attempts = max(1, int(os.getenv("NVIDIA_IMAGE_RETRY_ATTEMPTS", "2")))
        except ValueError:
            attempts = 2
        for attempt in range(1, attempts + 1):
            try:
                return self._post(endpoint=endpoint, key=key, payload=payload)
            except RuntimeError as error:
                if attempt >= attempts or not self._is_retryable_error(error):
                    raise
                time.sleep(self._retry_delay_seconds())
        raise RuntimeError("NVIDIA image request failed after retry.")

    def _post(self, endpoint: str, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            timeout = int(os.getenv("NVIDIA_IMAGE_TIMEOUT_SECONDS", "120"))
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{error.code} {details}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Could not reach NVIDIA API: {error.reason}") from error

    @staticmethod
    def _is_retryable_error(error: RuntimeError) -> bool:
        text = str(error).strip()
        return text.startswith("429 ") or any(text.startswith(f"{code} ") for code in range(500, 600))

    @staticmethod
    def _retry_delay_seconds() -> float:
        try:
            return max(0.0, float(os.getenv("NVIDIA_IMAGE_RETRY_DELAY_SECONDS", "1")))
        except ValueError:
            return 1.0

    def _max_images_per_request(self, endpoint: str) -> int:
        if self._uses_openai_images(endpoint):
            raw = os.getenv("NVIDIA_IMAGE_OPENAI_MAX_IMAGES_PER_REQUEST", "4")
        else:
            raw = os.getenv("NVIDIA_IMAGE_MAX_SAMPLES_PER_REQUEST", "1")
        try:
            value = int(raw)
        except ValueError:
            value = 1
        return max(1, min(value, 4))

    @staticmethod
    def _merge_responses(responses: list[dict[str, Any]]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        data: list[Any] = []
        artifacts: list[Any] = []
        for response in responses:
            response_data = response.get("data")
            response_artifacts = response.get("artifacts")
            if isinstance(response_data, list):
                data.extend(response_data)
            if isinstance(response_artifacts, list):
                artifacts.extend(response_artifacts)
        if data:
            merged["data"] = data
        if artifacts:
            merged["artifacts"] = artifacts
        return merged

    def _save_or_report(
        self,
        body: dict[str, Any],
        prompt: str,
        output_path: str,
        n: int,
        size: str = "",
        seed: int | None = None,
        open_after_save: bool | None = None,
    ) -> str:
        saved_paths, urls = self._save_images(
            body=body,
            prompt=prompt,
            output_path=output_path,
            start_index=1,
            total=n,
            size=size,
            seed=seed,
        )
        self._open_paths_if_enabled(saved_paths, open_after_save=open_after_save)
        return self._format_result(saved_paths=saved_paths, urls=urls)

    def _save_images(
        self,
        body: dict[str, Any],
        prompt: str,
        output_path: str,
        start_index: int,
        total: int,
        size: str,
        seed: int | None,
    ) -> tuple[list[Path], list[str]]:
        items = body.get("data")
        if not isinstance(items, list) or not items:
            items = body.get("artifacts")
        if not isinstance(items, list) or not items:
            raise RuntimeError(f"Unexpected NVIDIA image response: {body}")

        saved_paths: list[Path] = []
        urls: list[str] = []
        encoded_images = self._encoded_images(body)

        for offset, item in enumerate(items[:total], start=0):
            index = start_index + offset
            if isinstance(item, dict):
                encoded = item.get("b64_json") or item.get("base64")
                if isinstance(encoded, str) and encoded.strip():
                    image_bytes = base64.b64decode(encoded)
                    target = self._target_path(prompt=prompt, output_path=output_path, index=index, multiple=total > 1)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(image_bytes)
                    self._write_metadata(target=target, prompt=prompt, size=size, seed=self._seed_for_index(seed, index, total))
                    saved_paths.append(target)
                    continue
                url = item.get("url")
                if isinstance(url, str) and url.strip():
                    urls.append(url.strip())

        return saved_paths, urls

    def _format_result(self, saved_paths: list[Path], urls: list[str]) -> str:
        if saved_paths:
            lines = [f"Generated {len(saved_paths)} image(s) with NVIDIA model {self._model_label()}:"]
            lines.extend(f"- {path}" for path in saved_paths)
            lines.append("Metadata saved beside each image.")
            return "\n".join(lines)
        if urls:
            lines = [f"NVIDIA returned image URL(s) with model {self._model_label()}:"]
            lines.extend(f"- {url}" for url in urls)
            return "\n".join(lines)
        raise RuntimeError("No image data found in NVIDIA response.")

    def _write_metadata(self, target: Path, prompt: str, size: str, seed: int | None) -> None:
        metadata = {
            "prompt": prompt,
            "model": self._model_label(),
            "endpoint": self._endpoint(),
            "seed": seed,
            "size": size or None,
            "created_at": datetime.now().astimezone().isoformat(),
            "image_path": str(target),
        }
        target.with_suffix(target.suffix + ".json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _open_paths_if_enabled(self, saved_paths: list[Path], open_after_save: bool | None = None) -> None:
        if not saved_paths or not self._open_after_save_enabled(open_after_save):
            return
        for path in saved_paths:
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except Exception:
                continue

    @staticmethod
    def _open_after_save_enabled(open_after_save: bool | None = None) -> bool:
        if open_after_save is not None:
            return open_after_save
        return os.getenv("NVIDIA_IMAGE_OPEN_AFTER_SAVE", "false").strip().lower() in {"1", "true", "yes", "on"}

    def _encoded_images(self, body: dict[str, Any]) -> list[str]:
        encoded: list[str] = []
        for collection_name in ("data", "artifacts"):
            collection = body.get(collection_name)
            if not isinstance(collection, list):
                continue
            for item in collection:
                if not isinstance(item, dict):
                    continue
                value = item.get("b64_json") or item.get("base64")
                if isinstance(value, str) and value.strip():
                    encoded.append(value.strip())
        return encoded

    def _payload(self, prompt: str, n: int, size: str, seed: int | None, endpoint: str) -> dict[str, Any]:
        if self._uses_openai_images(endpoint):
            payload: dict[str, Any] = {
                "model": self._model(),
                "prompt": prompt,
                "n": n,
                "response_format": "b64_json",
            }
            if size:
                payload["size"] = size
            if seed is not None:
                payload["seed"] = seed
            return payload

        payload = {
            "prompt": prompt,
            "samples": n,
        }
        width, height = self._parse_size(size)
        if width and height:
            payload["width"] = width
            payload["height"] = height
        if seed is not None:
            payload["seed"] = seed
        return payload

    @staticmethod
    def _parse_size(size: str) -> tuple[int | None, int | None]:
        match = re.fullmatch(r"\s*(\d{3,4})\s*[xX]\s*(\d{3,4})\s*", size or "")
        if not match:
            return None, None
        return int(match.group(1)), int(match.group(2))

    @staticmethod
    def _uses_openai_images(endpoint: str) -> bool:
        return endpoint.rstrip("/").endswith("/images/generations")

    def _model_label(self) -> str:
        endpoint = self._endpoint().rstrip("/")
        marker = "/genai/"
        if marker in endpoint:
            return endpoint.split(marker, 1)[1]
        return self._model()

    def _target_path(self, prompt: str, output_path: str, index: int, multiple: bool) -> Path:
        roots = self._image_allowed_roots()
        if output_path.strip():
            candidate = Path(output_path).expanduser()
            if not candidate.is_absolute():
                candidate = self._default_output_dir() / candidate
            if candidate.exists() and candidate.is_dir():
                candidate = candidate / self._filename(prompt, index, multiple)
            elif not candidate.suffix:
                candidate = candidate.with_suffix(".png")
        else:
            candidate = self._default_output_dir() / self._filename(prompt, index, multiple)
        image_roots_configured = bool(os.getenv("IMAGE_OUTPUT_ALLOWED_PATHS", "").strip())
        return ensure_allowed_path(candidate, roots, restrict=True if image_roots_configured else None)

    def _endpoint(self) -> str:
        endpoint = os.getenv("NVIDIA_IMAGE_ENDPOINT", "").strip()
        if endpoint:
            return endpoint
        base_url = os.getenv("NVIDIA_IMAGE_BASE_URL", "").strip()
        if not base_url and not self.base_url:
            return "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev"
        base_url = (
            self.base_url
            or base_url
            or os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").strip()
        )
        return f"{base_url.rstrip('/')}/images/generations"

    def _model(self) -> str:
        return self.model or os.getenv("NVIDIA_IMAGE_MODEL", "black-forest-labs/flux.2-klein-4b").strip()

    @staticmethod
    def _seed_for_index(seed: int | None, index: int, total: int) -> int | None:
        if seed is None:
            return None
        return seed + index - 1 if total > 1 else seed

    @staticmethod
    def _default_output_dir() -> Path:
        configured = os.getenv("NVIDIA_IMAGE_OUTPUT_DIR", "").strip()
        if configured:
            return Path(configured).expanduser()
        pictures = Path.home() / "Pictures"
        root = pictures if pictures.exists() else Path.home() / "Documents"
        return root / "ANKITA" / "images"

    @staticmethod
    def _image_allowed_roots() -> list[Path]:
        if os.getenv("IMAGE_OUTPUT_ALLOWED_PATHS", "").strip():
            return allowed_roots("IMAGE_OUTPUT_ALLOWED_PATHS")
        return allowed_roots("LOCAL_FILE_ALLOWED_PATHS")

    @staticmethod
    def _filename(prompt: str, index: int, multiple: bool) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:42] or "image"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        suffix = f"-{index}" if multiple else ""
        return f"{stamp}-{slug}{suffix}.png"
