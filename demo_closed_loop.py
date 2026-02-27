"""
A.N.K.I.T.A — Closed-Loop Vision Demo
=======================================
Proves the full See → Think → Click → Verify pipeline end-to-end.

Usage:
    python demo_closed_loop.py "click the Kernel chat"
    python demo_closed_loop.py                          # interactive prompt

What it does:
    1. BEFORE  — Captures screen, asks GPT-4o to describe what's on screen
    2. CLICK   — Calls visual_click(target, verify=True)
                  • Finds the element via GPT-4o vision
                  • Physically moves mouse + clicks (pyautogui)
                  • Re-captures screen 0.8s after click (the verification shot)
    3. AFTER   — Asks GPT-4o "What changed?" comparing the after-screenshot
    4. REPORT  — Prints a clean summary table

Requirements (already in requirements.txt):
    pip install mss pyautogui pillow python-dotenv

Run from the A.N.K.I.T.A project root:
    cd "3D Objects/A.N.K.I.T.A"
    python demo_closed_loop.py "click the Start button"
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: add project root to path so local imports work
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except ImportError:
    pass  # dotenv is optional for this demo

from llm import build_runtime_from_env
from llm.client import call_chat_with_image
from tools.desktop_ops import capture_screen, visual_click


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _header(title: str) -> None:
    width = 60
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def _describe_screen(runtime, b64: str, prompt: str) -> str:
    """Ask GPT-4o to describe a screenshot."""
    try:
        return call_chat_with_image(runtime, prompt, b64, max_tokens=400)
    except Exception as err:
        return f"[Vision error: {err}]"


# ---------------------------------------------------------------------------
# Main closed-loop demo
# ---------------------------------------------------------------------------

def run_demo(target: str) -> None:
    _header("A.N.K.I.T.A — Closed-Loop Vision Demo")
    print(f"  Target: \"{target}\"")
    print(f"  Runtime: building from .env ...")

    try:
        runtime = build_runtime_from_env()
        print(f"  Provider: {runtime.provider} | Model: {runtime.model}")
    except SystemExit as exc:
        print(f"\n[ERROR] Could not build LLM runtime. Check .env (COPILOT_GITHUB_TOKEN / GROQ_API_KEY).")
        sys.exit(exc.code or 1)

    # ------------------------------------------------------------------
    # STEP 1 — BEFORE: capture and describe the current screen
    # ------------------------------------------------------------------
    _header("Step 1 — BEFORE (Capturing screen)")
    before = capture_screen(monitor=1)
    if not before.get("ok"):
        print(f"[ERROR] Screen capture failed: {before.get('error')}")
        sys.exit(1)

    print(f"  Screenshot : {before['path']}")
    print(f"  Resolution : {before['resolution']} (original: {before.get('original_resolution', '?')})")
    print(f"  Scale      : x={before.get('scale_x', 1.0):.3f}, y={before.get('scale_y', 1.0):.3f}")
    print("\n  Asking GPT-4o to describe the screen...")

    before_desc = _describe_screen(
        runtime,
        before["base64"],
        "Describe what is currently visible on the screen in 2-3 sentences. Be specific about open windows, UI elements, and any text you can read."
    )
    print(f"\n  BEFORE description:\n  {before_desc}")

    # ------------------------------------------------------------------
    # STEP 2 — CLICK: visual_click with verify=True
    # ------------------------------------------------------------------
    _header(f"Step 2 — CLICK (Target: \"{target}\")")
    print("  Calling visual_click with verify=True ...")
    print("  (GPT-4o will locate the element → mouse moves → click → re-capture)\n")

    t_start = time.monotonic()
    result = visual_click(
        target_description=target,
        runtime=runtime,
        verify=True,      # auto re-captures screen 0.8s after click
    )
    elapsed = time.monotonic() - t_start

    if not result.get("ok"):
        print(f"[ERROR] Click failed: {result.get('error')}")
        sys.exit(1)

    print(f"  ✅ Clicked successfully in {elapsed:.1f}s")
    print(f"  AI coords  : {result.get('ai_coords')}  (in resized image space)")
    print(f"  Real coords: {result.get('real_coords')} (actual screen pixels)")
    print(f"  Scale used : {result.get('scale')}")
    print(f"  Before shot: {result.get('before_path')}")
    print(f"  After shot : {result.get('after_path', 'N/A')}")

    # ------------------------------------------------------------------
    # STEP 3 — AFTER: describe what changed
    # ------------------------------------------------------------------
    after_b64 = result.get("after_base64")
    if after_b64:
        _header("Step 3 — AFTER (What changed?)")
        print("  Asking GPT-4o to describe what changed after the click...\n")

        after_desc = _describe_screen(
            runtime,
            after_b64,
            f"The user just clicked '{target}'. Describe what changed on the screen compared to before. "
            "What new window, dialog, or UI state appeared? Be specific and concise (2-3 sentences)."
        )
        print(f"  AFTER description:\n  {after_desc}")
    else:
        print("\n  [SKIP] No after-screenshot available (verify may have failed).")
        after_desc = "N/A"

    # ------------------------------------------------------------------
    # STEP 4 — REPORT
    # ------------------------------------------------------------------
    _header("Closed-Loop Report")
    print(f"  Target    : {target}")
    print(f"  Clicked   : ✅ YES at real coords {result.get('real_coords')}")
    print(f"  Verified  : {'✅ YES' if result.get('verified') else '⚠️  NO (no after-shot)'}")
    print(f"  Duration  : {elapsed:.1f}s total")
    print()
    print("  BEFORE:")
    for line in before_desc.splitlines():
        print(f"    {line}")
    print()
    print("  AFTER:")
    for line in after_desc.splitlines():
        print(f"    {line}")
    print()
    print("  Loop complete. 🎯")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_arg = " ".join(sys.argv[1:]).strip()
    else:
        print("A.N.K.I.T.A Closed-Loop Demo")
        print("What UI element should Ankita click?")
        target_arg = input("Target > ").strip()
        if not target_arg:
            print("No target provided. Exiting.")
            sys.exit(0)

    run_demo(target_arg)
