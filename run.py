import subprocess
import sys
from pathlib import Path
import uvicorn

def _ensure_thinking_audio():
    try:
        result = subprocess.run(
            [sys.executable, "-m", "app.generate_thinking_audio"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(Path(__file__).parent),
        )
        if result.returncode != 0 and result.stderr:
            print(f"[startup] Thinking audio: {result.stderr.strip()}")
    except Exception as e:
        print(f"[startup] Thinking audio skipped: {e}")

if __name__ == "__main__":
    _ensure_thinking_audio()
    try:
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True
        )
    except OSError as e:
        if "address already in use" in str(e).lower() or "10048" in str(e):
            print("[ERROR] Port 8000 is already in use. Try another port or stop the other process.")
        else:
            print(f"[ERROR] Server failed to start: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[INFO] Server stopped by user.")
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)