# Semantic Control System

## Overview

Ankita's **Semantic Control** transforms her from command-based to intent-aware. Instead of explicit commands, you can express vague situations and Ankita will infer what you mean and take appropriate actions.

## How It Works

```
User: "Net is slow"
  ↓
Semantic Interpreter (detects "network_slow" situation)
  ↓
Action Planner (generates: reconnect wifi)
  ↓
Execute actions
  ↓
Ankita: "I'll reconnect Wi-Fi for you."
```

## Supported Situations

### 1. **network_slow**
**When to use:** Internet is slow, pages not loading, connection issues

**Example phrases:**
- "net is slow"
- "wifi is slow"
- "internet sucks"
- "internet kam slow hai" (Hinglish)

**What Ankita does:** Reconnects Wi-Fi automatically

---

### 2. **system_hot**
**When to use:** Laptop heating, fan loud, system overheating

**Example phrases:**
- "laptop is hot"
- "system is heating"
- "fan is loud"
- "laptop garam ho raha hai" (Hinglish)

**What Ankita does:** Lowers brightness and volume to cool down

---

### 3. **bored**
**When to use:** Nothing to do, want entertainment

**Example phrases:**
- "i am bored"
- "nothing to do"
- "bore ho raha hu" (Hinglish)
- "time pass karo"

**What Ankita does:** Opens YouTube with trending videos

---

### 4. **focus**
**When to use:** Need to concentrate, study time

**Example phrases:**
- "i want focus"
- "need to concentrate"
- "let's study"
- "padhai karni hai" (Hinglish)

**What Ankita does:** Closes distracting apps (Chrome)

---

### 5. **sleepy**
**When to use:** Tired, feeling sleepy

**Example phrases:**
- "i'm sleepy"
- "neend aa rahi hai" (Hinglish)
- "sona hai"

**What Ankita does:** Dims screen, lowers volume

---

### 6. **system_slow**
**When to use:** Computer lagging, system unresponsive

**Example phrases:**
- "system is slow"
- "laptop is lagging"
- "computer slow hai"

**What Ankita does:** Closes heavy apps

---

### 7. **entertainment**
**When to use:** Want to watch something

**Example phrases:**
- "play something"
- "watch something"
- "kuch dekho"

**What Ankita does:** Opens YouTube

---

### 8. **relax**
**When to use:** Want to relax, chill

**Example phrases:**
- "i want to relax"
- "relax karna hai"
- "chill karna hai"

**What Ankita does:** Plays lofi music

---

### 9. **music**
**When to use:** Want to listen to music

**Example phrases:**
- "play music"
- "gaana chalao"
- "music chahiye"

**What Ankita does:** Plays music on YouTube

---

### 10. **work**
**When to use:** Need to start working

**Example phrases:**
- "i need to work"
- "kaam karna hai"
- "work mode"

**What Ankita does:** Opens workspace (Notepad)

---

### 11. **break**
**When to use:** Need a break from work

**Example phrases:**
- "i need a break"
- "break chahiye"
- "thoda rest"

**What Ankita does:** Locks screen for your break

---

### 12. **tired**
**When to use:** Exhausted, need rest

**Example phrases:**
- "i'm tired"
- "thak gaya"
- "bahut thaka hua"

**What Ankita does:** Dims screen and plays calm music

---

### 13. **frustrated**
**When to use:** Feeling frustrated or annoyed

**Example phrases:**
- "i'm frustrated"
- "gussa aa raha hai"
- "pareshan ho gaya"

**What Ankita does:** Plays funny videos to cheer you up

---

## Features

### 🧠 Semantic Matching
- Uses sentence embeddings (not keywords)
- Understands paraphrases and variations
- Supports Hinglish

### ⚡ Context-Aware (DWIM)
- **Battery awareness:** Skips heavy actions when battery < 20%
- **Time awareness:** Adjusts brightness for night time
- **Resource awareness:** Prefers hotspot over wifi if available

### 📚 Learning
- Learns from your feedback
- If you say "no" or "stop", that action gets lower priority
- Personalizes over time

### 🔍 Ambiguity Handling
If your statement is unclear, Ankita asks for clarification:
```
You: "System is weird"
Ankita: "Sir, kindly confirm: Do you mean: system_slow, system_hot?"
```

## Usage

Just speak or type vague statements:

```
✅ "Net is slow today"
✅ "Laptop ka hot ho raha hai"
✅ "Bored"
✅ "I can't focus"
✅ "System lag"
```

Ankita will:
1. Detect the situation
2. Plan appropriate actions
3. Execute them
4. Learn from the outcome

## Technical Details

- **Model:** sentence-transformers (all-MiniLM-L6-v2)
- **Matching:** Cosine similarity with 0.6 threshold
- **Location:** `brain/semantic/`
- **Learning:** Weights stored in `brain/semantic/learned_weights.json`

## Adding New Situations

Edit `brain/semantic/situations.json`:

```json
{
  "new_situation": {
    "phrases": [
      "phrase 1",
      "phrase 2"
    ],
    "actions": [
      {"tool": "system.app", "action": "open", "app": "notepad"}
    ],
    "weight": 1.0,
    "description": "What Ankita will say"
  }
}
```

Ankita will automatically pick up new situations!
