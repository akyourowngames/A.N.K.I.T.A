"""
Instagram Automation Tool - Full automation using DOM, Accessibility, and OCR.

Capabilities:
- Open Instagram (web/app)
- Login/Logout
- Navigate feed, explore, reels
- Like/Unlike posts
- Follow/Unfollow users
- Comment on posts
- Send DMs
- Search users/hashtags
- Post stories/photos
- View notifications

Uses Playwright for web automation with fallback to accessibility APIs.
"""
import os
import time
import json
import re
from pathlib import Path


# ============== CONFIGURATION ==============

INSTAGRAM_URL = "https://www.instagram.com"
INSTAGRAM_MOBILE_URL = "https://www.instagram.com"
DATA_DIR = Path(__file__).parent.parent.parent / "data" / "instagram"
COOKIES_FILE = DATA_DIR / "cookies.json"
SESSION_FILE = DATA_DIR / "session.json"

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ============== MEMORY INTEGRATION ==============

def _get_memory():
    """Get the shared memory instance."""
    try:
        from memory.conversation_memory import get_conversation_memory
        return get_conversation_memory()
    except ImportError:
        return None


def _track_action(action: str, entities: dict = None, result: dict = None):
    """Track Instagram actions in memory."""
    memory = _get_memory()
    if memory:
        summary = f"Instagram: {action}"
        if entities:
            if "username" in entities:
                summary += f" @{entities['username']}"
            if "query" in entities:
                summary += f" '{entities['query']}'"
        
        memory.add_context(
            summary=summary,
            action=f"instagram.{action}",
            entities=entities or {},
            result=result or {},
            topic="social"
        )
        
        # Set tool-specific context
        if action in ("profile", "follow", "unfollow", "dm"):
            if entities and "username" in entities:
                memory.set_tool_context("instagram", "last_profile", entities["username"])
                memory.share_content("username", entities["username"], "instagram")
        
        if action == "search" and entities and "query" in entities:
            memory.set_tool_context("instagram", "last_search", entities["query"])
        
        if action in ("navigate", "feed", "explore", "reels"):
            memory.set_tool_context("instagram", "current_page", action)
        
        if action == "like":
            likes = memory.get_tool_context("instagram", "likes_today", 0)
            memory.set_tool_context("instagram", "likes_today", likes + 1, ttl_minutes=1440)
        
        if action == "dm":
            dms = memory.get_tool_context("instagram", "dms_sent", 0)
            memory.set_tool_context("instagram", "dms_sent", dms + 1, ttl_minutes=1440)
            if entities and "username" in entities:
                recent_dms = memory.get_tool_context("instagram", "recent_dms", [])
                if entities["username"] not in recent_dms:
                    recent_dms.insert(0, entities["username"])
                memory.set_tool_context("instagram", "recent_dms", recent_dms[:10])


# ============== BROWSER UTILITIES (SELENIUM) ==============

_driver = None
_browser = None
_context = None
_page = None
_playwright = None
_chrome_process = None


def _find_chrome_path():
    """Find Chrome executable path."""
    chrome_paths = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    
    for path in chrome_paths:
        if os.path.exists(path):
            return path
    
    return None


def _find_chrome_profile():
    """Find the Chrome profile directory for 'Krish'."""
    chrome_user_data = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
    profile_name = "Default"
    
    if os.path.exists(chrome_user_data):
        local_state_path = os.path.join(chrome_user_data, "Local State")
        if os.path.exists(local_state_path):
            try:
                with open(local_state_path, 'r', encoding='utf-8') as f:
                    local_state = json.load(f)
                
                profiles = local_state.get("profile", {}).get("info_cache", {})
                for profile_dir, profile_info in profiles.items():
                    name = profile_info.get("name", "").lower()
                    if "krish" in name:
                        profile_name = profile_dir
                        print(f"Found Chrome profile: {profile_name} ({profile_info.get('name')})")
                        break
            except Exception as e:
                print(f"Error reading Chrome profiles: {e}")
    
    return chrome_user_data, profile_name


def _open_in_chrome(url: str):
    """Open URL in regular Chrome with your profile (for navigation)."""
    import subprocess
    
    chrome_path = _find_chrome_path()
    chrome_user_data, profile_name = _find_chrome_profile()
    
    if chrome_path:
        try:
            subprocess.Popen([
                chrome_path,
                f"--profile-directory={profile_name}",
                url
            ], shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            print(f"Chrome launch error: {e}")
    
    # Fallback
    import webbrowser
    webbrowser.open(url)
    return True


def _get_driver():
    """Get Selenium driver with undetected-chromedriver using your profile."""
    global _driver
    
    if _driver:
        try:
            _driver.current_url  # Test if driver is still valid
            return _driver
        except:
            _driver = None
    
    try:
        import undetected_chromedriver as uc
        from selenium.webdriver.chrome.options import Options
        
        chrome_user_data, profile_name = _find_chrome_profile()
        
        options = uc.ChromeOptions()
        options.add_argument(f"--user-data-dir={chrome_user_data}")
        options.add_argument(f"--profile-directory={profile_name}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        
        print(f"Launching Chrome with profile: {profile_name}")
        
        _driver = uc.Chrome(options=options, use_subprocess=True)
        _driver.set_window_size(1280, 800)
        
        return _driver
        
    except Exception as e:
        print(f"Driver launch error: {e}")
        return None


def _close_driver():
    """Close Selenium driver."""
    global _driver
    
    if _driver:
        try:
            _driver.quit()
        except:
            pass
        _driver = None






async def _close_browser():
    """Close browser connection (not Chrome itself)."""
    global _browser, _context, _page, _playwright, _chrome_process
    
    if _context:
        try:
            await _save_storage_state()
            await _context.close()
        except Exception:
            pass
        _context = None
        _page = None

    if _browser:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    
    if _playwright:
        try:
            await _playwright.stop()
        except:
            pass
        _playwright = None
    
    # Optionally close Chrome process
    if _chrome_process:
        try:
            _chrome_process.terminate()
        except:
            pass
        _chrome_process = None


def _sync_wrapper(coro):
    """Run async function synchronously."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(coro)


async def _ensure_playwright_page():
    """Ensure a Playwright page is available and reuse it across calls."""
    global _browser, _context, _page, _playwright

    if _page is not None:
        try:
            await _page.title()
            return _page
        except Exception:
            _page = None

    if _context is not None:
        try:
            _ = _context.pages
        except Exception:
            _context = None

    if _browser is not None:
        try:
            _ = _browser.is_connected()
        except Exception:
            _browser = None

    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        raise RuntimeError(
            "Playwright is required for this tool. Install it with: pip install playwright && playwright install"
        ) from e

    if _playwright is None:
        _playwright = await async_playwright().start()

    if _browser is None:
        _browser = await _playwright.chromium.launch(headless=False)

    if _context is None:
        storage_state_path = str(SESSION_FILE.resolve()) if SESSION_FILE.exists() else None
        _context = await _browser.new_context(
            storage_state=storage_state_path,
            viewport={"width": 1280, "height": 800},
        )

    if _page is None:
        pages = _context.pages
        _page = pages[0] if pages else await _context.new_page()

    try:
        _page.set_default_timeout(30000)
        _page.set_default_navigation_timeout(30000)
    except Exception:
        pass

    return _page


async def _save_storage_state():
    global _context
    if _context is None:
        return
    try:
        await _context.storage_state(path=str(SESSION_FILE.resolve()))
    except Exception:
        pass


# ============== INSTAGRAM ACTIONS ==============

async def _instagram_open(page):
    """Open Instagram and wait for load."""
    try:
        # Navigate to Instagram
        await page.goto(INSTAGRAM_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)
        
        # Check if logged in
        is_logged_in = await page.query_selector('svg[aria-label="Home"]') is not None
        
        return {
            "status": "success",
            "message": "Instagram opened" + (" (logged in)" if is_logged_in else " (not logged in)"),
            "logged_in": is_logged_in
        }
    except Exception as e:
        return {"status": "fail", "reason": f"Error opening Instagram: {str(e)}"}


async def _instagram_login(page, username: str, password: str):
    """Log into Instagram."""
    if not username or not password:
        return {"status": "fail", "reason": "Username and password required"}
    
    try:
        await page.goto(f"{INSTAGRAM_URL}/accounts/login/", wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)
        
        # Accept cookies if present
        cookie_btn = await page.query_selector('button:has-text("Allow")')
        if cookie_btn:
            await cookie_btn.click()
            await page.wait_for_timeout(1000)
        
        # Fill login form
        username_input = await page.query_selector('input[name="username"]')
        password_input = await page.query_selector('input[name="password"]')
        
        if not username_input or not password_input:
            return {"status": "fail", "reason": "Login form not found"}
        
        await username_input.fill(username)
        await password_input.fill(password)
        
        # Click login button
        login_btn = await page.query_selector('button[type="submit"]')
        if login_btn:
            await login_btn.click()
        
        await page.wait_for_timeout(5000)
        
        # Check for 2FA
        if "two_factor" in page.url or await page.query_selector('input[name="verificationCode"]'):
            return {
                "status": "pending",
                "message": "Two-factor authentication required. Please enter the code.",
                "requires_2fa": True
            }
        
        # Check if login successful
        is_logged_in = await page.query_selector('svg[aria-label="Home"]') is not None
        
        if is_logged_in:
            return {"status": "success", "message": f"Logged in as {username}"}
        else:
            # Check for error messages
            error = await page.query_selector('[role="alert"]')
            error_text = await error.inner_text() if error else "Login failed"
            return {"status": "fail", "reason": error_text}
            
    except Exception as e:
        return {"status": "fail", "reason": f"Login error: {str(e)}"}

async def _instagram_verify_2fa(page, code: str):
    """Verify 2FA code."""
    try:
        code_input = await page.query_selector('input[name="verificationCode"]')
        if not code_input:
            return {"status": "fail", "reason": "2FA input not found"}
        
        await code_input.fill(code)
        
        confirm_btn = await page.query_selector('button:has-text("Confirm")')
        if confirm_btn:
            await confirm_btn.click()
        
        await page.wait_for_timeout(5000)
        
        is_logged_in = await page.query_selector('svg[aria-label="Home"]') is not None
        
        if is_logged_in:
            return {"status": "success", "message": "2FA verified, logged in"}
        else:
            return {"status": "fail", "reason": "Invalid 2FA code"}
            
    except Exception as e:
        return {"status": "fail", "reason": f"2FA verification error: {str(e)}"}


async def _instagram_navigate(page, destination: str):
    """Navigate to a specific Instagram section."""
    destinations = {
        "home": "/",
        "feed": "/",
        "explore": "/explore/",
        "reels": "/reels/",
        "search": "/explore/search/",
        "notifications": "/notifications/",
        "messages": "/direct/inbox/",
        "dm": "/direct/inbox/",
        "inbox": "/direct/inbox/",
        "profile": "/accounts/edit/",
        "settings": "/accounts/edit/",
    }
    
    dest = destinations.get(destination.lower(), f"/{destination}/")
    url = f"{INSTAGRAM_URL}{dest}"
    
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)
        
        return {
            "status": "success",
            "message": f"Navigated to {destination}",
            "url": page.url
        }
    except Exception as e:
        return {"status": "fail", "reason": f"Navigation error: {str(e)}"}


async def _instagram_search(page, query: str, search_type: str = "all"):
    """Search Instagram for users, hashtags, or places."""
    
    # First, try navigating to Instagram home and using the search from sidebar
    current_url = page.url
    if "instagram.com" not in current_url:
        await page.goto(INSTAGRAM_URL, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)
    
    # Strategy 1: Click on Search icon in the sidebar
    search_icon = await page.query_selector('svg[aria-label="Search"]')
    if search_icon:
        try:
            parent = await search_icon.query_selector("xpath=ancestor::a | ancestor::div[@role='button']")
            if parent:
                await parent.click()
            else:
                await search_icon.click()
            await page.wait_for_timeout(1500)
        except Exception:
            pass
    
    # Strategy 2: Try to find search input with multiple selectors
    search_selectors = [
        'input[placeholder*="Search"]',
        'input[aria-label*="Search"]',
        'input[type="text"][placeholder]',
        '[role="searchbox"]',
        'input[autocomplete="off"]',
    ]
    
    search_input = None
    for selector in search_selectors:
        search_input = await page.query_selector(selector)
        if search_input:
            # Verify it's visible
            is_visible = await search_input.is_visible()
            if is_visible:
                break
            search_input = None
    
    # Strategy 3: If still not found, navigate directly to explore page
    if not search_input:
        await page.goto(f"{INSTAGRAM_URL}/explore/", wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(1500)
        
        # Try clicking search icon again
        search_icon = await page.query_selector('svg[aria-label="Search"]')
        if search_icon:
            try:
                parent = await search_icon.query_selector("xpath=ancestor::a | ancestor::div[@role='button']")
                if parent:
                    await parent.click()
                else:
                    await search_icon.click()
                await page.wait_for_timeout(1500)
            except Exception:
                pass
        
        # Try finding input again
        for selector in search_selectors:
            search_input = await page.query_selector(selector)
            if search_input:
                is_visible = await search_input.is_visible()
                if is_visible:
                    break
                search_input = None
    
    if not search_input:
        return {"status": "fail", "reason": "Search input not found, sir."}
    
    # Clear and type the query
    try:
        await search_input.click()
        await page.wait_for_timeout(500)
        await search_input.fill("")  # Clear first
        await search_input.type(query, delay=50)  # Type with delay for better detection
        await page.wait_for_timeout(2500)  # Wait for search results to load
    except Exception as e:
        return {"status": "fail", "reason": f"Error typing search query: {str(e)}"}
    
    # Get search results from dropdown
    results = []
    
    # Try multiple result selectors
    result_selectors = [
        'a[href^="/"][role="link"]',  # Profile links
        '[role="listitem"] a',  # List items
        'a[href*="/"]',  # Any links
    ]
    
    for selector in result_selectors:
        result_items = await page.query_selector_all(selector)
        for item in result_items[:15]:
            try:
                href = await item.get_attribute("href")
                if not href or href in ("/", "#") or "explore" in href:
                    continue
                
                text = await item.inner_text()
                text = text.strip()
                
                # Filter relevant results
                if text and (query.lower() in text.lower() or query.lower() in (href or "").lower()):
                    result_entry = {"text": text, "href": href}
                    if result_entry not in results:
                        results.append(result_entry)
            except Exception:
                continue
        
        if results:
            break
    
    # Click on first result if available (optional - navigate to top result)
    if results:
        return {
            "status": "success",
            "message": f"Found {len(results)} results for '{query}', sir.",
            "results": results[:10]
        }
    
    return {
        "status": "success",
        "message": f"Search completed for '{query}', but no matching results found in dropdown.",
        "results": []
    }


async def _instagram_like(page, post_url: str = None):
    """Like a post (current or specific URL)."""
    if post_url:
        await page.goto(post_url, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(2500)
    
    # Multiple selectors for like button
    like_selectors = [
        'svg[aria-label="Like"]',
        '[aria-label="Like"]',
        'button svg[aria-label="Like"]',
    ]
    
    like_btn = None
    for selector in like_selectors:
        like_btn = await page.query_selector(selector)
        if like_btn:
            break
    
    if not like_btn:
        # Check if already liked
        unlike_selectors = [
            'svg[aria-label="Unlike"]',
            '[aria-label="Unlike"]',
        ]
        for selector in unlike_selectors:
            unlike_btn = await page.query_selector(selector)
            if unlike_btn:
                return {"status": "success", "message": "Post already liked, sir."}
        return {"status": "fail", "reason": "Like button not found, sir. Make sure you're viewing a post."}
    
    # Click the parent button or the SVG itself
    try:
        parent = await like_btn.query_selector("xpath=ancestor::button | ancestor::div[@role='button']")
        if parent:
            await parent.click()
        else:
            await like_btn.click()
        await page.wait_for_timeout(1500)
    except Exception as e:
        return {"status": "fail", "reason": f"Error clicking like button: {str(e)}"}
    
    return {"status": "success", "message": "Post liked, sir."}


async def _instagram_unlike(page, post_url: str = None):
    """Unlike a post."""
    if post_url:
        await page.goto(post_url, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(2500)
    
    unlike_selectors = [
        'svg[aria-label="Unlike"]',
        '[aria-label="Unlike"]',
    ]
    
    unlike_btn = None
    for selector in unlike_selectors:
        unlike_btn = await page.query_selector(selector)
        if unlike_btn:
            break
    
    if not unlike_btn:
        return {"status": "success", "message": "Post not liked, sir."}
    
    try:
        parent = await unlike_btn.query_selector("xpath=ancestor::button | ancestor::div[@role='button']")
        if parent:
            await parent.click()
        else:
            await unlike_btn.click()
        await page.wait_for_timeout(1500)
    except Exception as e:
        return {"status": "fail", "reason": f"Error clicking unlike button: {str(e)}"}
    
    return {"status": "success", "message": "Post unliked, sir."}


async def _instagram_comment(page, text: str, post_url: str = None):
    """Comment on a post."""
    if post_url:
        await page.goto(post_url, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(2500)
    
    # First, try to click the comment icon to focus the comment area
    comment_icon_selectors = [
        'svg[aria-label="Comment"]',
        '[aria-label="Comment"]',
        'svg[aria-label="Add a comment"]',
    ]
    
    for selector in comment_icon_selectors:
        try:
            comment_icon = await page.query_selector(selector)
            if comment_icon:
                parent = await comment_icon.query_selector("xpath=ancestor::button | ancestor::div[@role='button'] | ancestor::span")
                if parent:
                    await parent.click()
                else:
                    await comment_icon.click()
                await page.wait_for_timeout(1000)
                break
        except Exception:
            continue
    
    # Find comment input with multiple selectors
    comment_input_selectors = [
        'textarea[placeholder*="comment" i]',
        'textarea[placeholder*="Comment" i]',
        'textarea[aria-label*="comment" i]',
        'textarea[aria-label*="Comment" i]',
        '[contenteditable="true"][role="textbox"]',
        '[contenteditable="true"]',
        'textarea',
    ]
    
    comment_input = None
    is_contenteditable = False
    
    for selector in comment_input_selectors:
        elements = await page.query_selector_all(selector)
        for elem in elements:
            try:
                is_visible = await elem.is_visible()
                if is_visible:
                    # Prefer comment-specific inputs
                    placeholder = await elem.get_attribute("placeholder") or ""
                    aria_label = await elem.get_attribute("aria-label") or ""
                    if "comment" in placeholder.lower() or "comment" in aria_label.lower():
                        comment_input = elem
                        contenteditable = await elem.get_attribute("contenteditable")
                        is_contenteditable = contenteditable == "true"
                        break
                    elif not comment_input:
                        comment_input = elem
                        contenteditable = await elem.get_attribute("contenteditable")
                        is_contenteditable = contenteditable == "true"
            except Exception:
                continue
        if comment_input:
            placeholder = await comment_input.get_attribute("placeholder") or ""
            aria_label = await comment_input.get_attribute("aria-label") or ""
            if "comment" in placeholder.lower() or "comment" in aria_label.lower():
                break
    
    if not comment_input:
        return {"status": "fail", "reason": "Comment input not found, sir. Make sure you're viewing a post."}
    
    # Click and type the comment
    try:
        await comment_input.click()
        await page.wait_for_timeout(300)
        
        if is_contenteditable:
            await page.keyboard.type(text, delay=30)
        else:
            await comment_input.fill(text)
        
        await page.wait_for_timeout(800)
    except Exception as e:
        return {"status": "fail", "reason": f"Error typing comment: {str(e)}"}
    
    # Find and click post button
    post_btn_selectors = [
        'button:has-text("Post")',
        'div[role="button"]:has-text("Post")',
        '[role="button"]:has-text("Post")',
        'button[type="submit"]',
    ]
    
    posted = False
    for selector in post_btn_selectors:
        try:
            post_btn = await page.query_selector(selector)
            if post_btn:
                is_visible = await post_btn.is_visible()
                is_enabled = await post_btn.is_enabled()
                if is_visible and is_enabled:
                    await post_btn.click()
                    posted = True
                    await page.wait_for_timeout(2000)
                    break
        except Exception:
            continue
    
    # Fallback: Press Enter to post (some UIs work this way)
    if not posted:
        try:
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(2000)
            posted = True
        except Exception:
            pass
    
    if posted:
        return {"status": "success", "message": "Comment posted, sir."}
    
    return {"status": "fail", "reason": "Could not post comment, sir."}


async def _instagram_follow(page, username: str):
    """Follow a user."""
    await page.goto(f"{INSTAGRAM_URL}/{username}/", wait_until="domcontentloaded")
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)
    
    # Check if profile exists
    not_found = await page.query_selector("text=Sorry, this page isn't available")
    if not_found:
        return {"status": "fail", "reason": f"User @{username} not found"}
    
    # Find follow button
    follow_btn = await page.query_selector('button:has-text("Follow")')
    
    if not follow_btn:
        # Check if already following
        following_btn = await page.query_selector('button:has-text("Following")')
        if following_btn:
            return {"status": "success", "message": f"Already following @{username}"}
        return {"status": "fail", "reason": "Follow button not found"}
    
    await follow_btn.click()
    await page.wait_for_timeout(2000)
    
    return {"status": "success", "message": f"Now following @{username}"}


async def _instagram_unfollow(page, username: str):
    """Unfollow a user."""
    await page.goto(f"{INSTAGRAM_URL}/{username}/", wait_until="domcontentloaded")
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)
    
    # Find following button
    following_btn = await page.query_selector('button:has-text("Following")')
    
    if not following_btn:
        return {"status": "success", "message": f"Not following @{username}"}
    
    await following_btn.click()
    await page.wait_for_timeout(1000)
    
    # Confirm unfollow in modal
    unfollow_btn = await page.query_selector('button:has-text("Unfollow")')
    if unfollow_btn:
        await unfollow_btn.click()
    
    await page.wait_for_timeout(2000)
    
    return {"status": "success", "message": f"Unfollowed @{username}"}


async def _instagram_dm(page, username: str, message: str):
    """Send a direct message."""
    # Navigate to DM new message page
    await page.goto(f"{INSTAGRAM_URL}/direct/new/", wait_until="domcontentloaded")
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    await page.wait_for_timeout(2500)
    
    # Find search input for recipient with multiple selectors
    search_selectors = [
        'input[placeholder*="Search"]',
        'input[name="queryBox"]',
        'input[aria-label*="Search"]',
        'input[type="text"]',
    ]
    
    search_input = None
    for selector in search_selectors:
        search_input = await page.query_selector(selector)
        if search_input:
            is_visible = await search_input.is_visible()
            if is_visible:
                break
            search_input = None
    
    if not search_input:
        return {"status": "fail", "reason": "User search input not found, sir."}
    
    # Type username to search
    await search_input.click()
    await page.wait_for_timeout(300)
    await search_input.fill("")
    await search_input.type(username, delay=50)
    await page.wait_for_timeout(2500)
    
    # Select user from results - try multiple approaches
    user_found = False
    
    # Strategy 1: Click on the user result item (usually a div or span with username)
    user_selectors = [
        f'[role="button"]:has-text("{username}")',
        f'button:has-text("{username}")',
        f'div:has-text("{username}")',
        f'span:has-text("{username}")',
    ]
    
    for selector in user_selectors:
        try:
            user_option = await page.query_selector(selector)
            if user_option:
                is_visible = await user_option.is_visible()
                if is_visible:
                    await user_option.click()
                    user_found = True
                    await page.wait_for_timeout(1500)
                    break
        except Exception:
            continue
    
    # Strategy 2: Click on any clickable item in search results
    if not user_found:
        result_items = await page.query_selector_all('[role="listitem"], [role="option"]')
        for item in result_items[:5]:
            try:
                text = await item.inner_text()
                if username.lower() in text.lower():
                    await item.click()
                    user_found = True
                    await page.wait_for_timeout(1500)
                    break
            except Exception:
                continue
    
    # Strategy 3: Try clicking checkbox or radio button next to username
    if not user_found:
        checkboxes = await page.query_selector_all('input[type="checkbox"], [role="checkbox"]')
        for checkbox in checkboxes:
            try:
                # Check if this checkbox is near the username
                parent = await checkbox.query_selector("xpath=ancestor::div[contains(., '" + username + "')]")
                if parent:
                    await checkbox.click()
                    user_found = True
                    await page.wait_for_timeout(1000)
                    break
            except Exception:
                continue
    
    if not user_found:
        return {"status": "fail", "reason": f"User @{username} not found in search, sir."}
    
    # Click Next/Chat button to start conversation
    next_selectors = [
        'button:has-text("Chat")',
        'button:has-text("Next")',
        'div[role="button"]:has-text("Chat")',
        'div[role="button"]:has-text("Next")',
    ]
    
    for selector in next_selectors:
        try:
            next_btn = await page.query_selector(selector)
            if next_btn:
                is_visible = await next_btn.is_visible()
                if is_visible:
                    await next_btn.click()
                    await page.wait_for_timeout(2500)
                    break
        except Exception:
            continue
    
    # Find message input - Instagram uses both textarea and contenteditable divs
    msg_input_selectors = [
        'textarea[placeholder*="Message"]',
        'textarea[placeholder*="message"]',
        'textarea',
        '[contenteditable="true"][role="textbox"]',
        '[contenteditable="true"]',
        'div[role="textbox"]',
    ]
    
    msg_input = None
    is_contenteditable = False
    for selector in msg_input_selectors:
        msg_input = await page.query_selector(selector)
        if msg_input:
            is_visible = await msg_input.is_visible()
            if is_visible:
                # Check if it's contenteditable
                contenteditable = await msg_input.get_attribute("contenteditable")
                is_contenteditable = contenteditable == "true"
                break
            msg_input = None
    
    if not msg_input:
        return {"status": "fail", "reason": "Message input not found, sir."}
    
    # Type the message
    await msg_input.click()
    await page.wait_for_timeout(300)
    
    if is_contenteditable:
        # For contenteditable divs, use keyboard typing
        await page.keyboard.type(message, delay=30)
    else:
        await msg_input.fill(message)
    
    await page.wait_for_timeout(500)
    
    # Send message - try button first, then Enter key
    send_selectors = [
        'button:has-text("Send")',
        'div[role="button"]:has-text("Send")',
        'svg[aria-label="Send Message"]',
    ]
    
    sent = False
    for selector in send_selectors:
        try:
            send_btn = await page.query_selector(selector)
            if send_btn:
                is_visible = await send_btn.is_visible()
                if is_visible:
                    # If it's an SVG, click its parent
                    if "svg" in selector:
                        parent = await send_btn.query_selector("xpath=ancestor::button | ancestor::div[@role='button']")
                        if parent:
                            await parent.click()
                        else:
                            await send_btn.click()
                    else:
                        await send_btn.click()
                    sent = True
                    await page.wait_for_timeout(1500)
                    break
        except Exception:
            continue
    
    # Fallback: Press Enter to send
    if not sent:
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(1500)
        sent = True
    
    if sent:
        return {"status": "success", "message": f"Message sent to @{username}, sir."}
    
    return {"status": "fail", "reason": "Could not send message, sir."}


async def _instagram_view_profile(page, username: str):
    """View a user's profile and get info."""
    await page.goto(f"{INSTAGRAM_URL}/{username}/", wait_until="domcontentloaded")
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)
    
    # Check if profile exists
    not_found = await page.query_selector("text=Sorry, this page isn't available")
    if not_found:
        return {"status": "fail", "reason": f"User @{username} not found"}
    
    # Extract profile info
    profile_info = {}
    
    # Get name
    name_elem = await page.query_selector('header section span')
    if name_elem:
        profile_info["name"] = await name_elem.inner_text()
    
    # Get stats (posts, followers, following)
    stats = await page.query_selector_all('header section ul li')
    for stat in stats:
        text = await stat.inner_text()
        if "posts" in text.lower():
            profile_info["posts"] = text.split()[0]
        elif "followers" in text.lower():
            profile_info["followers"] = text.split()[0]
        elif "following" in text.lower():
            profile_info["following"] = text.split()[0]
    
    # Get bio
    bio_elem = await page.query_selector('header section > div:not(:has(button))')
    if bio_elem:
        profile_info["bio"] = await bio_elem.inner_text()
    
    return {
        "status": "success",
        "message": f"Viewing @{username}'s profile, sir.",
        "profile": profile_info
    }


async def _instagram_save_post(page, post_url: str = None):
    """Save/bookmark a post."""
    if post_url:
        await page.goto(post_url, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(2500)
    
    # Find save button
    save_selectors = [
        'svg[aria-label="Save"]',
        '[aria-label="Save"]',
        'svg[aria-label="Remove"]',  # Already saved
        '[aria-label="Remove"]',
    ]
    
    for selector in save_selectors:
        save_btn = await page.query_selector(selector)
        if save_btn:
            # Check if already saved
            aria_label = await save_btn.get_attribute("aria-label")
            if aria_label and "Remove" in aria_label:
                return {"status": "success", "message": "Post already saved, sir."}
            
            try:
                parent = await save_btn.query_selector("xpath=ancestor::button | ancestor::div[@role='button']")
                if parent:
                    await parent.click()
                else:
                    await save_btn.click()
                await page.wait_for_timeout(1500)
                return {"status": "success", "message": "Post saved, sir."}
            except Exception as e:
                return {"status": "fail", "reason": f"Error saving post: {str(e)}"}
    
    return {"status": "fail", "reason": "Save button not found, sir. Make sure you're viewing a post."}


async def _instagram_view_story(page, username: str = None):
    """View a user's story."""
    if username:
        # Go to user profile first
        await page.goto(f"{INSTAGRAM_URL}/{username}/", wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(2500)
        
        # Click on profile picture to view story
        story_selectors = [
            'header img[alt*="profile"]',
            'header canvas',  # Story ring
            f'img[alt*="{username}" i]',
            'header section > div:first-child',
        ]
        
        for selector in story_selectors:
            story_elem = await page.query_selector(selector)
            if story_elem:
                try:
                    await story_elem.click()
                    await page.wait_for_timeout(3000)
                    return {"status": "success", "message": f"Viewing @{username}'s story, sir."}
                except Exception:
                    continue
        
        return {"status": "fail", "reason": f"No story available for @{username}, sir."}
    
    # If no username, go to home and click first story
    await page.goto(INSTAGRAM_URL, wait_until="domcontentloaded")
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    await page.wait_for_timeout(2500)
    
    # Click on first story in the stories bar
    story_button = await page.query_selector('button[aria-label*="Story"]')
    if not story_button:
        story_button = await page.query_selector('canvas')  # Story ring canvas
    
    if story_button:
        await story_button.click()
        await page.wait_for_timeout(3000)
        return {"status": "success", "message": "Viewing stories, sir."}
    
    return {"status": "fail", "reason": "No stories available, sir."}


async def _instagram_share_post(page, username: str, post_url: str = None):
    """Share a post to a user via DM."""
    if post_url:
        await page.goto(post_url, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(2500)
    
    # Find share button
    share_selectors = [
        'svg[aria-label="Share Post"]',
        'svg[aria-label="Share"]',
        '[aria-label="Share Post"]',
        '[aria-label="Share"]',
    ]
    
    share_btn = None
    for selector in share_selectors:
        share_btn = await page.query_selector(selector)
        if share_btn:
            break
    
    if not share_btn:
        return {"status": "fail", "reason": "Share button not found, sir."}
    
    try:
        parent = await share_btn.query_selector("xpath=ancestor::button | ancestor::div[@role='button']")
        if parent:
            await parent.click()
        else:
            await share_btn.click()
        await page.wait_for_timeout(2000)
    except Exception as e:
        return {"status": "fail", "reason": f"Error clicking share button: {str(e)}"}
    
    # Search for user to share with
    search_input = await page.query_selector('input[placeholder*="Search"]')
    if not search_input:
        search_input = await page.query_selector('input[type="text"]')
    
    if search_input:
        await search_input.type(username, delay=50)
        await page.wait_for_timeout(2000)
        
        # Select user from results
        user_option = await page.query_selector(f'[role="button"]:has-text("{username}")')
        if not user_option:
            user_option = await page.query_selector(f'div:has-text("{username}")')
        
        if user_option:
            await user_option.click()
            await page.wait_for_timeout(1000)
            
            # Click Send button
            send_btn = await page.query_selector('button:has-text("Send")')
            if send_btn:
                await send_btn.click()
                await page.wait_for_timeout(2000)
                return {"status": "success", "message": f"Post shared with @{username}, sir."}
    
    return {"status": "fail", "reason": f"Could not share post with @{username}, sir."}


async def _instagram_scroll_feed(page, count: int = 5):
    """Scroll through feed and collect post info."""
    posts = []
    
    for i in range(count):
        # Scroll down
        await page.evaluate("window.scrollBy(0, 800)")
        await page.wait_for_timeout(1500)
        
        # Get visible posts
        articles = await page.query_selector_all("article")
        for article in articles:
            post_info = {}
            
            # Get username
            username_elem = await article.query_selector('a[href*="/"]')
            if username_elem:
                href = await username_elem.get_attribute("href")
                if href:
                    post_info["username"] = href.replace("/", "")
            
            # Get like count if visible
            likes_elem = await article.query_selector('button:has-text("likes")')
            if likes_elem:
                post_info["likes"] = await likes_elem.inner_text()
            
            if post_info and post_info not in posts:
                posts.append(post_info)
    
    return {
        "status": "success",
        "message": f"Scrolled feed, found {len(posts)} posts",
        "posts": posts[:10]
    }


async def _instagram_get_notifications(page):
    """Get recent notifications."""
    await page.goto(f"{INSTAGRAM_URL}/notifications/", wait_until="domcontentloaded")
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)
    
    notifications = []
    notif_items = await page.query_selector_all('[role="listitem"]')
    
    for item in notif_items[:10]:
        text = await item.inner_text()
        if text:
            notifications.append(text.strip())
    
    return {
        "status": "success",
        "message": f"Found {len(notifications)} notifications",
        "notifications": notifications
    }


async def _instagram_logout(page):
    """Log out of Instagram."""
    await page.goto(f"{INSTAGRAM_URL}/accounts/logout/", wait_until="domcontentloaded")
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)
    
    # Clear saved session
    if COOKIES_FILE.exists():
        COOKIES_FILE.unlink()
    
    return {"status": "success", "message": "Logged out of Instagram"}


# ============== MAIN RUN FUNCTION ==============

def run(action: str = "open", **kwargs) -> dict:
    """
    Instagram automation tool.
    
    Actions:
        - open: Open Instagram in browser
        - login: Log into Instagram (requires username, password)
        - verify_2fa: Verify 2FA code (requires code)
        - logout: Log out of Instagram
        - navigate: Go to feed/explore/reels/messages/profile (requires destination)
        - search: Search for users/hashtags (requires query)
        - like: Like current post (optional: post_url)
        - unlike: Unlike current post (optional: post_url)
        - comment: Comment on post (requires text, optional: post_url)
        - follow: Follow a user (requires username)
        - unfollow: Unfollow a user (requires username)
        - dm/message: Send direct message (requires username, message)
        - profile: View user profile (requires username)
        - feed: Scroll through feed (optional: count)
        - notifications: Get notifications
        - save: Save/bookmark current post
        - story: View stories (optional: username for specific user)
        - share: Share current post to a user (requires username)
        - close: Close browser
    
    Examples:
        run(action="open")
        run(action="login", username="user", password="pass")
        run(action="like")
        run(action="follow", username="instagram")
        run(action="dm", username="friend", message="Hey!")
        run(action="save")
        run(action="story", username="virat.kohli")
    """
    action = (action or "open").strip().lower()

    user_text = kwargs.get("user_text") or kwargs.get("prompt") or kwargs.get("command") or kwargs.get("text")
    user_text = str(user_text) if user_text is not None else ""

    def _first_present(*keys):
        for k in keys:
            if k in kwargs and kwargs.get(k) not in (None, ""):
                return kwargs.get(k)
        return None

    def _parse_quoted(s: str):
        m = re.search(r'"([^"]+)"', s)
        if m:
            return m.group(1).strip()
        m = re.search(r"'([^']+)'", s)
        if m:
            return m.group(1).strip()
        return None

    def _parse_username(s: str):
        m = re.search(r"@([A-Za-z0-9._]+)", s)
        if m:
            return m.group(1)
        m = re.search(r"\buser\s+([A-Za-z0-9._]+)", s, re.IGNORECASE)
        if m:
            return m.group(1)
        m = re.search(r"\bto\s+([A-Za-z0-9._]+)\b", s, re.IGNORECASE)
        if m:
            return m.group(1)
        m = re.search(r"\b(dm|message)\s+([A-Za-z0-9._]+)\b", s, re.IGNORECASE)
        if m:
            return m.group(2)
        tokens = [t for t in re.split(r"\s+", s.strip()) if t]
        if tokens:
            last = tokens[-1]
            if re.fullmatch(r"[A-Za-z0-9._]+", last):
                return last
        return None

    def _parse_query(s: str):
        # Clean up common suffixes
        cleaned = re.sub(r"\s+on\s+(insta|instagram)\s*$", "", s, flags=re.IGNORECASE)
        
        # Pattern: "search for X"
        m = re.search(r"\bsearch\b(?:\s+instagram)?\s+for\s+(.+)$", cleaned, re.IGNORECASE)
        if m:
            return m.group(1).strip().strip("\"'")
        
        # Pattern: "search X" (extract everything after "search")
        m = re.search(r"\bsearch\b\s+(.+)$", cleaned, re.IGNORECASE)
        if m:
            query = m.group(1).strip().strip("\"'")
            # Remove action words that might be captured
            query = re.sub(r"\s+(on\s+)?instagram\s*$", "", query, flags=re.IGNORECASE)
            return query if query else None
        
        return None

    def _parse_destination(s: str):
        if re.search(r"\b(msg|message|messages|inbox|dm)\b", s, re.IGNORECASE):
            return "messages"
        if re.search(r"\bnotif|notifications\b", s, re.IGNORECASE):
            return "notifications"
        if re.search(r"\bexplore\b", s, re.IGNORECASE):
            return "explore"
        if re.search(r"\breels\b", s, re.IGNORECASE):
            return "reels"
        if re.search(r"\bhome\b", s, re.IGNORECASE):
            return "home"
        if re.search(r"\bfeed\b", s, re.IGNORECASE):
            return "feed"
        return None
    
    # Action aliases
    aliases = {
        "message": "dm",
        "send": "dm",
        "scroll": "feed",
        "bookmark": "save",
        "stories": "story",
        "watch": "story",
        "view_story": "story",
    }
    action = aliases.get(action, action)
    
    # Handle special navigate aliases
    if action in ("home", "explore", "reels") and "destination" not in kwargs:
        kwargs["destination"] = action
        action = "navigate"
    
    try:
        # Close browser action
        if action == "close":
            _sync_wrapper(_close_browser())
            return {"status": "success", "message": "Browser closed"}

        async def _dispatch():
            page = await _ensure_playwright_page()

            if action == "open":
                result = await _instagram_open(page)
                await _save_storage_state()
                return result

            if action == "navigate":
                destination = _first_present("destination", "dest") or _parse_destination(user_text) or "home"
                result = await _instagram_navigate(page, str(destination))
                await _save_storage_state()
                return result

            if action == "login":
                username = _first_present("username", "user")
                password = _first_present("password", "pass")
                result = await _instagram_login(page, username=username, password=password)
                await _save_storage_state()
                return result

            if action == "verify_2fa":
                code = kwargs.get("code")
                if not code:
                    return {"status": "fail", "reason": "Code required"}
                result = await _instagram_verify_2fa(page, code=str(code))
                await _save_storage_state()
                return result

            if action == "logout":
                result = await _instagram_logout(page)
                await _save_storage_state()
                return result

            if action == "search":
                query = _first_present("query", "q") or _parse_query(user_text)
                if not query:
                    return {"status": "fail", "reason": "Search query required, sir. Please specify what to search for."}
                search_type = kwargs.get("search_type", "all")
                result = await _instagram_search(page, query=str(query), search_type=str(search_type))
                await _save_storage_state()
                return result

            if action == "like":
                post_url = kwargs.get("post_url")
                result = await _instagram_like(page, post_url=post_url)
                await _save_storage_state()
                return result

            if action == "unlike":
                post_url = kwargs.get("post_url")
                result = await _instagram_unlike(page, post_url=post_url)
                await _save_storage_state()
                return result

            if action == "comment":
                text = _first_present("text", "comment") or _parse_quoted(user_text)
                
                # Enhanced comment text extraction
                if not text and user_text:
                    # Clean up common suffixes
                    cleaned = re.sub(r"\s+(on\s+)?(insta|instagram)\s*$", "", user_text, flags=re.IGNORECASE)
                    
                    # Pattern: "comment <text>" or "add comment <text>"
                    m = re.search(r"\b(?:comment|add\s+comment)\s+(.+)$", cleaned, re.IGNORECASE)
                    if m:
                        text = m.group(1).strip().strip("\"'")
                        # Additional cleanup
                        text = re.sub(r"\s*(on\s+)?(insta|instagram)\s*$", "", text, flags=re.IGNORECASE).strip()
                
                if not text:
                    return {"status": "fail", "reason": "Comment text required, sir."}
                post_url = kwargs.get("post_url")
                result = await _instagram_comment(page, text=str(text), post_url=post_url)
                await _save_storage_state()
                return result

            if action == "follow":
                username = _first_present("username", "user", "handle") or _parse_username(user_text)
                if not username:
                    return {"status": "fail", "reason": "Username required"}
                result = await _instagram_follow(page, username=str(username))
                await _save_storage_state()
                return result

            if action == "unfollow":
                username = _first_present("username", "user", "handle") or _parse_username(user_text)
                if not username:
                    return {"status": "fail", "reason": "Username required"}
                result = await _instagram_unfollow(page, username=str(username))
                await _save_storage_state()
                return result

            if action == "dm":
                username = _first_present("username", "user", "to") or _parse_username(user_text)
                message = _first_present("message", "msg") or _parse_quoted(user_text)
                
                # Enhanced message extraction for patterns like "dm arjun hi on insta"
                if not message and user_text:
                    # Clean up common suffixes from the full text first
                    cleaned = re.sub(r"\s+(on\s+)?(insta|instagram)\s*$", "", user_text, flags=re.IGNORECASE)
                    
                    # Pattern: "dm/message <username> <message>"
                    m = re.search(r"\b(?:dm|message|send)\s+([A-Za-z0-9._]+)\s+(.+)$", cleaned, re.IGNORECASE)
                    if m:
                        if not username:
                            username = m.group(1)
                        message = m.group(2).strip().strip("\"'")
                        # Additional cleanup for any remaining "insta" words
                        message = re.sub(r"\s*(on\s+)?(insta|instagram)\s*$", "", message, flags=re.IGNORECASE).strip()
                    else:
                        # Fallback: try "message <content>" pattern
                        m = re.search(r"\bmessage\b\s+(.+)$", cleaned, re.IGNORECASE)
                        if m:
                            message = m.group(1).strip().strip("\"'")
                            message = re.sub(r"\s*(on\s+)?(insta|instagram)\s*$", "", message, flags=re.IGNORECASE).strip()
                
                # Final cleanup if message still contains stray "insta"
                if message:
                    message = re.sub(r"\s*(on\s+)?(insta|instagram)\s*$", "", message, flags=re.IGNORECASE).strip()
                
                if not username or not message:
                    return {"status": "fail", "reason": "Username and message required, sir."}
                result = await _instagram_dm(page, username=str(username), message=str(message))
                await _save_storage_state()
                return result

            if action == "profile":
                username = _first_present("username", "user", "handle") or _parse_username(user_text)
                if not username:
                    return {"status": "fail", "reason": "Username required"}
                result = await _instagram_view_profile(page, username=str(username))
                await _save_storage_state()
                return result

            if action == "feed":
                count = kwargs.get("count", 5)
                try:
                    count_int = int(count)
                except Exception:
                    count_int = 5
                result = await _instagram_scroll_feed(page, count=count_int)
                await _save_storage_state()
                return result

            if action == "notifications":
                result = await _instagram_get_notifications(page)
                await _save_storage_state()
                return result

            if action == "save":
                post_url = kwargs.get("post_url")
                result = await _instagram_save_post(page, post_url=post_url)
                await _save_storage_state()
                return result

            if action == "story":
                username = _first_present("username", "user") or _parse_username(user_text)
                result = await _instagram_view_story(page, username=username)
                await _save_storage_state()
                return result

            if action == "share":
                username = _first_present("username", "user", "to") or _parse_username(user_text)
                if not username:
                    return {"status": "fail", "reason": "Username required to share post, sir."}
                post_url = kwargs.get("post_url")
                result = await _instagram_share_post(page, username=str(username), post_url=post_url)
                await _save_storage_state()
                return result

            return {"status": "fail", "reason": f"Unknown action: {action}"}

        result = _sync_wrapper(_dispatch())
        
        # Track action in memory
        tracked_entities = {}
        if "username" in kwargs:
            tracked_entities["username"] = kwargs["username"]
        if "query" in kwargs:
            tracked_entities["query"] = kwargs["query"]
        if "destination" in kwargs:
            tracked_entities["destination"] = kwargs["destination"]
        
        if result.get("status") == "success":
            _track_action(action, entities=tracked_entities, result=result)
        
        return result
        
    except Exception as e:
        return {"status": "fail", "reason": f"Instagram error: {str(e)}"}

