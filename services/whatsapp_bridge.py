"""
WhatsApp AI Bridge — Ghost Browser Engine for A.N.K.I.T.A.

Watches WhatsApp Web via a persistent Playwright Chromium session.
When an unread message arrives from a VIP contact, it passes the message
to the CommsAgent and types the AI reply back like a human.

First run: a headed browser window opens — scan the QR code with your phone.
Every run after that: the session is remembered, no QR needed.

Usage:
    python whatsapp_runner.py
    # or import and call WhatsAppBridge directly
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _parse_vip_friends(raw: str) -> Set[str]:
    """Parse comma-separated VIP contact names into a set (stripped, lowercased for matching)."""
    return {name.strip().lower() for name in (raw or "").split(",") if name.strip()}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# ARIA / XPath selectors — class-name-free, accessibility-label based
# These are stable across WhatsApp DOM updates.
# ---------------------------------------------------------------------------

# Unread message badge indicator
SEL_UNREAD_BADGE = '[aria-label="Unread messages"]'

# The left-side chat list container
SEL_CHAT_LIST = '[aria-label="Chat list"]'

# The pane containing unread chats (fallback)
SEL_UNREAD_CHAT_ITEM = '[aria-label="Unread messages"] >> xpath=ancestor::div[@role="listitem"]'

# Message input box
SEL_INPUT_BOX = '[title="Type a message"], [aria-label="Type a message"]'

# Conversation header (contact name lives in the title attribute of a span here)
SEL_CONV_HEADER = 'header [title]'

# Incoming message bubbles (aria role="row" in the message list)
SEL_MSG_CONTAINER = '[data-testid="msg-container"]'

# Fallback: last span with the actual message text inside an incoming message
SEL_MSG_TEXT_FALLBACK = 'div[class*="message-in"] span[class*="selectable-text"]'


# ---------------------------------------------------------------------------
# Core bridge class
# ---------------------------------------------------------------------------

class WhatsAppBridge:
    """
    Persistent Playwright-based WhatsApp Web bridge.

    Launches a Chromium browser with a persistent profile so the WhatsApp
    Web session survives restarts (QR code scanned only once).

    The watch loop runs in a background daemon thread. Call start() to begin
    and stop() to shut down gracefully.
    """

    def __init__(
        self,
        agent_runtime: Any,
        workspace_root: Optional[Path] = None,
        vip_friends: Optional[Set[str]] = None,
        session_dir: Optional[str] = None,
        poll_interval: float = 5.0,
        typing_delay: int = 80,
        headless: bool = False,
        use_chrome: bool = False,
        chrome_profile: str = "Default",
    ) -> None:
        """
        Args:
            agent_runtime:  An AgentRuntime instance used to generate WhatsApp replies.
            workspace_root: ANKITA workspace root (for session dir resolution).
            vip_friends:    Set of lowercased contact names to respond to.
                            If empty, responds to ALL contacts (not recommended).
            session_dir:    Path to Playwright persistent profile directory.
            poll_interval:  Seconds between unread-badge checks.
            typing_delay:   Milliseconds between keystrokes (human simulation).
            headless:       Run browser in headless mode (False = visible window).
            use_chrome:     If True, hijack the real Chrome installation instead of
                            Playwright's bundled Chromium. Uses the existing Chrome
                            session so WhatsApp Web is already logged in.
                            WARNING: Close all Chrome windows before enabling this.
            chrome_profile: Chrome profile to use (default: "Default").
        """
        self.agent_runtime = agent_runtime
        self.workspace_root = workspace_root or Path.cwd()
        self.vip_friends: Set[str] = vip_friends or set()
        self.session_dir = Path(session_dir or (self.workspace_root / "whatsapp_session")).resolve()
        self.poll_interval = poll_interval
        self.typing_delay = typing_delay
        self.headless = headless
        self.use_chrome = use_chrome
        self.chrome_profile = chrome_profile

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._playwright = None
        self._browser = None
        self._page = None

        # Track last replied message per chat to avoid duplicate replies
        # key: contact_name_lower, value: last message text we replied to
        self._last_replied: Dict[str, str] = {}

        # Conversation history per contact for multi-turn context
        self._histories: Dict[str, List[Dict[str, str]]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch the Playwright browser and start the watch loop in background."""
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="WhatsAppBridge",
        )
        self._thread.start()
        print(f"[WhatsApp] Bridge started. Session: {self.session_dir}")
        if not self.headless:
            print("[WhatsApp] Browser window will open. Scan QR code with your phone (first run only).")

    def stop(self) -> None:
        """Signal the watch loop to stop and wait for it to finish."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=15)
        self._cleanup()
        print("[WhatsApp] Bridge stopped.")

    def join(self) -> None:
        """Block until stop() is called (use in __main__ to keep process alive)."""
        try:
            while not self._stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    # ------------------------------------------------------------------
    # Internal — browser lifecycle
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Main loop: launch browser, wait for WhatsApp to load, poll for messages."""
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        except ImportError:
            print("[WhatsApp] ERROR: playwright not installed.")
            print("  Run: pip install playwright && playwright install chromium")
            return

        with sync_playwright() as pw:
            self._playwright = pw

            if self.use_chrome:
                # Chrome hijack mode — copy the Chrome profile into a temp Playwright
                # profile dir so Playwright has full control without fighting Chrome's
                # own process lock. This is the most reliable approach.
                import platform, shutil
                if platform.system() == "Windows":
                    chrome_user_data = Path(os.path.expandvars(
                        r"%LOCALAPPDATA%\Google\Chrome\User Data"
                    ))
                elif platform.system() == "Darwin":
                    chrome_user_data = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
                else:
                    chrome_user_data = Path.home() / ".config" / "google-chrome"

                src_profile = chrome_user_data / self.chrome_profile
                pw_profile_dir = self.session_dir / f"pw_chrome_{self.chrome_profile}"

                print(f"[WhatsApp] Chrome profile source: {src_profile}")
                print(f"[WhatsApp] Copying profile to Playwright session dir (first time may take 30s)...")

                if not pw_profile_dir.exists():
                    pw_profile_dir.mkdir(parents=True, exist_ok=True)
                    # Copy only essential subdirs (cookies, local storage, cache is skipped)
                    for subdir in ["Cookies", "Local Storage", "Session Storage",
                                   "IndexedDB", "Local Extension Settings"]:
                        src = src_profile / subdir
                        dst = pw_profile_dir / subdir
                        if src.exists():
                            try:
                                shutil.copytree(str(src), str(dst))
                                print(f"[WhatsApp]   Copied: {subdir}")
                            except Exception as copy_err:
                                print(f"[WhatsApp]   Skipped {subdir}: {copy_err}")
                    print("[WhatsApp] Profile copy complete.")
                else:
                    print("[WhatsApp] Using existing copied profile.")

                self._browser = pw.chromium.launch_persistent_context(
                    user_data_dir=str(pw_profile_dir),
                    channel="chrome",
                    headless=self.headless,
                    args=["--no-first-run", "--no-default-browser-check",
                          "--disable-extensions-except=", "--no-sandbox"],
                    viewport={"width": 1280, "height": 800},
                )
            else:
                print("[WhatsApp] Launching Playwright Chromium with persistent session...")
                self._browser = pw.chromium.launch_persistent_context(
                    user_data_dir=str(self.session_dir),
                    headless=self.headless,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                    viewport={"width": 1280, "height": 800},
                )

            # ------------------------------------------------------------------
            # Grab the steering wheel — always open a fresh tab and navigate
            # ------------------------------------------------------------------
            print("[WhatsApp] Context launched. Opening WhatsApp Web...")
            time.sleep(1.5)

            # Open a fresh page — avoids restored tabs from previous sessions
            self._page = self._browser.new_page()

            # Navigate with retries
            for attempt in range(1, 4):
                try:
                    print(f"[WhatsApp] Navigation attempt {attempt}/3...")
                    self._page.goto(
                        "https://web.whatsapp.com",
                        wait_until="domcontentloaded",
                        timeout=45_000,
                    )
                    print(f"[WhatsApp] ✅ Navigated! URL: {self._page.url}")
                    break
                except Exception as nav_err:
                    print(f"[WhatsApp] Attempt {attempt} failed: {nav_err}")
                    if attempt < 3:
                        time.sleep(3)
                    else:
                        print("[WhatsApp] ❌ All navigation attempts failed.")

            # Wait for WhatsApp chat list (= fully logged in)
            print("[WhatsApp] Waiting for chat list (up to 120s)...")
            try:
                self._page.wait_for_selector(SEL_CHAT_LIST, timeout=120_000)
                print("[WhatsApp] ✅ WhatsApp loaded! Chats are visible.")
            except PWTimeout:
                print("[WhatsApp] ⚠️  Chat list not found within 120s.")
                print(f"[WhatsApp]    Current URL: {self._page.url}")
                print("[WhatsApp]    If you see a QR code — scan it with your phone.")
                print("[WhatsApp]    Continuing poll loop anyway...")

            # Start the poll loop
            while not self._stop_event.is_set():
                try:
                    self._tick()
                except Exception as err:
                    print(f"[WhatsApp] Tick error: {err}")
                self._stop_event.wait(timeout=self.poll_interval)

            self._cleanup()

    def _cleanup(self) -> None:
        try:
            if self._browser:
                self._browser.close()
                self._browser = None
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal — watch logic
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        """One poll cycle: find unread chats and process them."""
        page = self._page
        if page is None:
            return

        # Find all unread badge elements
        unread_badges = page.query_selector_all(SEL_UNREAD_BADGE)
        if not unread_badges:
            return  # Nothing to process

        for badge in unread_badges:
            try:
                self._process_badge(badge)
            except Exception as err:
                print(f"[WhatsApp] Error processing badge: {err}")

    def _process_badge(self, badge: Any) -> None:
        """Click the chat associated with an unread badge and process the message."""
        from playwright.sync_api import TimeoutError as PWTimeout

        page = self._page

        # Find the parent list item (the chat row) and click it
        chat_row = badge.evaluate_handle(
            "el => el.closest('[role=\"listitem\"]') || el.closest('div[tabindex]')"
        )
        if not chat_row:
            badge.click()
        else:
            chat_row.click()

        time.sleep(1.0)  # Wait for chat to open

        # Read contact name from conversation header
        contact_name = self._get_contact_name()
        if not contact_name:
            return

        contact_lower = contact_name.lower()

        # VIP guard — skip if not in VIP list (and VIP list is not empty)
        if self.vip_friends and contact_lower not in self.vip_friends:
            print(f"[WhatsApp] Skipping non-VIP: {contact_name}")
            # Click away back to the chat list
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            return

        # Scrape the last incoming message
        last_msg = self._get_last_incoming_message()
        if not last_msg:
            print(f"[WhatsApp] No readable message from {contact_name}")
            return

        # Deduplicate — don't reply to the same message twice
        if self._last_replied.get(contact_lower) == last_msg:
            return

        print(f"[WhatsApp] 💬 {contact_name}: {last_msg[:80]}")

        # Generate AI reply
        reply = self._generate_reply(contact_name, last_msg)
        if not reply:
            print(f"[WhatsApp] CommsAgent returned empty reply for {contact_name}")
            return

        print(f"[WhatsApp] 🤖 Reply to {contact_name}: {reply[:80]}")

        # Type and send the reply
        self._send_message(reply)

        # Mark as replied
        self._last_replied[contact_lower] = last_msg

    def _get_contact_name(self) -> Optional[str]:
        """Extract the contact name from the conversation header."""
        page = self._page
        try:
            header_el = page.query_selector(SEL_CONV_HEADER)
            if header_el:
                name = header_el.get_attribute("title") or header_el.inner_text()
                return name.strip() if name else None
        except Exception:
            pass
        # Fallback: try data-testid
        try:
            header_el = page.query_selector('[data-testid="conversation-header"] span[title]')
            if header_el:
                name = header_el.get_attribute("title") or header_el.inner_text()
                return name.strip() if name else None
        except Exception:
            pass
        return None

    def _get_last_incoming_message(self) -> Optional[str]:
        """Scrape the text of the last incoming message bubble."""
        page = self._page
        try:
            # Try data-testid approach first
            containers = page.query_selector_all(SEL_MSG_CONTAINER)
            if containers:
                # Walk backwards to find the last incoming message
                for container in reversed(containers):
                    try:
                        # Incoming messages don't have data-testid="msg-meta" with "sent" class
                        text_el = container.query_selector(
                            'span.selectable-text, span[class*="selectable-text"]'
                        )
                        if text_el:
                            text = text_el.inner_text().strip()
                            if text:
                                return text
                    except Exception:
                        continue
        except Exception:
            pass

        # Fallback: grab last message-in span
        try:
            msg_spans = page.query_selector_all(SEL_MSG_TEXT_FALLBACK)
            if msg_spans:
                text = msg_spans[-1].inner_text().strip()
                return text if text else None
        except Exception:
            pass

        return None

    def _generate_reply(self, contact_name: str, message: str) -> Optional[str]:
        """Pass the message to the CommsAgent and return the reply."""
        contact_lower = contact_name.lower()

        # Build conversation history for multi-turn context
        if contact_lower not in self._histories:
            self._histories[contact_lower] = []

        history = self._histories[contact_lower]
        history.append({"role": "user", "content": f"[{contact_name}]: {message}"})

        # Keep history bounded (last 10 turns)
        if len(history) > 10:
            history = history[-10:]
            self._histories[contact_lower] = history

        try:
            from agent_runtime import new_session  # type: ignore
            from agents.specialists import CommsAgent  # type: ignore

            # Start with the CommsAgent system prompt (WhatsApp persona)
            # instead of the default ANKITA general-purpose system prompt
            msgs = [{"role": "system", "content": CommsAgent.system_prompt}]
            # Inject conversation history for multi-turn context
            for turn in history:
                msgs.append(turn)

            reply = self.agent_runtime.process_user_text(
                user_text=message,
                messages=msgs,
            )
            reply = (reply or "").strip()

            # Clean up any markdown that slipped through
            reply = re.sub(r"\*+", "", reply)
            reply = re.sub(r"#+\s*", "", reply)
            reply = reply.strip()

            if reply:
                history.append({"role": "assistant", "content": reply})
                self._histories[contact_lower] = history[-10:]

            return reply if reply else None
        except Exception as err:
            print(f"[WhatsApp] CommsAgent error: {err}")
            return None

    def _send_message(self, text: str) -> None:
        """Type and send a message in the currently open WhatsApp chat."""
        from playwright.sync_api import TimeoutError as PWTimeout
        page = self._page

        try:
            # Click the input box
            input_box = page.wait_for_selector(SEL_INPUT_BOX, timeout=5_000)
            input_box.click()
            time.sleep(0.3)

            # Type keystroke-by-keystroke with delay (human simulation)
            input_box.type(text, delay=self.typing_delay)
            time.sleep(0.4)

            # Press Enter to send
            page.keyboard.press("Enter")
            time.sleep(0.5)
            print("[WhatsApp] ✅ Message sent.")
        except PWTimeout:
            print("[WhatsApp] ❌ Could not find message input box.")
        except Exception as err:
            print(f"[WhatsApp] ❌ Send error: {err}")
