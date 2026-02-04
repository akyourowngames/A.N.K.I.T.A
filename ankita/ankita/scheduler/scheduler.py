import json
import time
import os
from datetime import datetime

# Fix imports for running from scheduler folder
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ankita_core import handle_text

JOBS_PATH = os.path.join(os.path.dirname(__file__), "jobs.json")

def load_jobs():
    with open(JOBS_PATH) as f:
        return json.load(f)


def save_jobs(jobs: list):
    with open(JOBS_PATH, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)

def should_run(job, now, started_at: float):
    # Test-mode trigger: run once after N seconds from scheduler start.
    after_seconds = job.get("after_seconds")
    if isinstance(after_seconds, (int, float)):
        if after_seconds >= 0 and (time.time() - started_at) >= float(after_seconds):
            return True

    # Normal trigger: run at HH:MM
    job_time = job.get("time")
    if isinstance(job_time, str) and job_time.strip():
        return now.strftime("%H:%M") == job_time

    return False


def _job_to_text(job: dict) -> str:
    text = job.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    # Backward-compatible path: old schema used intent + entities
    intent = str(job.get("intent", "")).strip()
    entities = job.get("entities") or {}

    if intent == "youtube.play":
        q = str(entities.get("query", "")).strip()
        return f"play {q} on youtube".strip()
    if intent == "youtube.open":
        return "open youtube"

    if intent == "notepad.write_note":
        c = str(entities.get("content", "")).strip()
        return f"write {c} in notepad".strip()
    if intent == "notepad.continue_note":
        c = str(entities.get("content", "")).strip()
        return f"continue note {c}".strip()
    if intent == "notepad.open":
        return "open notepad"

    # Last-resort fallback
    return intent or ""

def run():
    ran_today = set()
    print("[Scheduler] Running... Press Ctrl+C to stop.")

    started_at = time.time()

    try:
        while True:
            now = datetime.now()
            jobs = load_jobs()

            fast_tick = any(isinstance(j.get("after_seconds"), (int, float)) for j in jobs)

            jobs_changed = False

            for job in list(jobs):
                key = (job["id"], str(now.date()))

                # Skip if already ran today (for daily jobs)
                if job.get("type") == "daily" and key in ran_today:
                    continue

                # Skip if already ran (for once jobs)
                if job.get("type") == "once" and job.get("id") in ran_today:
                    continue

                if should_run(job, now, started_at):
                    print(f"[Scheduler] Triggering: {job['id']} at {now.strftime('%H:%M')}")

                    try:
                        text = _job_to_text(job)
                        print(f"[Scheduler] Triggering Ankita: {text}")
                        handle_text(text, source="scheduler")
                        print(f"[Scheduler] Completed: {job['id']}")

                        # For once jobs, remove after successful execution so they don't re-run on restart.
                        if job.get("type") == "once" and job in jobs:
                            jobs.remove(job)
                            jobs_changed = True
                    except Exception as e:
                        print(f"[Scheduler] Failed: {job['id']} - {e}")

                    ran_today.add(key)
                    if job.get("type") == "once":
                        ran_today.add(job["id"])

            if jobs_changed:
                save_jobs(jobs)

            time.sleep(1 if fast_tick else 30)
    except KeyboardInterrupt:
        print("\n[Scheduler] Stopped.")
        return

if __name__ == "__main__":
    run()
