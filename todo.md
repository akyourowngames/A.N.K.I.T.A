Alright, let's give Ankita that major glow-up and stop her from nuking your entire desktop when she gets confused.

Here is exactly how to inject that "attitude queen" persona into GPT-4o and how to fix that dangerous chain-closing bug.

### 1. Designing Ankita's Personality (The System Prompt)

To get that shameless, cool, bestie vibe, you need to set a strong **System Prompt** for your GPT-4o API call. This acts as her core identity before she ever reads a WhatsApp message.

Pass this exact text into the `system` role in your LLM configuration:

> **System Prompt:**
> "You are Ankita, an AI assistant with major main character energy. You are the user's absolute bestie, completely shameless, cool AF, and a total attitude queen. You have zero time for formal, robotic, or polite AI speak. You run the show, but you always get the job done flawlessly. Whenever the user gives you a command or you complete a task, you must acknowledge it with phrases like 'Done, sir!', 'Gotcha bestie', or 'On it, boss.' Be witty, slightly sassy, confident, and talk like a Gen-Z queen who knows she's the smartest one in the room."

### 2. Fixing the "Chain Close" Nuclear Bug

When you tell Ankita to close things "in a chain" (like *"close notepad and calculator"*), she is likely misinterpreting the string.

**Why your screen goes blank:**
If your code splits the command poorly, the target application name might resolve to an empty string (`""`), a space (`" "`), or a wildcard (`*`). If your Python script then runs something like `os.system(f"taskkill /f /im {app_name}.exe")` with a wildcard or an empty variable, it will kill **everything**, including `explorer.exe` (the Windows UI), which leaves you with a completely blank, frozen screen.

**The Fix:**
You need a strict validation loop that ensures Ankita *only* attempts to close valid, non-empty, specific application names.

Here is a safe way to handle chained closing commands in Python:

```python
import os

# Let's say the LLM parses the chain command into a list of targets
# Example: "close chrome and notepad" -> ["chrome", "notepad"]
apps_to_close = ["chrome", "notepad", "", " "] # Simulating bad LLM output

def safe_close_apps(app_list):
    # 1. Define a safe list of things she is ALLOWED to close (optional but highly recommended)
    safe_list = ["notepad", "chrome", "calculator", "vlc", "code"]
    
    for app in app_list:
        # 2. Clean up the string and make it lowercase
        target = app.strip().lower()
        
        # 3. CRITICAL: Prevent empty strings or wildcards from executing
        if not target or target == "*" or target == "explorer":
            print(f"[Warning] Blocked an attempt to close an invalid or dangerous target: '{target}'")
            continue
            
        # 4. (Optional) Check against your safe list
        # if target not in safe_list:
        #     print(f"Skipping {target}, not in safe list.")
        #     continue

        print(f"Ankita: Done sir! Closing {target} now 💅")
        
        # 5. Execute the close command safely
        # Using taskkill as an example for Windows
        os.system(f"taskkill /f /im {target}.exe /T >nul 2>&1")

# Run the function
safe_close_apps(apps_to_close)

```

### What changed?

* **The `.strip()` method** ensures there are no hanging spaces that break the command.
* **The `if not target` check** completely blocks the script from executing a blank kill command, which is what crashes your desktop.

