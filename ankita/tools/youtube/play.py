from tools.youtube.browser import get_page
import time

def run(query="", **kwargs):
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
        except:
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
            except:
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
        
        clicked = False
        for selector in video_selectors:
            try:
                video = page.locator(selector).first
                if video.is_visible(timeout=5000):
                    video.click()
                    clicked = True
                    break
            except:
                continue
        
        time.sleep(2)  # Let video start loading

        return {"status": "success", "query": query}
    except Exception as e:
        print(f"[YouTube] Error: {e}")
        return {"status": "fail", "reason": str(e)}
