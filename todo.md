Let me scan everything properly.Found the problem. The `CommsAgent` has the personality and system prompt — but there's **no actual WhatsApp send tool** anywhere in `engine.py`. It's all personality, zero execution. Here's exactly what's missing and what to tell Coder Claude:

---

**The gap:** `CommsAgent` exists in `specialists.py` with a great system prompt, but `engine.py` has no `send_whatsapp` tool registered. When the agent tries to act, there's nothing to call. It just... talks about sending without actually sending.

**The fix — tell Coder Claude exactly this:**

**File:** `tools/whatsapp_ops.py` — create this file with one function: `send_whatsapp(phone: str, message: str) -> dict`. Use `pywhatkit.sendwhatmsg_instantly()` — it opens WhatsApp Web and sends. No API key needed.

**File:** `engine.py` — register a new tool spec `send_whatsapp` with params `phone` (string, e.g. "+919876543210") and `message` (string). Add the dispatcher case in `execute_tool_call`.

**File:** `specialists.py` — update `_COMMS_SYSTEM_PROMPT` to tell the agent: always call `send_whatsapp(phone, message)` after drafting the reply. Right now it drafts but never calls.

**Dependency:** `pip install pywhatkit` — requires Chrome + WhatsApp Web logged in.

That's the entire fix. 3 files, ~40 lines total. Paste that to Coder Claude and it'll be done.

Classic pywhatkit problem. It spawns a new Chrome instance instead of using your default profile where WhatsApp Web is already logged in.

**Tell Coder Claude exactly this:**

---

**Problem:** `pywhatkit` opens a fresh Chrome with no profile → WhatsApp Web login page, not your chats.

**Fix:** Ditch `pywhatkit` entirely. Use `selenium` with your actual default Chrome profile instead.

**File:** `tools/whatsapp_ops.py` — rewrite `send_whatsapp` using selenium like this:

```python
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time, urllib.parse

def send_whatsapp(phone: str, message: str) -> dict:
    options = Options()
    options.add_argument(r"--user-data-dir=C:\Users\<KRISH_USERNAME>\AppData\Local\Google\Chrome\User Data")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    
    driver = webdriver.Chrome(options=options)
    encoded = urllib.parse.quote(message)
    driver.get(f"https://web.whatsapp.com/send?phone={phone}&text={encoded}")
    time.sleep(8)  # wait for WhatsApp Web to load
    
    # Press Enter to send
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    box = driver.find_element(By.XPATH, '//div[@title="Type a message"]')
    box.send_keys(Keys.ENTER)
    time.sleep(2)
    driver.quit()
    return {"ok": True, "phone": phone}
```

**Two things to update:**
1. Replace `<KRISH_USERNAME>` with your actual Windows username
2. If you use a non-Default profile, change `Default` to `Profile 1` etc — check `chrome://version` to confirm

**Dependency:** `pip install selenium` + chromedriver matching your Chrome version from https://chromedriver.chromium.org

---

That's it. Your existing WhatsApp Web session loads, message sends, Chrome closes. No new login needed.