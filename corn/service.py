import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .schedule import next_run_ms
from .store import load_store, save_store

PayloadExecutor = Callable[[Dict[str, Any], Path], Dict[str, Any]]


class CornService:
    def __init__(self, workspace_root: Path, store_path: Optional[Path] = None, runs_path: Optional[Path] = None):
        self.workspace_root = workspace_root
        base = workspace_root / ".ankita" / "corn"
        self.store_path = store_path or (base / "jobs.json")
        self.runs_path = runs_path or (base / "runs.jsonl")

    def _load(self) -> Dict[str, Any]:
        return load_store(self.store_path)

    def _save(self, payload: Dict[str, Any]) -> None:
        save_store(self.store_path, payload)

    def status(self) -> Dict[str, Any]:
        data = self._load()
        now_ms = int(time.time() * 1000)
        enabled = [j for j in data["jobs"] if isinstance(j, dict) and bool(j.get("enabled", True))]
        due = [j for j in enabled if int(j.get("state", {}).get("next_run_at_ms", 2**62)) <= now_ms]
        return {
            "kind": "cron_status",
            "jobs_total": len(data["jobs"]),
            "jobs_enabled": len(enabled),
            "jobs_due_now": len(due),
            "store_path": str(self.store_path),
        }

    def list(self, include_disabled: bool = False) -> Dict[str, Any]:
        data = self._load()
        rows: List[Dict[str, Any]] = []
        for job in data["jobs"]:
            if not isinstance(job, dict):
                continue
            if not include_disabled and not bool(job.get("enabled", True)):
                continue
            rows.append(job)
        return {"kind": "cron_list", "jobs": rows}

    def add(self, job_input: Dict[str, Any]) -> Dict[str, Any]:
        now_ms = int(time.time() * 1000)
        job = self._normalize_job(job_input, now_ms=now_ms)
        data = self._load()
        data["jobs"].append(job)
        self._save(data)
        return {"kind": "cron_job", "action": "add", "job": job}

    def update(self, job_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        data = self._load()
        idx = self._find_job_index(data["jobs"], job_id)
        if idx < 0:
            raise FileNotFoundError(f"cron job not found: {job_id}")
        now_ms = int(time.time() * 1000)
        current = data["jobs"][idx]
        if not isinstance(current, dict):
            raise RuntimeError("invalid job record")
        merged: Dict[str, Any] = dict(current)
        for k in ("name", "enabled", "delete_after_run"):
            if k in patch:
                merged[k] = patch[k]
        if "schedule" in patch and isinstance(patch["schedule"], dict):
            merged["schedule"] = patch["schedule"]
        if "payload" in patch and isinstance(patch["payload"], dict):
            merged["payload"] = patch["payload"]
        merged["updated_at_ms"] = now_ms
        merged["state"] = dict(merged.get("state") or {})
        merged["state"]["next_run_at_ms"] = next_run_ms(dict(merged["schedule"]), now_ms)
        data["jobs"][idx] = merged
        self._save(data)
        return {"kind": "cron_job", "action": "update", "job": merged}

    def remove(self, job_id: str) -> Dict[str, Any]:
        data = self._load()
        idx = self._find_job_index(data["jobs"], job_id)
        if idx < 0:
            raise FileNotFoundError(f"cron job not found: {job_id}")
        removed = data["jobs"].pop(idx)
        self._save(data)
        return {"kind": "cron_job", "action": "remove", "job": removed}

    def run(self, job_id: str, force: bool = False, executor: Optional[PayloadExecutor] = None) -> Dict[str, Any]:
        data = self._load()
        idx = self._find_job_index(data["jobs"], job_id)
        if idx < 0:
            raise FileNotFoundError(f"cron job not found: {job_id}")
        job = data["jobs"][idx]
        if not isinstance(job, dict):
            raise RuntimeError("invalid job record")
        now_ms = int(time.time() * 1000)
        due_at = int(job.get("state", {}).get("next_run_at_ms", 0) or 0)
        if (not force) and due_at > now_ms:
            return {"kind": "cron_run", "status": "skipped", "reason": "not_due", "job_id": job_id, "due_at_ms": due_at}
        out = self._execute_one(job=job, now_ms=now_ms, executor=executor)
        data["jobs"][idx] = out["job"]
        if bool(out["job"].get("delete_after_run")) and out["status"] in {"ok", "error", "skipped"}:
            data["jobs"].pop(idx)
        self._save(data)
        return out

    def runs(self, job_id: str, limit: int = 20) -> Dict[str, Any]:
        if limit < 1:
            limit = 1
        rows: List[Dict[str, Any]] = []
        try:
            text = self.runs_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"kind": "cron_runs", "job_id": job_id, "runs": []}
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if str(row.get("job_id", "")) == job_id:
                rows.append(row)
        return {"kind": "cron_runs", "job_id": job_id, "runs": rows[-limit:][::-1]}

    def run_due(self, max_jobs: int = 5, executor: Optional[PayloadExecutor] = None) -> Dict[str, Any]:
        if max_jobs < 1:
            max_jobs = 1
        lock_path = self.store_path.with_suffix(self.store_path.suffix + ".lock")
        if not self._acquire_lock(lock_path):
            return {"kind": "cron_run_due", "ran": [], "skipped": "locked"}
        try:
            data = self._load()
            now_ms = int(time.time() * 1000)
            changed = False
            ran: List[Dict[str, Any]] = []
            idx = 0
            while idx < len(data["jobs"]) and len(ran) < max_jobs:
                job = data["jobs"][idx]
                if not isinstance(job, dict) or not bool(job.get("enabled", True)):
                    idx += 1
                    continue
                due_at = int(job.get("state", {}).get("next_run_at_ms", 2**62))
                if due_at > now_ms:
                    idx += 1
                    continue
                out = self._execute_one(job=job, now_ms=now_ms, executor=executor)
                changed = True
                if bool(out["job"].get("delete_after_run")):
                    data["jobs"].pop(idx)
                else:
                    data["jobs"][idx] = out["job"]
                    idx += 1
                ran.append({"job_id": out["job_id"], "status": out["status"], "duration_ms": out["duration_ms"]})
            if changed:
                self._save(data)
            return {"kind": "cron_run_due", "ran": ran}
        finally:
            self._release_lock(lock_path)

    def _execute_one(self, job: Dict[str, Any], now_ms: int, executor: Optional[PayloadExecutor]) -> Dict[str, Any]:
        job_id = str(job.get("id", ""))
        state = dict(job.get("state") or {})
        job["state"] = state
        state["running_at_ms"] = now_ms
        started = time.time()
        status = "ok"
        error = ""
        output: Dict[str, Any] = {}
        try:
            output = self._execute_payload(job, executor=executor)
        except Exception as err:
            status = "error"
            error = str(err)
        duration_ms = int((time.time() - started) * 1000)
        state["running_at_ms"] = None
        state["last_run_at_ms"] = now_ms
        state["last_status"] = status
        state["last_error"] = error
        state["last_duration_ms"] = duration_ms
        nxt = next_run_ms(dict(job.get("schedule") or {}), now_ms)
        state["next_run_at_ms"] = nxt
        if nxt is None and str(job.get("schedule", {}).get("kind", "")).lower() == "at":
            job["enabled"] = False
        self._append_run(
            {
                "ts_ms": now_ms,
                "job_id": job_id,
                "status": status,
                "error": error,
                "duration_ms": duration_ms,
            }
        )
        return {
            "kind": "cron_run",
            "job_id": job_id,
            "status": status,
            "error": error,
            "duration_ms": duration_ms,
            "output": output,
            "job": job,
        }

    def _execute_payload(self, job: Dict[str, Any], executor: Optional[PayloadExecutor]) -> Dict[str, Any]:
        payload = dict(job.get("payload") or {})
        if executor is not None:
            return executor(payload, self.workspace_root)
        kind = str(payload.get("kind", "")).strip().lower()
        if kind == "command":
            command = str(payload.get("command", "")).strip()
            if not command:
                raise ValueError("payload.command is required")
            raw_cwd = str(payload.get("cwd", "."))
            safe_cwd = (self.workspace_root / raw_cwd).resolve()
            try:
                safe_cwd.relative_to(self.workspace_root)
            except ValueError as err:
                raise ValueError(f"cwd escapes workspace: {raw_cwd}") from err
            if not safe_cwd.exists() or not safe_cwd.is_dir():
                raise FileNotFoundError(f"cwd not found: {raw_cwd}")
            timeout_s = max(1.0, min(float(payload.get("timeout_ms", 20000)) / 1000.0, 120.0))
            started = time.time()
            argv = ["powershell", "-NoProfile", "-Command", command] if os.name == "nt" else ["/bin/sh", "-lc", command]
            proc = subprocess.run(
                argv,
                cwd=str(safe_cwd),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                shell=False,
                check=False,
            )
            return {
                "ok": proc.returncode == 0,
                "exit_code": proc.returncode,
                "timed_out": False,
                "duration_ms": int((time.time() - started) * 1000),
                "cwd": str(safe_cwd.relative_to(self.workspace_root)).replace("\\", "/") or ".",
                "argv": argv,
                "stdout": proc.stdout or "",
                "stderr": proc.stderr or "",
            }
        if kind == "note":
            text = str(payload.get("text", "")).strip()
            if not text:
                raise ValueError("payload.text is required")
            return {"ok": True, "note": text}
        raise ValueError(f"unsupported payload.kind: {kind}")

    def _normalize_job(self, job_input: Dict[str, Any], now_ms: int) -> Dict[str, Any]:
        if not isinstance(job_input, dict):
            raise ValueError("job must be an object")
        schedule = dict(job_input.get("schedule") or {})
        payload = dict(job_input.get("payload") or {})
        kind = str(schedule.get("kind", "")).strip().lower()
        if kind not in {"at", "every", "cron"}:
            raise ValueError("schedule.kind must be one of: at, every, cron")
        payload_kind = str(payload.get("kind", "")).strip().lower()
        if payload_kind not in {"command", "note"}:
            raise ValueError("payload.kind must be one of: command, note")
        nxt = next_run_ms(schedule, now_ms)
        if nxt is None:
            raise ValueError("schedule cannot produce a future run time")
        return {
            "id": str(job_input.get("id", "")).strip() or uuid.uuid4().hex[:12],
            "name": str(job_input.get("name", "cron-job")).strip() or "cron-job",
            "enabled": bool(job_input.get("enabled", True)),
            "delete_after_run": bool(job_input.get("delete_after_run", False)),
            "created_at_ms": now_ms,
            "updated_at_ms": now_ms,
            "schedule": schedule,
            "payload": payload,
            "state": {
                "next_run_at_ms": nxt,
                "running_at_ms": None,
                "last_run_at_ms": None,
                "last_status": None,
                "last_error": "",
                "last_duration_ms": None,
            },
        }

    def _find_job_index(self, jobs: List[Any], job_id: str) -> int:
        target = str(job_id).strip()
        for idx, row in enumerate(jobs):
            if isinstance(row, dict) and str(row.get("id", "")) == target:
                return idx
        return -1

    def _append_run(self, row: Dict[str, Any]) -> None:
        self.runs_path.parent.mkdir(parents=True, exist_ok=True)
        with self.runs_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(row, ensure_ascii=True) + "\n")

    def _acquire_lock(self, lock_path: Path, stale_after_sec: float = 30.0) -> bool:
        now = time.time()
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {int(now)}".encode("utf-8"))
            os.close(fd)
            return True
        except FileExistsError:
            try:
                st = lock_path.stat()
                if now - st.st_mtime > stale_after_sec:
                    lock_path.unlink(missing_ok=True)
                    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(fd, f"{os.getpid()} {int(now)}".encode("utf-8"))
                    os.close(fd)
                    return True
            except Exception:
                return False
            return False

    def _release_lock(self, lock_path: Path) -> None:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass
