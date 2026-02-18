import os
import time
from pathlib import Path

from dotenv import load_dotenv

from corn import CornService

WORKSPACE_ROOT = Path.cwd().resolve()


def main() -> None:
    load_dotenv()
    poll_sec = max(1.0, min(float(os.getenv("CORN_POLL_INTERVAL_SEC", "5")), 300.0))
    max_jobs = max(1, min(int(os.getenv("CORN_MAX_JOBS_PER_TICK", "5")), 50))
    service = CornService(workspace_root=WORKSPACE_ROOT)

    print("ANKITA Corn Worker")
    print(f"Workspace: {WORKSPACE_ROOT}")
    print(f"Poll interval: {poll_sec}s")
    print(f"Max jobs/tick: {max_jobs}")

    while True:
        try:
            result = service.run_due(max_jobs=max_jobs)
            ran = result.get("ran", [])
            if isinstance(ran, list) and ran:
                print(f"[corn] executed {len(ran)} job(s)")
                for row in ran:
                    if isinstance(row, dict):
                        print(f"[corn] {row.get('job_id')} -> {row.get('status')} ({row.get('duration_ms')} ms)")
            time.sleep(poll_sec)
        except KeyboardInterrupt:
            print("\nStopping Corn worker.")
            break
        except Exception as err:
            print(f"[corn-error] {err}")
            time.sleep(poll_sec)


if __name__ == "__main__":
    main()

