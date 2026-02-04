import json
import os
import uuid


_ANKITA_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_JOBS_PATH = os.path.join(_ANKITA_ROOT, "scheduler", "jobs.json")


def _load_jobs():
    if not os.path.exists(_JOBS_PATH):
        return []
    with open(_JOBS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data if isinstance(data, list) else []


def _save_jobs(jobs: list):
    os.makedirs(os.path.dirname(_JOBS_PATH), exist_ok=True)
    with open(_JOBS_PATH, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)


def run(text: str = "", type: str = "once", after_seconds=None, time=None, **kwargs):
    text = (text or "").strip()
    if not text:
        return {"status": "fail", "reason": "Missing job text"}

    job_type = (type or "").strip().lower() or "once"
    if job_type not in ("once", "daily"):
        job_type = "once"

    job = {
        "id": f"job_{uuid.uuid4().hex[:8]}",
        "type": job_type,
        "text": text,
    }

    if after_seconds is not None:
        try:
            job["after_seconds"] = int(after_seconds)
        except Exception:
            return {"status": "fail", "reason": "Invalid after_seconds"}

    if time is not None:
        time_str = str(time).strip()
        if time_str:
            job["time"] = time_str

    jobs = _load_jobs()
    jobs.append(job)
    _save_jobs(jobs)

    return {"status": "success", "job": job, "jobs_path": _JOBS_PATH}
