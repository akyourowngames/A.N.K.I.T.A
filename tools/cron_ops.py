from pathlib import Path
from typing import Any, Dict

from corn import CornService


def cron_action(
    workspace_root: Path,
    action: str,
    job: Dict[str, Any] | None = None,
    job_id: str | None = None,
    patch: Dict[str, Any] | None = None,
    include_disabled: bool = False,
    mode: str = "due",
    limit: int = 20,
) -> Dict[str, Any]:
    service = CornService(workspace_root=workspace_root)
    op = str(action or "").strip().lower()
    if op == "status":
        return service.status()
    if op == "list":
        return service.list(include_disabled=bool(include_disabled))
    if op == "add":
        return service.add(dict(job or {}))
    if op == "update":
        target = str(job_id or "").strip()
        if not target:
            raise ValueError("job_id is required for cron.update")
        return service.update(target, dict(patch or {}))
    if op == "remove":
        target = str(job_id or "").strip()
        if not target:
            raise ValueError("job_id is required for cron.remove")
        return service.remove(target)
    if op == "run":
        target = str(job_id or "").strip()
        if not target:
            raise ValueError("job_id is required for cron.run")
        return service.run(target, force=(str(mode).lower() == "force"))
    if op == "runs":
        target = str(job_id or "").strip()
        if not target:
            raise ValueError("job_id is required for cron.runs")
        return service.runs(target, limit=int(limit))
    if op == "run_due":
        return service.run_due(max_jobs=max(1, int(limit)))
    raise ValueError(f"unsupported cron action: {action}")

