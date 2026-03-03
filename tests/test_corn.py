import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from corn.schedule import next_run_ms
from corn.service import CornService


class CornScheduleTests(unittest.TestCase):
    def test_at_schedule(self) -> None:
        now = datetime.now(timezone.utc)
        at = (now + timedelta(minutes=5)).isoformat()
        out = next_run_ms({"kind": "at", "at": at}, int(now.timestamp() * 1000))
        self.assertIsNotNone(out)
        self.assertGreater(out, int(now.timestamp() * 1000))

    def test_every_schedule(self) -> None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        out = next_run_ms({"kind": "every", "every_ms": 60_000, "anchor_ms": now_ms}, now_ms)
        self.assertEqual(out, now_ms + 60_000)

    def test_cron_schedule(self) -> None:
        now = datetime.now(timezone.utc)
        minute = (now.minute + 2) % 60
        expr = f"{minute} * * * *"
        out = next_run_ms({"kind": "cron", "expr": expr}, int(now.timestamp() * 1000))
        self.assertIsNotNone(out)


class CornServiceTests(unittest.TestCase):
    def test_add_list_run_remove(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            svc = CornService(workspace_root=root)
            now = datetime.now(timezone.utc)
            at = (now + timedelta(minutes=1)).isoformat()
            added = svc.add(
                {
                    "name": "test",
                    "schedule": {"kind": "at", "at": at},
                    "payload": {"kind": "note", "text": "hello"},
                }
            )
            jid = str(added["job"]["id"])
            listed = svc.list()
            self.assertEqual(len(listed["jobs"]), 1)
            run = svc.run(jid, force=True)
            self.assertEqual(run["status"], "ok")
            runs = svc.runs(jid)
            self.assertTrue(len(runs["runs"]) >= 1)
            removed = svc.remove(jid)
            self.assertEqual(str(removed["job"]["id"]), jid)


if __name__ == "__main__":
    unittest.main(verbosity=2)

