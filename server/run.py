"""One-command launcher: backend (uvicorn) + frontend (Next.js dev).

Usage:
    python server/run.py                 # backend :8000 + frontend :3000
    python server/run.py --no-frontend   # backend only
    python server/run.py --prod          # backend + `next start` (needs `npm run build` first)

Env overrides:
    ZUMBA_API_PORT   backend port (default 8000)
    ZUMBA_WEB_PORT   frontend port (default 3000)
"""

import argparse
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FRONTEND_DIR = ROOT / "frontend"

API_PORT = int(os.getenv("ZUMBA_API_PORT", "8000"))
WEB_PORT = int(os.getenv("ZUMBA_WEB_PORT", "3000"))
API_URL = f"http://127.0.0.1:{API_PORT}"


def _npm_cmd() -> str:
    name = "npm.cmd" if os.name == "nt" else "npm"
    found = shutil.which(name) or shutil.which("npm")
    if not found:
        raise RuntimeError("npm not found on PATH — install Node.js 20+ first.")
    return found


def _check_frontend() -> None:
    if not (FRONTEND_DIR / "package.json").exists():
        raise RuntimeError(f"frontend not found at {FRONTEND_DIR}")
    if not (FRONTEND_DIR / "node_modules").exists():
        raise RuntimeError(
            "frontend/node_modules is missing — run this once:\n"
            "    cd frontend && npm install"
        )


def _stream_output(proc: subprocess.Popen, tag: str) -> None:
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(f"[{tag}] {line.rstrip()}", flush=True)
    except Exception:
        pass


def start_frontend(prod: bool = False) -> subprocess.Popen:
    _check_frontend()
    npm = _npm_cmd()
    args = [npm, "run", "start" if prod else "dev", "--", "-p", str(WEB_PORT)]
    if prod and not (FRONTEND_DIR / ".next").exists():
        raise RuntimeError("frontend/.next is missing — run `cd frontend && npm run build` first.")
    env = dict(os.environ)
    env["PORT"] = str(WEB_PORT)
    env["NEXT_PUBLIC_API_URL"] = os.getenv("NEXT_PUBLIC_API_URL", API_URL)
    print(f"[web] starting {'`npm run start`' if prod else '`npm run dev`'} on port {WEB_PORT} ...", flush=True)
    proc = subprocess.Popen(
        args,
        cwd=str(FRONTEND_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    threading.Thread(target=_stream_output, args=(proc, "web"), daemon=True).start()
    return proc


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Zumba backend + frontend.")
    parser.add_argument("--no-frontend", action="store_true", help="backend only")
    parser.add_argument("--prod", action="store_true",
                        help="serve frontend with `next start` instead of dev mode")
    ns = parser.parse_args()

    web_proc: subprocess.Popen | None = None
    if not ns.no_frontend:
        try:
            web_proc = start_frontend(prod=ns.prod)
        except RuntimeError as exc:
            print(f"[web] {exc}", flush=True)
            print("[web] continuing with backend only.", flush=True)

    import uvicorn

    print(f"[api] backend on {API_URL}  |  frontend on http://localhost:{WEB_PORT}", flush=True)
    try:
        uvicorn.run("server.app:app", host="127.0.0.1", port=API_PORT, reload=False)
    except KeyboardInterrupt:
        pass
    finally:
        if web_proc is not None and web_proc.poll() is None:
            print("[web] stopping frontend ...", flush=True)
            web_proc.terminate()
            try:
                web_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                web_proc.kill()


if __name__ == "__main__":
    main()
