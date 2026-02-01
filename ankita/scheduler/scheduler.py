import json
import time
import os
from datetime import datetime

# Fix imports for running from scheduler folder
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ankita_core import handle_event

JOBS_PATH = os.path.join(os.path.dirname(__file__), "jobs.json")

def load_jobs():
    with open(JOBS_PATH) as f:
        return json.load(f)

def should_run(job, now):
    return now.strftime("%H:%M") == job["time"]

def run():
    ran_today = set()
    print("[Scheduler] Running... Press Ctrl+C to stop.")

    while True:
        now = datetime.now()
        jobs = load_jobs()

        for job in jobs:
            key = (job["id"], str(now.date()))
            
            # Skip if already ran today (for daily jobs)
            if job["type"] == "daily" and key in ran_today:
                continue
            
            # Skip if already ran (for once jobs)
            if job["type"] == "once" and job["id"] in ran_today:
                continue

            if should_run(job, now):
                print(f"[Scheduler] Triggering: {job['id']} at {now.strftime('%H:%M')}")
                
                try:
                    handle_event(job["intent"], job.get("entities"))
                    print(f"[Scheduler] Completed: {job['id']}")
                except Exception as e:
                    print(f"[Scheduler] Failed: {job['id']} - {e}")

                ran_today.add(key)
                if job["type"] == "once":
                    ran_today.add(job["id"])

        time.sleep(30)

if __name__ == "__main__":
    run()
