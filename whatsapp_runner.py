"""
WhatsApp AI Bridge — Entry Point for A.N.K.I.T.A.

How to run:
    python whatsapp_runner.py

First run:
    A headed Chromium browser opens → scan the QR code with your phone.
    WhatsApp Web stays logged in permanently after that.

Every run after:
    The browser opens silently (or headlessly if WHATSAPP_HEADLESS=true),
    finds unread messages from your VIP contacts, and replies automatically.

Required .env variables:
    LLM_PROVIDER=copilot          (recommended — GPT-4o quality)
    COPILOT_GITHUB_TOKEN=...
    VIP_FRIENDS=Rahul,Aryan,Priya  (exact names as saved in your phone)

Optional:
    WHATSAPP_SESSION_DIR=./whatsapp_session
    WHATSAPP_POLL_INTERVAL=5
    WHATSAPP_TYPING_DELAY=80
    WHATSAPP_HEADLESS=false
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ------------------------------------------------------------------
# Check for playwright before anything else — give a clear error
# ------------------------------------------------------------------
try:
    import playwright  # noqa: F401
except ImportError:
    raise SystemExit(
        "\n[WhatsApp] playwright is not installed.\n"
        "Run: pip install playwright && playwright install chromium\n"
    )

from agent_runtime import AgentRuntime  # noqa: E402
from agents.specialists import CommsAgent  # noqa: E402
from llm import build_runtime_from_env  # noqa: E402
from services.whatsapp_bridge import WhatsAppBridge, _parse_vip_friends, _env_bool  # noqa: E402

WORKSPACE_ROOT = Path.cwd().resolve()


def main() -> None:
    # ------------------------------------------------------------------
    # Build LLM runtime — strongly recommend Copilot (GPT-4o) for WhatsApp
    # ------------------------------------------------------------------
    runtime = build_runtime_from_env()
    print(f"[WhatsApp] LLM provider: {runtime.provider} / {runtime.model}")

    # ------------------------------------------------------------------
    # Build AgentRuntime — CommsAgent system prompt injected per-session
    # inside WhatsAppBridge._generate_reply() via the messages list.
    # ------------------------------------------------------------------
    agent = AgentRuntime(runtime=runtime, workspace_root=WORKSPACE_ROOT)

    # ------------------------------------------------------------------
    # Load config from .env
    # ------------------------------------------------------------------
    vip_raw = os.getenv("VIP_FRIENDS", "").strip()
    vip_friends = _parse_vip_friends(vip_raw)

    if not vip_friends:
        print("[WhatsApp] ⚠️  WARNING: VIP_FRIENDS is not set in .env.")
        print("           ANKITA will respond to ALL contacts — set VIP_FRIENDS to limit this.")
    else:
        print(f"[WhatsApp] VIP contacts: {', '.join(sorted(vip_friends))}")

    session_dir = os.getenv("WHATSAPP_SESSION_DIR", str(WORKSPACE_ROOT / "whatsapp_session"))
    poll_interval = float(os.getenv("WHATSAPP_POLL_INTERVAL", "5"))
    typing_delay = int(os.getenv("WHATSAPP_TYPING_DELAY", "80"))
    headless = _env_bool("WHATSAPP_HEADLESS", False)
    use_chrome = _env_bool("WHATSAPP_USE_CHROME", False)
    chrome_profile = os.getenv("WHATSAPP_CHROME_PROFILE", "Default").strip()

    if use_chrome:
        print("[WhatsApp] ⚠️  Chrome hijack mode enabled.")
        print("[WhatsApp] ⚠️  CLOSE ALL CHROME WINDOWS NOW before continuing!")
        input("[WhatsApp] Press ENTER when all Chrome windows are closed...")

    # ------------------------------------------------------------------
    # Start the bridge
    # ------------------------------------------------------------------
    bridge = WhatsAppBridge(
        agent_runtime=agent,
        workspace_root=WORKSPACE_ROOT,
        vip_friends=vip_friends,
        session_dir=session_dir,
        poll_interval=poll_interval,
        typing_delay=typing_delay,
        headless=headless,
        use_chrome=use_chrome,
        chrome_profile=chrome_profile,
    )

    print()
    print("╔══════════════════════════════════════════╗")
    print("║   A.N.K.I.T.A WhatsApp Bridge  ACTIVE   ║")
    print("╚══════════════════════════════════════════╝")
    print(f"  VIP contacts : {', '.join(sorted(vip_friends)) or 'ALL (no filter)'}")
    print(f"  Poll interval: {poll_interval}s")
    print(f"  Typing delay : {typing_delay}ms/key")
    print(f"  Session dir  : {session_dir}")
    print(f"  Headless     : {headless}")
    print(f"  Chrome mode  : {'ON (real Chrome)' if use_chrome else 'OFF (Playwright Chromium)'}")
    if use_chrome:
        print(f"  Chrome profile: {chrome_profile}")
    print()
    print("Press Ctrl+C to stop.\n")

    bridge.start()
    bridge.join()  # Blocks until Ctrl+C


if __name__ == "__main__":
    main()
