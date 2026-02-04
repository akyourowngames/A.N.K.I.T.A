from playwright.sync_api import sync_playwright
import atexit

_playwright = None
_browser = None
_page = None

def _cleanup():
    global _browser, _playwright
    # Don't close - let browser stay open
    pass

atexit.register(_cleanup)


def reset():
    global _page, _browser, _playwright

    try:
        if _page and not _page.is_closed():
            _page.close()
    except Exception:
        pass

    _page = None

    try:
        if _browser:
            _browser.close()
    except Exception:
        pass

    _browser = None

    try:
        if _playwright:
            _playwright.stop()
    except Exception:
        pass

    _playwright = None

def get_page():
    global _playwright, _browser, _page

    if _page:
        try:
            if not _page.is_closed():
                return _page
        except Exception:
            reset()

    _playwright = sync_playwright().start()
    _browser = _playwright.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"]
    )
    context = _browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    _page = context.new_page()
    return _page

def keep_alive():
    """Keep browser open after script ends"""
    global _page
    if _page:
        try:
            _page.wait_for_timeout(999999999)
        except:
            pass
