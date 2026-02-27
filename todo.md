This is the **"Proactive Sentinel" Upgrade**.

You are describing the "Holy Grail" of AI: **Agency**. Instead of waiting for you to type, Ankita will realize you are stuck (idle) and reach out to *you* first.

Here is the **God-Tier Plan** to build this:

### 1. The "Pulse" (Idle Detection) 💓

We need a way to detect if you haven't moved the mouse or typed for X minutes.

* **The Tech:** We use the Windows API (`GetLastInputInfo`) via Python's `ctypes`.
* **The Logic:** `Idle_Time = Current_System_Time - Last_Input_Time`.

### 2. The "Sentinel Loop" (Background Brain) 🔄

We run a lightweight thread that checks your pulse every 10 seconds.

* **Condition:** If `Idle_Time > 5 minutes`:
1. **Trigger:** `ScreenAgent` wakes up.
2. **Capture:** Takes a snapshot of your screen.
3. **Analyze:** "User has been staring at this Python error for 5 minutes."
4. **Action:** Ankita speaks: *"Hey, I see you're stuck on that syntax error. Want me to fix it?"*



### 3. The "Proactive Persona" (New Prompt) 🧠

We update `specialists.py` to give the ScreenAgent a "Nudge Mode."

* **Instruction:** "If triggered by idle time, be helpful but low-pressure. Don't be annoying. Offer specific help based on the screen content."

---

### Step 1: Create `tools/idle_ops.py`

This tool lets Ankita check how long you've been AFK (Away From Keyboard).

```python
"""
Idle Detection Tool for A.N.K.I.T.A.
Uses Windows API to check how long since the user last touched the mouse/keyboard.
"""
import ctypes
import ctypes.wintypes

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.c_uint),
        ('dwTime', ctypes.c_ulong),
    ]

def get_idle_seconds() -> float:
    """Returns the number of seconds the user has been idle."""
    lastInputInfo = LASTINPUTINFO()
    lastInputInfo.cbSize = ctypes.sizeof(lastInputInfo)
    
    # Call Windows API
    if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lastInputInfo)):
        # GetTickCount() returns milliseconds since boot
        millis = ctypes.windll.kernel32.GetTickCount() - lastInputInfo.dwTime
        return millis / 1000.0
    else:
        return 0.0

```

### Step 2: Update `main.py` (The Sentinel Loop)

We modify your main script to run this check in the background.

**(Add this logic to your main loop or create `sentinel.py`):**

```python
import time
import threading
from tools.idle_ops import get_idle_seconds
from tools.desktop_ops import capture_screen
# ... import your orchestrator ...

IDLE_THRESHOLD = 300  # 5 Minutes
CHECK_INTERVAL = 10   # Check every 10s

def sentinel_loop(orchestrator):
    print(f"[Sentinel] Watching for idle > {IDLE_THRESHOLD}s...")
    triggered = False
    
    while True:
        idle = get_idle_seconds()
        
        # Trigger ONLY if idle long enough AND haven't triggered yet for this session
        if idle > IDLE_THRESHOLD and not triggered:
            print(f"[Sentinel] User idle for {idle}s. Waking up Ankita...")
            triggered = True
            
            # 1. Capture Screen
            screen_res = capture_screen() # Uses the turbo mode we built
            
            # 2. Inject into Orchestrator as a "System Trigger"
            prompt = (
                "SYSTEM ALERT: The user has been idle/stuck for 5 minutes. "
                "Look at this screenshot. Analyze what they are working on. "
                "If it looks like an error or a blank page, proactively offer specific help. "
                "Be brief and casual."
            )
            
            # 3. Fire! (You'll need to adapt this to your specific runtime call)
            # This simulates the user sending the screenshot, but marked as system alert
            response = orchestrator.run(prompt, screen_res) # Pseudo-code
            
            # 4. Speak the result
            print(f"\n[Ankita]: {response}")
            # tts_speak(response) # Optional: Voice Output
            
        # Reset trigger if user comes back
        if idle < 5:
            if triggered:
                print("[Sentinel] User returned. Resetting watch.")
            triggered = False
            
        time.sleep(CHECK_INTERVAL)

# Start in background
# t = threading.Thread(target=sentinel_loop, args=(my_orchestrator,), daemon=True)
# t.start()

```

### Step 3: Proactive Agent Tuning

In `specialists.py`, update `_SCREEN_SYSTEM_PROMPT` to handle this specific "Proactive" intent:

> **PROACTIVE MODE:**
> "If you receive a 'SYSTEM ALERT' about idle time:
> 1. Identify the *blocker* (e.g., 'Syntax Error on line 40', 'Writer's block on empty Word doc', 'Doomscrolling Twitter').
> 2. Offer a specific solution.
> * *Bad:* 'Can I help?'
> * *Good:* 'I see a NameError on line 40. Want me to fix that variable typo?'"
> 
> 
> 
> 

**Ready to install the Idle Detector?** I can give you the full `tools/idle_ops.py` code to copy-paste.