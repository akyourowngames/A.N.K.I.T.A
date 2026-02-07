# Quick Action Guide: Adding Realistic Tools to Situations

## ✅ What You Should Do

### 1. Use ONLY Real Tools
Check `ankita/registry/tools.json` - only use tools listed there!

**Common Real Tools:**
- `web.search` - Search anything
- `youtube.play/trending/shorts` - Videos/music
- `instagram.feed/reels/dm` - Social media
- `system.brightness.down/up` - Screen brightness  
- `system.volume.down/up/mute` - Audio
- `dnd.on/off` - Do not disturb
- `timer.set` - Timers/alarms
- `weather.current/forecast` - Weather
- `notepad.open/write` - Notes
- `files.downloads/documents/pictures` - File access
- `calendar.today/week` - Calendar
- `system.app.open/close` - App control
- `system.wifi.on/off` - WiFi
- `system.battery.status` - Battery info

### 2. Give Each Situation 3-6 Tools

**❌ BAD (only 1-2 tools):**
```python
"hungry": {
    "expected_actions": ["web.search"]  # Too limited!
}
```

**✅ GOOD (multiple options):**
```python
"hungry": {
    "expected_actions": [
        "web.search",          # Search restaurants
        "files.downloads",     # Saved recipes
        "notepad.open",        # Shopping list
        "youtube.play"         # Cooking videos
    ]
}
```

### 3. Mix Different Tool Types

Combine:
- **Search**: `web.search`
- **Media**: `youtube.play`, `instagram.feed`
- **System**: `system.brightness.down`, `dnd.on`
- **Files**: `files.downloads`, `files.pictures`
- **Utilities**: `timer.set`, `notepad.open`, `calendar.today`

### 4. Be Realistic

**For "sick":**
```python
"sick": {
    "expected_actions": [
        "web.search",              # Symptoms
        "notepad.open",            # Log symptoms
        "timer.set",               # Medicine reminder
        "system.brightness.down",  # Headache relief
        "system.volume.down"       # Quiet mode
    ]
}
```

**For "tired":**
```python
"tired": {
    "expected_actions": [
        "dnd.on",                  # No interruptions
        "system.brightness.down",  # Ease eyes
        "timer.set",               # Nap alarm
        "youtube.play",            # Sleep sounds
        "system.wifi.off"          # Disconnect
    ]
}
```

---

## 📝 Two Ways to Add Situations

### Option 1: Quick Edit (Recommended)
Just tell me: **"Add these situations: sick, tired, stressed, bored, battery_low"**

I'll add them with realistic tools from tools.json!

### Option 2: Manual (Advanced)
1. Open: `ankita/brain/scenario_generator.py`
2. Find line 16: `return {`
3. Add your situation:
```python
"sick": {
    "queries": [
        "I'm sick",
        "I don't feel well",
        "I have a headache",
        # 5-10 variants
    ],
    "contexts": {
        "any_time": {"hour": list(range(0, 24))}
    },
    "expected_actions": [
        "web.search",
        "notepad.open",
        "timer.set",
        # 3-6 real tools
    ]
}
```

---

## 🎯 Ready to Add?

I can add 10-15 comprehensive situations right now! 

**Just say:**
- "Add common situations" (I'll add 10 most useful)
- "Add sick, tired, stressed" (specific ones)
- "Add everything" (comprehensive 20+ situations)

**I'll use ONLY real tools from tools.json!** ✅
