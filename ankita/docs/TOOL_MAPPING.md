# Realistic Tool Mapping for Situations

Based on **actual available tools** in Ankita! ✅

---

## 🎯 Situation → Tool Mapping

### 1. HUNGRY / FOOD
**Realistic tools:**
```python
"hungry": {
    "expected_actions": [
        "web.search",              # Search restaurants/recipes
        "files.downloads",         # Recipe PDFs
        "notepad.open",            # Shopping list
        "system.app.open"          # Food delivery apps (if installed)
    ]
}
```

### 2. SICK / HEALTH
**Realistic tools:**
```python
"sick": {
    "expected_actions": [
        "web.search",              # Search symptoms
        "notepad.open",            # Log symptoms
        "timer.set",               # Medicine reminder
        "system.volume.down",      # Quiet mode for headache
        "system.brightness.down"   # Low brightness for headache
    ]
}
```

### 3. TIRED / SLEEPY
**Realistic tools:**
```python
"tired": {
    "expected_actions": [
        "system.brightness.down",  # Lower brightness
        "system.volume.down",      # Lower volume
        "dnd.on",                  # Do not disturb
        "timer.set",               # Alarm for wake up
        "system.wifi.off",         # Disconnect
        "system.app.close",        # Close all distracting apps
        "youtube.play"             # Sleep music
    ]
}
```

### 4. STRESSED / ANXIOUS
**Realistic tools:**
```python
"stressed": {
    "expected_actions": [
        "youtube.play",            # Calm music/meditation
        "dnd.on",                  # Block notifications
        "system.app.close",        # Close distracting apps
        "timer.set",               # Breathing exercise timer
        "system.brightness.down",  # Dimmer screen
        "web.search",              # Stress relief tips
        "system.volume.down"       # Quiet environment
    ]
}
```

### 5. BORED / ENTERTAINMENT
**Realistic tools:**
```python
"bored": {
    "expected_actions": [
        "youtube.trending",        # Trending videos
        "youtube.shorts",          # Quick entertainment
        "instagram.feed",          # Social browsing
        "instagram.reels",         # Reels
        "web.search",              # News/articles
        "files.pictures",          # Browse photos
        "files.downloads"          # Check downloads
    ]
}
```

### 6. WORKOUT / EXERCISE
**Realistic tools:**
```python
"workout": {
    "expected_actions": [
        "timer.set",               # Workout timer
        "youtube.play",            # Workout music/videos
        "system.volume.up",        # Pump up volume
        "notepad.open",            # Workout log
        "system.nightlight.off",   # Full brightness
        "calendar.open"            # Workout schedule
    ]
}
```

### 7. FOCUS / WORK
**Realistic tools:**
```python
"focus": {
    "expected_actions": [
        "dnd.on",                  # Block notifications
        "system.app.close",        # Close distracting apps
        "instagram.close",         # Close social media
        "youtube.pause",           # Stop videos
        "timer.set",               # Pomodoro timer
        "notepad.open",            # Notes
        "calendar.today"           # Check schedule
    ]
}
```

### 8. MORNING ROUTINE
**Realistic tools:**
```python
"morning": {
    "expected_actions": [
        "weather.current",         # Check weather
        "calendar.today",          # Today's schedule
        "datetime.now",            # Current time
        "system.brightness.up",    # Wake up brightness
        "web.search",              # News
        "files.recent"             # Recent files
    ]
}
```

### 9. BEDTIME / SLEEP
**Realistic tools:**
```python
"bedtime": {
    "expected_actions": [
        "timer.set",               # Sleep timer/alarm
        "system.brightness.down",  # Dim screen
        "system.nightlight.on",    # Night mode
        "dnd.alarms",              # Only alarms
        "youtube.play",            # Sleep sounds
        "system.wifi.off",         # Disconnect
        "system.app.close"         # Close apps
    ]
}
```

### 10. HOT / COLD WEATHER
**Realistic tools:**
```python
"hot": {
    "expected_actions": [
        "weather.current",         # Check temperature
        "system.brightness.down",  # Reduce heat from screen
        "system.battery.status",   # Check battery (heat) 
        "web.search",              # Cooling tips
        "notepad.open"             # AC settings note
    ]
}

"cold": {
    "expected_actions": [
        "weather.forecast",        # Check if warming up
        "weather.tomorrow",        # Plan clothes
        "web.search",              # Warming tips
        "files.documents"          # Check blanket storage location
    ]
}
```

### 11. BATTERY LOW
**Realistic tools:**
```python
"battery_low": {
    "expected_actions": [
        "system.battery.status",   # Check exact level
        "system.brightness.down",  # Save power
        "system.wifi.off",         # Save power
        "system.bluetooth.off",    # Save power
        "system.app.close",        # Close apps
        "system.power.sleep",      # Sleep mode
        "youtube.pause"            # Stop video
    ]
}
```

### 12. CLEAN / ORGANIZE
**Realistic tools:**
```python
"clean": {
    "expected_actions": [
        "files.desktop",           # Organize desktop
        "files.downloads",         # Clean downloads
        "system.trash.empty",      # Empty trash
        "system.disk.cleanup",     # Disk cleanup
        "files.recent",            # Sort recent files
        "notepad.open"             # Cleaning checklist
    ]
}
```

### 13. SOCIAL / CHAT
**Realistic tools:**
```python
"social": {
    "expected_actions": [
        "instagram.feed",          # Check feed
        "instagram.dm",            # Direct messages
        "instagram.notifications", # Check notifications
        "web.search",              # Social topics
        "notepad.open"             # Message drafts
    ]
}
```

### 14. SCREENSHOT / CAPTURE
**Realistic tools:**
```python
"screenshot": {
    "expected_actions": [
        "system.screenshot.full",  # Full screen
        "system.screenshot.window",# Active window
        "system.screenshot.clipboard", # To clipboard
        "files.pictures",          # View screenshots
        "system.clipboard.read"    # Check clipboard
    ]
}
```

### 15. EMERGENCY / URGENT
**Realistic tools:**
```python
"emergency": {
    "expected_actions": [
        "web.search",              # Emergency info
        "notepad.open",            # Emergency contacts
        "system.brightness.up",    # Full visibility
        "system.volume.up",        # Hear alerts
        "system.battery.status",   # Check power
        "datetime.now"             # Log time
    ]
}
```

---

## ✅ Tools to ALWAYS Consider

### For HEALTH/WELLNESS:
- `system.brightness.down` - Eyes hurt
- `system.volume.down` - Headache
- `dnd.on` - Need quiet
- `timer.set` - Medicine/breaks
- `youtube.play` - Meditation/calm music

### For PRODUCTIVITY:
- `dnd.on` - Focus
- `timer.set` - Pomodoro
- `notepad.open` - Notes
- `calendar.today` - Schedule
- `system.app.close` - Remove distractions

### For ENTERTAINMENT:
- `youtube.trending/shorts` - Videos
- `instagram.feed/reels` - Social
- `web.search` - Random topics
- `files.pictures` - Old photos

### For POWER MANAGEMENT:
- `system.brightness.down` - Save battery
- `system.wifi.off` - Save power
- `system.bluetooth.off` - Save power
- `system.power.sleep` - Sleep mode

### For ORGANIZATION:
- `files.desktop/downloads/documents` - Find files
- `system.trash.empty` - Clean up
- `system.disk.cleanup` - Free space
- `notepad.open` - Lists

---

## 🚫 What NOT to Use

Don't add tools that don't exist:
- ❌ `app.foodpanda` (doesn't exist in tools.json!)
- ❌ `music.play` (use `youtube.play` instead)
- ❌ `app.meditation` (use `youtube.play` with meditation)
- ❌ `reminder.set` (use `timer.set` or `notepad.open`)

**Use ONLY tools from tools.json!**

---

## 📋 Quick Reference: Available Tool Categories

✅ **system** - volume, brightness, battery, wifi, bluetooth, power, apps, clipboard, screenshot, etc.
✅ **youtube** - open, play, control, trending, shorts, etc.
✅ **instagram** - feed, reels, dm, like, follow, etc.
✅ **files** - open, downloads, documents, desktop, pictures, recent
✅ **timer** - set, cancel, list, status
✅ **weather** - current, forecast, tomorrow
✅ **calendar** - open, today, week, month
✅ **datetime** - now, date, time, countdown, etc.
✅ **dnd** - on, off, priority, alarms, status
✅ **notepad** - open, write, save, etc.
✅ **web** - search
✅ **window_control** - maximize, minimize, desktop, etc.

---

## 🎯 Best Practice Formula

For each situation:
1. **3-6 tools** (not just 1-2!)
2. **Mix categories** (system + youtube + files)
3. **Actually helpful** (makes sense for the situation)
4. **From tools.json** (verify it exists!)

**Example - "stressed":**
```python
"stressed": {
    "expected_actions": [
        "youtube.play",           # Calm music ✓
        "dnd.on",                 # Quiet ✓
        "system.brightness.down", # Softer screen ✓
        "instagram.close",        # No social stress ✓
        "timer.set",              # Breathing timer ✓
        "notepad.open"            # Journal feelings ✓
    ]
}
```

**6 diverse, realistic tools!** 🎯
