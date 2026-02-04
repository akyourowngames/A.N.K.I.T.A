from tools.youtube.browser import get_page, reset
import time

def run(query="", **kwargs):
    last_err = None
    for attempt in range(2):
        try:
            page = get_page()

            if not page.url.startswith("https://www.youtube.com"):
                page.goto("https://www.youtube.com")
                time.sleep(3)
 
            # Handle cookie consent if present
            try:
                accept_btn = page.locator("button:has-text('Accept all')")
                if accept_btn.is_visible(timeout=2000):
                    accept_btn.click()
                    time.sleep(1)
            except Exception:
                pass
 
            # Try multiple search box selectors
            search_selectors = [
                "input#search",
                "input[name='search_query']",
                "ytd-searchbox input",
                "[aria-label='Search']"
            ]
 
            search_box = None
            for selector in search_selectors:
                try:
                    search_box = page.locator(selector)
                    if search_box.is_visible(timeout=3000):
                        break
                except Exception:
                    continue
 
            if not search_box:
                return {"status": "fail", "reason": "Search box not found"}
 
            search_box.fill(query)
            page.keyboard.press("Enter")

            time.sleep(3)  # Wait for search results
 
            # Click first video
            video_selectors = [
                "ytd-video-renderer a#thumbnail",
                "ytd-video-renderer a#video-title",
                "a.ytd-thumbnail"
            ]
 
            for selector in video_selectors:
                try:
                    video = page.locator(selector).first
                    if video.is_visible(timeout=5000):
                        video.click()
                        break
                except Exception:
                    continue
 
            time.sleep(2)  # Let video start loading

            return {"status": "success", "query": query}
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
