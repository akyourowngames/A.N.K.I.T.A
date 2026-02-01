from tools.youtube.browser import get_page
import time

def run(**kwargs):
    try:
        page = get_page()
        page.goto("https://www.youtube.com")
        time.sleep(2)  # Wait for page load
        return {"status": "success"}
    except Exception as e:
        print(f"[YouTube] Error: {e}")
        return {"status": "fail", "reason": str(e)}
