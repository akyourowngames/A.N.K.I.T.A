from tools.youtube.browser import get_page, reset
import time

def run(**kwargs):
    last_err = None
    for attempt in range(2):
        try:
            page = get_page()
            page.goto("https://www.youtube.com")
            time.sleep(2)  # Wait for page load
            return {"status": "success"}
        except Exception as e:
            last_err = e
            msg = str(e)
            print(f"[YouTube] Error: {msg}")
            if attempt == 0 and ("Target page" in msg or "has been closed" in msg):
                reset()
                time.sleep(0.3)
                continue
            break
    return {"status": "fail", "reason": str(last_err)}
