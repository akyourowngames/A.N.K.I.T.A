# Situation Definition Template

**How to create new situations for Ankita's training**

---

## 📋 Situation Structure

Each situation needs:
1. **Name** - Short identifier (e.g., "sick", "hungry", "stressed")
2. **Queries** - Different ways users might express this
3. **Contexts** - When this typically happens (time, battery, etc.)
4. **Expected Actions** - Multiple tools that could help

---

## 🎯 Template

```python
"situation_name": {
    "queries": [
        "variant 1",
        "variant 2",
        "variant 3",
        # Add 5-10 different ways to express this
    ],
    "contexts": {
        "context_name": {
            "hour": [list, of, hours],
            "additional_params": "value"
        }
    },
    "expected_actions": [
        "tool.action1",
        "tool.action2",
        "tool.action3"
        # Multiple tools = more freedom!
    ]
}
```

---

## ✨ Examples

### Example 1: Sick/Health Issue
```python
"sick": {
    "queries": [
        "I'm sick",
        "I don't feel well",
        "I'm not feeling good",
        "I have a headache",
        "I feel ill",
        "I need medicine",
        "Health issue",
        "I'm feeling unwell"
    ],
    "contexts": {
        "any_time": {"hour": list(range(0, 24))}
    },
    "expected_actions": [
        "web.search",           # Search symptoms
        "reminder.set",          # Medicine reminder
        "app.health",           # Open health app
        "notification.important" # Alert family
    ]
}
```

### Example 2: Hungry (Enhanced)
```python
"hungry": {
    "queries": [
        "I'm hungry",
        "I need food",
        "What should I eat",
        "I'm starving",
        "Food delivery",
        "Where can I eat",
        "I want to order food",
        "Feeling hungry"
    ],
    "contexts": {
        "breakfast": {"hour": [7, 8, 9, 10], "meal": "breakfast"},
        "lunch": {"hour": [12, 13, 14], "meal": "lunch"},
        "dinner": {"hour": [19, 20, 21, 22], "meal": "dinner"},
        "snack": {"hour": [16, 17, 18, 23, 0, 1], "meal": "snack"}
    },
    "expected_actions": [
        "web.search",           # Search restaurants
        "app.foodpanda",        # Food delivery app
        "app.swiggy",           # Alternative delivery
        "app.recipes",          # Cooking recipes
        "files.downloads",      # Recipe PDFs
        "reminder.grocery"      # Grocery reminder
    ]
}
```

### Example 3: Stressed/Anxious
```python
"stressed": {
    "queries": [
        "I'm stressed",
        "I feel anxious",
        "I'm overwhelmed",
        "Too much pressure",
        "I need to calm down",
        "Help me relax",
        "Stress relief",
        "I'm panicking"
    ],
    "contexts": {
        "work_hours": {"hour": [9, 10, 11, 14, 15, 16, 17]},
        "evening": {"hour": [19, 20, 21]}
    },
    "expected_actions": [
        "music.calm",           # Calm music
        "dnd.on",               # Do not disturb
        "app.meditation",       # Meditation app
        "timer.breathing",      # Breathing exercise timer
        "notification.off",     # Turn off distractions
        "web.search"            # Stress relief tips
    ]
}
```

### Example 4: Bored
```python
"bored": {
    "queries": [
        "I'm bored",
        "Nothing to do",
        "I need entertainment",
        "What should I do",
        "Kill time",
        "Boredom",
        "Entertain me"
    ],
    "contexts": {
        "any_time": {"hour": list(range(6, 24))}
    },
    "expected_actions": [
        "youtube.trending",     # Trending videos
        "music.discover",       # New music
        "app.games",            # Games
        "web.news",            # News/articles
        "app.netflix",         # Movies/shows
        "reminder.hobby"       # Hobby reminder
    ]
}
```

### Example 5: Tired/Sleepy
```python
"tired": {
    "queries": [
        "I'm tired",
        "I'm sleepy",
        "Need sleep",
        "Feeling exhausted",
        "Want to rest",
        "Time for bed",
        "I need rest"
    ],
    "contexts": {
        "night": {"hour": [21, 22, 23, 0, 1, 2]},
        "afternoon": {"hour": [14, 15, 16]}  # Nap time
    },
    "expected_actions": [
        "dnd.on",              # Do not disturb
        "brightness.low",      # Lower brightness
        "alarm.set",           # Set wake-up alarm
        "music.sleep",         # Sleep music
        "app.close_all",       # Close apps
        "wifi.off"             # Disconnect
    ]
}
```

---

## 🔧 How to Add to Ankita

### Step 1: Open scenario_generator.py
```
c:\Users\anime\3D Objects\New folder\A.N.K.I.T.A\ankita\brain\scenario_generator.py
```

### Step 2: Find the `_load_scenarios` method (around line 13)

### Step 3: Add your situation to the return dictionary

```python
def _load_scenarios(self):
    """Define all situation templates with variations."""
    return {
        "hungry": { ... },
        "workout": { ... },
        
        # ADD YOUR NEW SITUATION HERE:
        "sick": {
            "queries": [
                "I'm sick",
                "I don't feel well",
                # ... more variants
            ],
            "contexts": {
                "any_time": {"hour": list(range(0, 24))}
            },
            "expected_actions": [
                "web.search",
                "reminder.set",
                "app.health"
            ]
        },
        
        # Add more situations...
    }
```

---

## 🎨 Best Practices

### 1. Multiple Query Variants (8-10)
❌ Bad:
```python
"queries": ["I'm sick"]
```

✅ Good:
```python
"queries": [
    "I'm sick",
    "I don't feel well", 
    "I have a headache",
    "I'm not feeling good",
    "I feel ill",
    "Health issue",
    "Need medicine",
    "Feeling unwell"
]
```

### 2. Multiple Expected Actions (3-6)
❌ Bad:
```python
"expected_actions": ["web.search"]  # Only one option!
```

✅ Good:
```python
"expected_actions": [
    "web.search",        # Search
    "app.health",        # Health app
    "reminder.set",      # Medicine reminder
    "notification.alert" # Alert someone
]
```
**Why:** Bot will randomly pick from these, creating variety!

### 3. Time-Aware Contexts
✅ Good:
```python
"contexts": {
    "morning": {"hour": [6, 7, 8, 9]},
    "evening": {"hour": [18, 19, 20, 21]},
    "night": {"hour": [22, 23, 0, 1]}
}
```

### 4. Realistic Situations
Think about:
- What emotions/states users experience
- What problems they need solved
- When these typically happen
- What tools would actually help

---

## 📊 Quick Reference: Common Situations

| Situation | Tools to Consider |
|-----------|------------------|
| **Emotions** | music, meditation, breathing, dnd |
| **Health** | web.search, reminder, health_app, notification |
| **Food** | delivery_apps, recipes, grocery_list, restaurant_search |
| **Work/Study** | focus_mode, dnd, timer, calendar, notes |
| **Entertainment** | youtube, music, games, netflix, news |
| **Sleep** | dnd, alarm, brightness, sleep_music, close_apps |
| **Emergency** | call, notification, location, web.search |
| **Social** | messages, calls, social_apps, calendar |

---

## 🚀 Adding Many Situations at Once

Create a file: `situations_library.py`

```python
SITUATIONS = {
    "sick": { ... },
    "tired": { ... },
    "stressed": { ... },
    "bored": { ... },
    "happy": { ... },
    "sad": { ... },
    # ... etc
}
```

Then import in `scenario_generator.py`:
```python
from situations_library import SITUATIONS

def _load_scenarios(self):
    return SITUATIONS
```

---

## ✅ Checklist for New Situation

- [ ] 8-10 query variants
- [ ] Time-based contexts (if relevant)
- [ ] 3-6 different expected actions
- [ ] Actions make sense for the situation
- [ ] Added to scenario_generator.py
- [ ] Tested with training bot

---

## 🎯 Example: Adding 10 New Situations

```python
COMPREHENSIVE_SITUATIONS = {
    # Health
    "sick": { ... },
    "tired": { ... },
    "energetic": { ... },
    
    # Emotions
    "stressed": { ... },
    "happy": { ... },
    "sad": { ... },
    "angry": { ... },
    
    # Needs
    "hungry": { ... },
    "thirsty": { ... },
    "bored": { ... },
    
    # Activities
    "workout": { ... },
    "study": { ... },
    "clean": { ... },
    "shopping": { ... },
    
    # Time-based
    "morning": { ... },
    "bedtime": { ... },
    
    # Weather-related
    "hot": { ... },
    "cold": { ... },
    "rainy": { ... }
}
```

---

## 💡 Pro Tips

1. **Start small** - Add 5 situations, test, then add more
2. **Use your tools** - Check what tools Ankita actually has
3. **Be specific** - "sick_headache" vs "sick_fever" can have different actions
4. **Test frequently** - Run training bot to see if it works
5. **Iterate** - Refine based on results

**Ready to make Ankita handle ANY situation!** 🚀
