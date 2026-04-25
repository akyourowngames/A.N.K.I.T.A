from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jakata_agent.tasks.models import TaskRecord, utcnow_iso
from jakata_agent.tasks.store import TaskStore


GUARDED_TOOLS = {
    "os_agent",
    "keyboard",
    "mouse",
    "browser",
    "clipboard",
    "window",
    "system",
}

_HIGH_RISK_KEYBOARD_HOTKEYS = {
    "alt+f4",
    "ctrl+shift+w",
    "ctrl+w",
    "win+d",
    "win+r",
    "win+x",
}

@dataclass(slots=True)
class ApprovalRequest:
    id: str
    task_id: str
    tool: str
    args: dict[str, Any]
    reason: str
    fingerprint: str
    summary: str
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "tool": self.tool,
            "args": self.args,
            "reason": self.reason,
            "fingerprint": self.fingerprint,
            "summary": self.summary,
            "created_at": self.created_at,
        }


class ApprovalRequired(RuntimeError):
    def __init__(self, request: ApprovalRequest) -> None:
        super().__init__(request.summary)
        self.request = request


class ApprovalDenied(RuntimeError):
    def __init__(self, approval: dict[str, Any]) -> None:
        super().__init__("Pending action was denied by the operator.")
        self.approval = approval


class ApprovalGate:
    def __init__(
        self,
        *,
        task_store: TaskStore,
        task: TaskRecord,
        guarded_tools: set[str] | None = None,
        approval_policy: str = "manual",
        workspace_dir: str | Path | None = None,
        data_dir: str | Path | None = None,
        actor: str = "operator",
    ) -> None:
        self.task_store = task_store
        self.task = task
        self.guarded_tools = guarded_tools or GUARDED_TOOLS
        self.approval_policy = approval_policy.strip().lower() or "manual"
        self.workspace_dir = Path(workspace_dir).expanduser().resolve() if workspace_dir else None
        self.data_dir = Path(data_dir).expanduser().resolve() if data_dir else None
        self.actor = actor

    def require(self, tool: str, args: dict[str, Any], reason: str = "") -> None:
        if not self._requires_approval(tool, args):
            return
        fingerprint = self.fingerprint(tool, args)
        pending = self._latest_task().pending_approval
        if pending and pending.get("fingerprint") == fingerprint:
            status = str(pending.get("status", "waiting"))
            if status == "approved":
                self.task = self.task_store.clear_pending_approval(self.task.id) or self.task
                return
            if status == "denied":
                raise ApprovalDenied(pending)

        request = ApprovalRequest(
            id=str(uuid.uuid4()),
            task_id=self.task.id,
            tool=tool,
            args=self._safe_args(args),
            reason=reason,
            fingerprint=fingerprint,
            summary=self._summary(tool, args, reason),
            created_at=utcnow_iso(),
        )
        self.task = self.task_store.set_pending_approval(self.task.id, request.as_dict()) or self.task
        raise ApprovalRequired(request)

    def _requires_approval(self, tool: str, args: dict[str, Any]) -> bool:
        if tool == "shell":
            return False
        if tool not in self.guarded_tools:
            return False
        if self.approval_policy == "auto":
            return False
        if self.approval_policy != "auto_safe":
            return True
        return self._is_high_risk(tool, args)

    def _is_high_risk(self, tool: str, args: dict[str, Any]) -> bool:
        if tool == "os_agent":
            return True
        if tool == "write_file":
            return not self._is_trusted_write(args)
        if tool == "system":
            action = str(args.get("action", "")).strip().lower()
            operation = str(args.get("operation", "")).strip().lower()
            if action in {"power", "terminate_process"}:
                return True
            return action == "recycle_bin" and operation == "empty"
        if tool == "window":
            return str(args.get("action", "")).strip().lower() == "close"
        if tool == "browser":
            return str(args.get("action", "")).strip().lower() == "close_tab"
        if tool == "keyboard":
            return self._keyboard_is_high_risk(args)
        return False

    def _keyboard_is_high_risk(self, args: dict[str, Any]) -> bool:
        action = str(args.get("action", "")).strip().lower()
        if action == "hotkey":
            return self._is_high_risk_hotkey(str(args.get("keys", "")))
        if action == "press":
            return str(args.get("keys", "")).strip().lower() == "f4"
        if action == "sequence":
            steps = args.get("steps", [])
            if not isinstance(steps, list):
                return False
            return any(self._keyboard_is_high_risk(step) for step in steps if isinstance(step, dict))
        return False

    @staticmethod
    def _is_high_risk_hotkey(keys: str) -> bool:
        normalized = keys.strip().lower().replace(" ", "")
        return normalized in _HIGH_RISK_KEYBOARD_HOTKEYS

    def _is_trusted_write(self, args: dict[str, Any]) -> bool:
        raw_path = str(args.get("path", "")).strip()
        if not raw_path:
            return False
        candidate = self._resolve_trusted_candidate(raw_path)
        return candidate is not None

    def _resolve_trusted_candidate(self, raw_path: str) -> Path | None:
        trusted_roots = [root for root in [self.workspace_dir, self.data_dir, self._task_cwd()] if root is not None]
        if not trusted_roots:
            return None
        if not raw_path:
            return trusted_roots[0]
        candidate = Path(raw_path).expanduser()
        candidate = (trusted_roots[0] / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        for root in trusted_roots:
            try:
                candidate.relative_to(root)
                return candidate
            except ValueError:
                continue
        return None

    def _task_cwd(self) -> Path | None:
        cwd = str(getattr(self.task, "cwd", "") or "").strip()
        if not cwd:
            return None
        return Path(cwd).expanduser().resolve()

    def _latest_task(self) -> TaskRecord:
        latest = self.task_store.get_task(self.task.id)
        if latest is not None:
            self.task = latest
        return self.task

    @staticmethod
    def fingerprint(tool: str, args: dict[str, Any]) -> str:
        payload = json.dumps({"tool": tool, "args": args}, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _safe_args(args: dict[str, Any]) -> dict[str, Any]:
        text = json.dumps(args, ensure_ascii=False, default=str)
        if len(text) <= 2000:
            return args
        return {"preview": text[:2000], "truncated": True}

    @staticmethod
    def _summary(tool: str, args: dict[str, Any], reason: str) -> str:
        action = args.get("action") if isinstance(args, dict) else ""
        target = args.get("target") or args.get("path") or args.get("url") or args.get("command") if isinstance(args, dict) else ""
        bits = [f"Approval required for {tool}"]
        if action:
            bits.append(f"action={action}")
        if target:
            bits.append(f"target={str(target)[:160]}")
        if reason:
            bits.append(f"reason={reason[:220]}")
        return "; ".join(bits)
