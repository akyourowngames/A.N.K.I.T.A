# Remaining Fixes for ANKITA - Implementation Guide

## Status Summary

From todo.md analysis:
- ✅ 13/14 upgrades complete
- ⚠️ 4 bugs remaining to fix

---

## Bug 1: ContextAgent Not Wired (CRITICAL)

**Location:** `agents/orchestrator.py` line ~837

**Current State:** ContextAgent is instantiated in `__init__` but never called in `run()`

**Fix Required:**
Add this code at the START of the `run()` method (before Supervisor routing):

```python
# 0. CONTEXT AGENT: Extract context from conversation history BEFORE routing
context_block = None
try:
    context_result = self.context_agent.extract(user_text, messages)
    if context_result and context_result.get("context_block"):
        context_block = context_result["context_block"]
        print(f"[ContextAgent] Extracted context: {context_block[:100]}...", flush=True)
except Exception as ctx_err:
    print(f"[ContextAgent] Failed to extract context: {ctx_err}", flush=True)

# Inject context block into supervisor routing if available
routing_text = user_text
if context_block:
    routing_text = f"{context_block}\n\nUser request: {user_text}"

# Then pass routing_text to supervisor instead of user_text:
routing = self.supervisor.route(routing_text, history=supervisor_history)
```

**Impact:** Fixes "finish that", "fix it", and all ambiguous follow-up commands

---

## Bug 2: Music Confidence Threshold Too High (CRITICAL)

**Location:** `tools/music_ops.py` line 384

**Current Code:**
```python
if not best or not bool(found.get("is_confident_match")):
    candidates = [str(r.get("title", "")) for r in found.get("results", [])[:3]]
    raise RuntimeError(f"Low confidence match. Top: {' | '.join(candidates)}")
```

**Fix Required:**
```python
# Try all candidates down to 0.35 score instead of failing immediately
candidates = found.get("results", [])
for candidate in candidates:
    score = float(candidate.get("score", 0.0))
    if score >= 0.35:  # Lower threshold from 0.62 to 0.35
        best = candidate
        break

if not best or float(best.get("score", 0.0)) < 0.35:
    candidate_names = [str(r.get("title", "")) for r in candidates[:3]]
    raise RuntimeError(f"No confident match found (all < 0.35). Top: {' | '.join(candidate_names)}")
```

**Impact:** Allows regional/niche music to play instead of failing on low confidence

---

## Bug 3: Dual Routing Not Implemented

**Location:** `agents/orchestrator.py` line ~855 (after routing = self.supervisor.route(...))

**Current State:** Supervisor outputs confidence score but Orchestrator doesn't use it

**Fix Required:**
Add this code after reading the routing result:

```python
confidence: float = routing.get("confidence", 1.0)  # Read confidence score

# DUAL ROUTING PROTOCOL: If confidence < 0.65, run both primary and fallback
if confidence < 0.65 and len(agent_names) == 1:
    primary = agent_names[0]
    fallback_map = {
        "FileAgent": "TerminalAgent",
        "WebAgent": "GeneralAgent",
        "SystemAgent": "TerminalAgent",
        "CodeAgent": "TerminalAgent",
        "MusicAgent": "GeneralAgent",
    }
    if primary in fallback_map:
        fallback_agent = fallback_map[primary]
        agent_names.append(fallback_agent)
        print(f"[DualRouting] Low confidence ({confidence:.2f}) - adding fallback: {fallback_agent}", flush=True)
```

**Impact:** Eliminates wrong-agent routing errors on ambiguous requests

---

## Bug 4: Double-Open File Bug

**Location:** `agents/specialists.py` - SystemAgent prompt, line ~450

**Current Issue:** FileAgent opens file, then SystemAgent opens it again

**Fix Required:**

1. In `_build_prior_context_block()` in orchestrator.py (~line 150):
```python
# DOUBLE-OPEN FIX: Check if FileAgent already opened the file
file_already_opened = agent_name == "FileAgent" and ("opened" in reply.lower() or "launch_app" in reply.lower())

if artifacts["files"]:
    # If FileAgent already opened the file, don't pass FILE_PATH to next agent
    if not file_already_opened:
        for f in artifacts["files"]:
            lines.append(f"FILE: {f}")
```

2. In SystemAgent prompt in specialists.py:
```python
"DOUBLE-OPEN PREVENTION: If the previous agent's reply contains 'Opened' or 'launch_app was called', "
"DO NOT call launch_app again for the same file. The file is already open.\n"
```

**Impact:** Prevents duplicate file opening

---

## Implementation Priority

1. **Bug 1 (ContextAgent)** - 5 minutes - Highest impact
2. **Bug 2 (Music threshold)** - 3 minutes - User-facing
3. **Bug 3 (Dual routing)** - 5 minutes - Improves reliability
4. **Bug 4 (Double-open)** - 2 minutes - Polish

**Total Time:** ~15 minutes

---

## Testing After Fixes

1. Test ContextAgent: "finish that" after a previous task
2. Test Music: "play some regional Indian music"
3. Test Dual Routing: Give an ambiguous command like "show me the code"
4. Test Double-Open: "write a poem and open it"

---

## Notes

- All fixes are backward compatible
- No breaking changes to existing functionality
- These are the ONLY remaining items from the 14-upgrade plan
- After these fixes, ANKITA will be 100% complete per the master plan
