import subprocess
import time

def run(**kwargs):
    # Launch Notepad in background (non-blocking)
    subprocess.Popen(["notepad.exe"])
    time.sleep(1.0)  # Wait for Notepad to fully open
    return {"status": "success"}
