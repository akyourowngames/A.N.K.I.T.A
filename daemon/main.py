from __future__ import annotations

import argparse
from pathlib import Path

from daemon.project_daemon import ProjectDaemon


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ANKITA project daemon.")
    parser.add_argument("--once", action="store_true", help="Run one daemon cycle and exit.")
    parser.add_argument("--root", default=".", help="Project root.")
    args = parser.parse_args()

    daemon = ProjectDaemon.from_root(Path(args.root).resolve())
    if args.once:
        event = daemon.run_once()
        print(event["summary"])
        print(f"Report: {daemon.config.report_path}")
        return
    daemon.run_forever()


if __name__ == "__main__":
    main()
