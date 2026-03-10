#!/usr/bin/env python3
"""
Local browser bridge server for ANKITA browser-extension automation.
"""

import base64
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse


class BrowserBridgeState:
    """In-memory command queue and extension registration state."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.extensions: Dict[str, Dict[str, Any]] = {}
        self.commands: Dict[str, Dict[str, Any]] = {}
        self.pending_order: list[str] = []

    def _now(self) -> float:
        return time.time()

    def _cleanup(self) -> None:
        now = self._now()
        stale_extensions = [
            client_id
            for client_id, info in self.extensions.items()
            if now - float(info.get("last_seen", 0.0)) > 120.0
        ]
        for client_id in stale_extensions:
            self.extensions.pop(client_id, None)

        stale_commands = [
            command_id
            for command_id, info in self.commands.items()
            if now - float(info.get("created_at", now)) > 1800.0
        ]
        for command_id in stale_commands:
            self.commands.pop(command_id, None)
            if command_id in self.pending_order:
                self.pending_order.remove(command_id)

    def _artifact_dir(self, command_id: str) -> Path:
        artifact_dir = Path(".cache") / "browser_bridge" / command_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        return artifact_dir

    def _materialize_artifacts(self, command_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            return payload

        normalized_artifacts = []
        artifact_dir = self._artifact_dir(command_id)

        for index, artifact in enumerate(artifacts, 1):
            if not isinstance(artifact, dict):
                normalized_artifacts.append(artifact)
                continue

            data_url = artifact.get("data_url")
            if not data_url or not isinstance(data_url, str) or ";base64," not in data_url:
                normalized_artifacts.append(artifact)
                continue

            header, encoded = data_url.split(",", 1)
            mime = header.split(":", 1)[-1].split(";", 1)[0].strip() or "application/octet-stream"
            extension = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/webp": ".webp",
                "text/plain": ".txt",
            }.get(mime, ".bin")

            filename = artifact.get("filename") or f"artifact_{index}{extension}"
            output_path = artifact_dir / filename
            output_path.write_bytes(base64.b64decode(encoded))

            normalized = dict(artifact)
            normalized.pop("data_url", None)
            normalized["path"] = str(output_path)
            normalized["mime_type"] = mime
            normalized_artifacts.append(normalized)

        payload["artifacts"] = normalized_artifacts
        return payload

    def register_extension(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self.condition:
            self._cleanup()
            client_id = str(payload.get("client_id") or f"ext-{uuid.uuid4().hex[:8]}")
            self.extensions[client_id] = {
                "client_id": client_id,
                "name": payload.get("name") or "ankita-browser-extension",
                "version": payload.get("version") or "dev",
                "capabilities": payload.get("capabilities") or [],
                "last_seen": self._now(),
                "active_tab": payload.get("active_tab"),
            }
            self.condition.notify_all()
            return {
                "ok": True,
                "client_id": client_id,
                "bridge": self.status(),
            }

    def heartbeat(self, client_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self.condition:
            self._cleanup()
            if client_id not in self.extensions:
                return {"ok": False, "error": f"unknown_client:{client_id}"}

            info = self.extensions[client_id]
            info["last_seen"] = self._now()
            if "active_tab" in payload:
                info["active_tab"] = payload["active_tab"]
            if "capabilities" in payload:
                info["capabilities"] = payload["capabilities"]
            self.condition.notify_all()
            return {"ok": True, "client_id": client_id}

    def status(self) -> Dict[str, Any]:
        with self.lock:
            self._cleanup()
            return {
                "service": "browser_bridge",
                "connected_extensions": len(self.extensions),
                "extensions": list(self.extensions.values()),
                "pending_commands": len(self.pending_order),
            }

    def has_connected_extensions(self) -> bool:
        with self.lock:
            self._cleanup()
            return bool(self.extensions)

    def enqueue_command(
        self,
        payload: Dict[str, Any],
        wait_for_result: bool = True,
        timeout_sec: float = 30.0,
        target_client_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self.condition:
            self._cleanup()
            command_id = str(payload.get("command_id") or f"cmd-{uuid.uuid4().hex[:10]}")
            record = {
                "command_id": command_id,
                "created_at": self._now(),
                "status": "pending",
                "target_client_id": target_client_id,
                "payload": payload,
                "result": None,
                "assigned_client_id": None,
            }
            self.commands[command_id] = record
            self.pending_order.append(command_id)
            self.condition.notify_all()

            if not wait_for_result:
                return {"ok": True, "queued": True, "command_id": command_id}

            deadline = self._now() + timeout_sec
            while self._now() < deadline:
                current = self.commands.get(command_id)
                if current and current.get("status") in {"completed", "error"}:
                    result = dict(current.get("result") or {})
                    result.setdefault("command_id", command_id)
                    return result
                remaining = deadline - self._now()
                if remaining <= 0:
                    break
                self.condition.wait(timeout=remaining)

            current = self.commands.get(command_id)
            if current:
                current["status"] = "timeout"
            return {
                "ok": False,
                "error": "command_timeout",
                "command_id": command_id,
            }

    def next_command(self, client_id: str, timeout_sec: float = 20.0) -> Dict[str, Any]:
        with self.condition:
            self._cleanup()
            if client_id not in self.extensions:
                return {"ok": False, "error": f"unknown_client:{client_id}"}

            deadline = self._now() + timeout_sec
            while self._now() < deadline:
                self.extensions[client_id]["last_seen"] = self._now()
                for command_id in list(self.pending_order):
                    record = self.commands.get(command_id)
                    if not record or record.get("status") != "pending":
                        if command_id in self.pending_order:
                            self.pending_order.remove(command_id)
                        continue

                    target_client_id = record.get("target_client_id")
                    if target_client_id and target_client_id != client_id:
                        continue

                    record["status"] = "dispatched"
                    record["assigned_client_id"] = client_id
                    self.pending_order.remove(command_id)
                    return {
                        "ok": True,
                        "command": {
                            "command_id": command_id,
                            **record["payload"],
                        },
                    }

                remaining = deadline - self._now()
                if remaining <= 0:
                    break
                self.condition.wait(timeout=remaining)

            return {"ok": True, "command": None}

    def submit_result(self, client_id: str, command_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self.condition:
            self._cleanup()
            if client_id not in self.extensions:
                return {"ok": False, "error": f"unknown_client:{client_id}"}
            record = self.commands.get(command_id)
            if record is None:
                return {"ok": False, "error": f"unknown_command:{command_id}"}

            result = self._materialize_artifacts(command_id, dict(payload))
            result.setdefault("ok", True)
            result["command_id"] = command_id
            result["client_id"] = client_id

            record["status"] = "completed" if result.get("ok") else "error"
            record["result"] = result
            record["assigned_client_id"] = client_id
            self.condition.notify_all()
            return {"ok": True}


class BrowserBridgeManager:
    """Singleton manager for the local browser bridge server."""

    _instance: Optional["BrowserBridgeManager"] = None
    _instance_lock = threading.Lock()

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.state = BrowserBridgeState()
        self.server: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    @classmethod
    def get_instance(cls) -> "BrowserBridgeManager":
        with cls._instance_lock:
            if cls._instance is None:
                host = os.getenv("BROWSER_BRIDGE_HOST", "127.0.0.1").strip() or "127.0.0.1"
                port = int(os.getenv("BROWSER_BRIDGE_PORT", "8766") or "8766")
                cls._instance = cls(host=host, port=port)
            return cls._instance

    @classmethod
    def ensure_running(cls) -> "BrowserBridgeManager":
        manager = cls.get_instance()
        manager.start()
        return manager

    def start(self) -> None:
        if self.server is not None:
            return

        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def address_string(self) -> str:
                return self.client_address[0]

            def log_message(self, format: str, *args: object) -> None:
                return

            def _send_cors_headers(self) -> None:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

            def _read_json(self) -> Dict[str, Any]:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                raw = self.rfile.read(length) if length > 0 else b"{}"
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))

            def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(204)
                self._send_cors_headers()
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/health":
                    self._send_json(200, {"ok": True, **state.status()})
                    return
                if parsed.path == "/status":
                    self._send_json(200, {"ok": True, **state.status()})
                    return
                if parsed.path == "/extension/next":
                    params = parse_qs(parsed.query)
                    client_id = (params.get("client_id", [""])[0] or "").strip()
                    timeout_sec = float((params.get("timeout_sec", ["20"])[0] or "20").strip())
                    if not client_id:
                        self._send_json(400, {"ok": False, "error": "client_id_required"})
                        return
                    self._send_json(200, state.next_command(client_id=client_id, timeout_sec=timeout_sec))
                    return
                self._send_json(404, {"ok": False, "error": "not_found"})

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                try:
                    payload = self._read_json()
                except Exception as exc:
                    self._send_json(400, {"ok": False, "error": f"invalid_json:{exc}"})
                    return

                if parsed.path == "/extension/register":
                    self._send_json(200, state.register_extension(payload))
                    return
                if parsed.path == "/extension/heartbeat":
                    client_id = str(payload.get("client_id") or "").strip()
                    if not client_id:
                        self._send_json(400, {"ok": False, "error": "client_id_required"})
                        return
                    self._send_json(200, state.heartbeat(client_id=client_id, payload=payload))
                    return
                if parsed.path == "/extension/result":
                    client_id = str(payload.get("client_id") or "").strip()
                    command_id = str(payload.get("command_id") or "").strip()
                    if not client_id or not command_id:
                        self._send_json(400, {"ok": False, "error": "client_id_and_command_id_required"})
                        return
                    self._send_json(200, state.submit_result(client_id=client_id, command_id=command_id, payload=payload))
                    return
                if parsed.path == "/command":
                    wait_for_result = bool(payload.get("wait_for_result", True))
                    timeout_sec = float(payload.get("timeout_sec", os.getenv("BROWSER_BRIDGE_COMMAND_TIMEOUT_SEC", "30")))
                    target_client_id = payload.get("target_client_id")
                    command_payload = payload.get("command") or payload
                    self._send_json(
                        200,
                        state.enqueue_command(
                            payload=command_payload,
                            wait_for_result=wait_for_result,
                            timeout_sec=timeout_sec,
                            target_client_id=target_client_id,
                        ),
                    )
                    return

                self._send_json(404, {"ok": False, "error": "not_found"})

        self.server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.5},
            name="AnkitaBrowserBridge",
            daemon=True,
        )
        self.thread.start()

    def stop(self) -> None:
        if self.server is None:
            return
        self.server.shutdown()
        self.server.server_close()
        self.server = None
        self.thread = None

    def command(self, payload: Dict[str, Any], wait_for_result: bool = True, timeout_sec: float = 30.0) -> Dict[str, Any]:
        return self.state.enqueue_command(
            payload=payload,
            wait_for_result=wait_for_result,
            timeout_sec=timeout_sec,
        )


def main() -> None:
    manager = BrowserBridgeManager.ensure_running()
    print("ANKITA Browser Bridge started")
    print(f"URL: http://{manager.host}:{manager.port}")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping browser bridge.")
    finally:
        manager.stop()


if __name__ == "__main__":
    main()
