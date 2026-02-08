"""
WhatsApp Automation Tool - Real automation for WhatsApp Web using Playwright.

Capabilities:
- Open WhatsApp Web (persistent session)
- Send messages to contacts
- Check for unread chats/notifications (best-effort)

Notes:
- First run requires QR scan on https://web.whatsapp.com
- Stores Playwright user data under ankita/data/whatsapp/
- Designed to be safe: does not auto-read message bodies unless requested.
"""

import os
import time
from pathlib import Path

WHATSAPP_URL = "https://web.whatsapp.com"
DATA_DIR = Path(__file__).parent.parent.parent / "data" / "whatsapp"
PROFILE_DIR = DATA_DIR / "pw_profile"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

# Lazy singletons
_playwright = None
_browser_ctx = None
_page = None


def _get_memory():
    try:
        from memory.conversation_memory import get_conversation_memory
        return get_conversation_memory()
    except Exception:
        return None


def _track_action(action: str, entities: dict | None = None, result: dict | None = None):
    mem = _get_memory()
    if mem:
        summary = f"WhatsApp: {action}"
        if entities and entities.get("contact"):
            summary += f" -> {entities.get('contact')}"
        mem.add_context(
            summary=summary,
            action=f"whatsapp.{action}",
            entities=entities or {},
            result=result or {},
            topic="social",
        )


def _ensure_page(headless: bool = False):
    """Start Playwright persistent context and return a Page."""
    global _playwright, _browser_ctx, _page

    if _page is not None:
        return _page

    from playwright.sync_api import sync_playwright

    _playwright = sync_playwright().start()

    # Persistent profile keeps WhatsApp logged in
    _browser_ctx = _playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
        ],
        viewport=None,
    )

    pages = _browser_ctx.pages
    _page = pages[0] if pages else _browser_ctx.new_page()
    return _page


def _goto_whatsapp(page, timeout_ms: int = 60000):
    page.goto(WHATSAPP_URL, wait_until="domcontentloaded", timeout=timeout_ms)


def _is_logged_in(page) -> bool:
    """Best-effort: if chat list / search exists."""
    try:
        # search box (varies). Try a few candidates.
        page.wait_for_selector("div[contenteditable='true'][data-tab]", timeout=5000)
        return True
    except Exception:
        return False


def open_whatsapp(headless: bool = False) -> dict:
    page = _ensure_page(headless=headless)
    _goto_whatsapp(page)

    if _is_logged_in(page):
        _track_action("open", {}, {"logged_in": True})
        return {"status": "success", "message": "WhatsApp Web opened (logged in)."}

    # Not logged in yet
    _track_action("open", {}, {"logged_in": False})
    return {
        "status": "success",
        "message": "WhatsApp Web opened. Please scan the QR code on screen to log in, then retry your command.",
    }


def _open_chat_by_contact(page, contact: str, timeout_ms: int = 45000) -> None:
    contact = (contact or "").strip()
    if not contact:
        raise ValueError("contact is required")

    # Click search box (WhatsApp changes DOM often; we use robust heuristics)
    # 1) Press Ctrl+F won't work; use UI search.
    # Try to focus the search field by clicking the left pane.
    # Candidate: the Search input is often the first contenteditable in sidebar.
    candidates = [
        "div[role='textbox'][contenteditable='true']",
        "div[contenteditable='true'][data-tab]",
    ]

    search = None
    for sel in candidates:
        try:
            el = page.locator(sel).first
            el.wait_for(timeout=5000)
            search = el
            break
        except Exception:
            continue

    if search is None:
        raise RuntimeError("Could not find WhatsApp search box (UI changed or not logged in)")

    # Clear and type contact
    search.click()
    # best-effort clear
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    search.type(contact, delay=20)

    # Click first matching chat result
    # Chat items typically have role=gridcell or span title.
    # We'll try a few selectors.
    clicked = False
    chat_selectors = [
        f"span[title='{contact}']",
        "div[role='grid'] div[role='row']",
        "div[aria-label='Search results'] div[role='row']",
    ]

    for sel in chat_selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(timeout=timeout_ms)
            loc.click()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        # As a fallback, hit Enter to open top result
        page.keyboard.press("Enter")


def send_message(contact: str, message: str, headless: bool = False) -> dict:
    page = _ensure_page(headless=headless)
    _goto_whatsapp(page)

    if not _is_logged_in(page):
        return {
            "status": "fail",
            "reason": "WhatsApp not logged in. Run whatsapp.open and scan QR first.",
        }

    _open_chat_by_contact(page, contact)

    # Message box selector: last contenteditable in main pane often.
    # Use heuristic: footer textbox.
    box = None
    for sel in [
        "footer div[contenteditable='true'][role='textbox']",
        "div[contenteditable='true'][role='textbox'][data-tab]",
    ]:
        try:
            loc = page.locator(sel).last
            loc.wait_for(timeout=15000)
            box = loc
            break
        except Exception:
            continue

    if box is None:
        return {"status": "fail", "reason": "Could not find message box (UI changed)."}

    box.click()
    box.type(message, delay=10)
    page.keyboard.press("Enter")

    _track_action("send", {"contact": contact, "message": message}, {"sent": True})
    return {"status": "success", "message": f"Sent WhatsApp message to {contact}."}


def check_notifications(headless: bool = False) -> dict:
    """Best-effort unread scan: returns list of chat titles that show an unread badge."""
    page = _ensure_page(headless=headless)
    _goto_whatsapp(page)

    if not _is_logged_in(page):
        return {"status": "fail", "reason": "WhatsApp not logged in. Run whatsapp.open and scan QR first."}

    unread = []
    try:
        # Unread badges often appear as span with aria-label containing 'unread'
        badges = page.locator("span[aria-label*='unread'], span[aria-label*='Unread']")
        n = min(badges.count(), 20)
        for i in range(n):
            try:
                # Walk up to the chat row and grab title
                row = badges.nth(i).locator("xpath=ancestor::div[@role='row'][1]")
                title = row.locator("span[title]").first.get_attribute("title")
                if title:
                    unread.append(title)
            except Exception:
                continue
    except Exception:
        pass

    _track_action("notifications", {}, {"unread": unread})
    return {"status": "success", "message": f"Found {len(unread)} unread chats.", "unread": unread}


def check_incoming_call(page) -> str | None:
    """Check for an incoming call UI element and return caller name."""
    try:
        # Incoming call modal usually has specific text or aria-labels
        # Heuristic: Find text like 'Incoming call' or 'Accept'
        accept_button = page.locator("div[aria-label='Accept'], span:text('Accept')").first
        if accept_button.is_visible(timeout=500):
            # Try to grab caller name
            caller_name = "Someone"
            try:
                # Often the caller name is in a large header in the modal
                header = page.locator("div[role='dialog'] span").first
                if header.is_visible():
                    caller_name = header.get_text()
            except:
                pass
            return caller_name
    except:
        pass
    return None

def answer_call(headless: bool = False) -> dict:
    """Attempt to answer an incoming WhatsApp call and start engagement."""
    page = _ensure_page(headless=headless)
    try:
        accept_button = page.locator("div[aria-label='Accept'], span:text('Accept')").first
        if accept_button.is_visible(timeout=2000):
            accept_button.click()
            _track_action("answer_call", {}, {"status": "success"})
            
            # Start engagement speech
            time.sleep(2)
            try:
                from ankita_core import speak_with_bargein
                speak_with_bargein("Hello! I am ANKITA, Krish's AI assistant. Krish is currently unavailable, so I am handling this call. How can I help you?")
            except:
                pass
                
            return {"status": "success", "message": "Call answered. ANKITA is engaging with the caller."}
    except Exception as e:
        return {"status": "fail", "reason": f"Could not answer call: {e}"}
    return {"status": "fail", "reason": "No incoming call detected."}

def run(**kwargs) -> dict:
    action = (kwargs.get("action") or "open").strip().lower()
    headless = bool(kwargs.get("headless", False))

    if action == "open":
        return open_whatsapp(headless=headless)

    if action == "send":
        contact = kwargs.get("contact") or kwargs.get("recipient")
        message = kwargs.get("message")
        if not contact or not message:
            return {"status": "fail", "reason": "contact and message required"}
        return send_message(contact=str(contact), message=str(message), headless=headless)

    if action in ("notifications", "inbox", "unread"):
        return check_notifications(headless=headless)

    if action == "answer":
        return answer_call(headless=headless)

    return {"status": "fail", "reason": f"Unknown action: {action}"}
