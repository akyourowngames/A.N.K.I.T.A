I see exactly what is going on in that final screenshot (`image_1a5078.png`). You ran `python whatsapp_runner.py` and instantly hit a wall:

`TypeError: AgentRuntime.__init__() got an unexpected keyword argument 'system_prompt'`

This is a classic code generation hallucination. Your assistant tried to force a `system_prompt` directly into the Orchestrator's initialization, but your `AgentRuntime` architecture doesn't accept that argument (because prompts are handled inside `agents/specialists.py`).

On top of that, wanting to hijack your *actual* Chrome profile so you don't have to rescan the QR code is a total boss move. We can absolutely do that.

Here is the exact battle plan to fix the bug and hijack your local Chrome profile.

### 1. Fix the `TypeError` Crash

Open `whatsapp_runner.py` and look around line 64.

```python
# ❌ Delete the system_prompt line from AgentRuntime
agent = AgentRuntime(
    llm_provider="copilot",
    system_prompt="..." # <-- DELETE THIS ENTIRE LINE
)

# ✅ It should look like this:
agent = AgentRuntime(llm_provider="copilot")

```

*Note: The `CommsAgent` prompt is already safely stored in your `specialists.py` file, so the runtime doesn't need it here.*

### 2. Hijack Your Default Chrome Profile ("Krish")

To use your real Chrome browser instead of Playwright's default Chromium, we need to point Playwright directly to your Windows AppData folder. Looking at your terminal path, your Windows username is `anime`.

Open `services/whatsapp_bridge.py` and update the browser launch code:

```python
# Replace your current context initialization with this:

chrome_user_data_path = r"C:\Users\anime\AppData\Local\Google\Chrome\User Data"

context = p.chromium.launch_persistent_context(
    user_data_dir=chrome_user_data_path,
    channel="chrome", # This forces Playwright to use your real Chrome installation
    headless=False,
    # If "Krish" is not your default profile, uncomment the line below and change the profile number
    # args=["--profile-directory=Profile 1"] 
)

```

### ⚠️ The "Ghost Browser" Golden Rule

Because you are hijacking your real Chrome database, **you MUST close all open Google Chrome windows before running the script**.
If you leave a normal Chrome window open, Playwright will crash with a "Database Locked" error because two programs can't read the Chrome profile at the exact same time.

Make those two code edits, close out of your normal Chrome browser completely, and run `python whatsapp_runner.py` again.

Would you like me to walk you through how to find your exact `--profile-directory` name if "Krish" isn't the primary "Default" profile?