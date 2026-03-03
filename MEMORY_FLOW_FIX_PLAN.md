# Memory Flow Fix Implementation Plan

Based on the todo.md review, here are the issues and fixes:

## Issue 1: Memory Write-Back from Specialists (HIGH PRIORITY)

**Status:** ✅ ALREADY WORKING
**Analysis:** After reviewing the code:
- `chat.py` calls `memory.add(session_id, "assistant", reply)` after orchestrator.run()
- `gui.py` calls `self.memory.add(self.session_id, "assistant", reply)` after orchestrator.run()
- `telegram_bot.py` calls `memory.add(session_id, "assistant", content_reply)` after orchestrator.run()

The specialist replies ARE being written to ChromaDB. The architecture is correct:
1. Orchestrator returns the reply string
2. Caller (chat/gui/telegram) writes it to ChromaDB with session_id

**No fix needed** - this is working as designed.

## Issue 2: Bridge Two Memory Systems (MEDIUM PRIORITY)

**Current State:**
- ChromaDB (`memory.py`) - semantic vector search
- JSON Vault (`tools/memory_ops.py`) - explicit facts

**Problem:** When `_inject_memory()` runs, it only queries ChromaDB. It doesn't include explicit facts from the JSON vault.

**Fix:** Update `_inject_memory()` to:
1. Query ChromaDB for semantic matches
2. Query JSON vault for explicit facts
3. Combine both into a single memory block

**Implementation:**
```python
def _inject_memory(messages: List[Dict[str, Any]], session_id: str) -> None:
    # 1. Get semantic memories from ChromaDB
    chromadb_memories = memory_store.search(query=recent_context, n=5)
    
    # 2. Get explicit facts from JSON vault
    from tools.memory_ops import recall_all_categories
    vault_facts = recall_all_categories()
    
    # 3. Combine into unified memory block
    memory_block = format_unified_memory(chromadb_memories, vault_facts)
    
    # 4. Inject into system message
    if messages and messages[0].get("role") == "system":
        messages[0]["content"] = f"{messages[0]['content']}\n\n{memory_block}"
```

## Issue 3: Vary DreamAgent's Query (LOW PRIORITY)

**Current State:** DreamAgent uses hardcoded query:
```python
results = memory_store.search(
    query="recent work tasks ideas problems struggles projects",
    n=n_memories
)
```

**Fix:** Make the query dynamic based on:
- Recent conversation topics
- Time of day
- User's current activity

**Implementation:**
```python
def _generate_dream_query(recent_messages: List[Dict]) -> str:
    # Extract topics from recent messages
    topics = extract_topics(recent_messages[-5:])
    
    # Vary by time of day
    hour = datetime.now().hour
    if 6 <= hour < 12:
        focus = "morning tasks goals plans"
    elif 12 <= hour < 18:
        focus = "work progress challenges"
    else:
        focus = "reflections learnings insights"
    
    return f"{' '.join(topics)} {focus}"
```

## Issue 4: Add Token Guard to _inject_memory (LOW PRIORITY)

**Problem:** If ChromaDB has thousands of entries, top-5 results could be verbose and bloat context.

**Fix:** Cap injected memory block at ~500 tokens

**Implementation:**
```python
def _inject_memory(messages: List[Dict[str, Any]], session_id: str, max_tokens: int = 500) -> None:
    memory_block = format_unified_memory(chromadb_memories, vault_facts)
    
    # Token guard
    estimated_tokens = len(memory_block.split()) * 1.3  # rough estimate
    if estimated_tokens > max_tokens:
        # Truncate to fit
        words = memory_block.split()
        target_words = int(max_tokens / 1.3)
        memory_block = ' '.join(words[:target_words]) + "..."
    
    # Inject
    ...
```

## Implementation Priority

1. ✅ **Issue 1** - Already working, verify with tests
2. 🔧 **Issue 2** - Bridge two memory systems (IMPLEMENT NOW)
3. 🔧 **Issue 3** - Vary DreamAgent query (IMPLEMENT NOW)
4. 🔧 **Issue 4** - Token guard (IMPLEMENT NOW)

## Testing Plan

Create `test_memory_flow.py` that verifies:
1. ✅ Specialist replies are written to ChromaDB
2. ✅ _inject_memory includes both ChromaDB and JSON vault
3. ✅ DreamAgent uses dynamic queries
4. ✅ Memory injection respects token limits
5. ✅ Cross-session memory works correctly

## Files to Modify

1. `agents/orchestrator.py` - Update `_inject_memory()` to bridge systems
2. `agents/dream_agent.py` - Update query generation
3. `tools/memory_ops.py` - Add `recall_all_categories()` helper
4. `memory.py` - Add token estimation helper

## Success Criteria

- [ ] _inject_memory combines ChromaDB + JSON vault
- [ ] DreamAgent query varies based on context
- [ ] Memory injection capped at 500 tokens
- [ ] All tests passing
- [ ] Documentation updated
