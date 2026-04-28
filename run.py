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

def _validate_startup():

    from config import GROQ_API_KEY, CHATS_DATA_DIR, LEARNING_DATA_DIR
    if not GROQ_API_KEY or len(GROQ_API_KEY.strip()) < 10:
        print("[WARN] GROQ_API_KEY is missing or invalid. Chat will not work.")

    if not CHATS_DATA_DIR.exists() or not CHATS_DATA_DIR.is_dir():
        print("[WARN] CHATS_DATA_DIR does not exist or is not writable.")

    if not LEARNING_DATA_DIR.exists() or not LEARNING_DATA_DIR.is_dir():
        print("[WARN] LEARNING_DATA_DIR does not exist or is not writable.")

if __name__ == "__main__":
    _validate_startup()
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
