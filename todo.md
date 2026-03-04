Bug 1 — chat.py: session_log used before it's defined — crash on startup
python# chat.py — current order:
orchestrator.attach_memory(memory, session_id, session_log)  # ← session_log used HERE
from session_log import SessionLog
session_log = SessionLog(WORKSPACE_ROOT, session_id)         # ← defined AFTER
session_log is referenced before assignment. Python will throw UnboundLocalError on startup in CLI mode. The attach_memory() call must come after SessionLog is created.
Fix — swap the order:
pythonsession_log = SessionLog(WORKSPACE_ROOT, session_id)
orchestrator.attach_memory(memory, session_id, session_log)

Bug 2 — telegram_bot.py: set_session_id() called BEFORE SessionLog is created for new chats
python# Current order per message:
if chat_id in session_logs:
    orchestrator.set_session_id(session_id, session_logs[chat_id])  # ← passes log if exists
else:
    orchestrator.set_session_id(session_id)  # ← passes nothing for NEW chat

# ... later ...
if chat_id not in sessions:  # ← SessionLog created INSIDE this block
    session_logs[chat_id] = SessionLog(WORKSPACE_ROOT, session_id)
On the first message from a new chat, set_session_id() is called without the SessionLog (it's in the else branch), then the SessionLog is created but never passed to the orchestrator. The orchestrator's _session_log stays None forever for that chat.
Fix — move set_session_id to AFTER the if chat_id not in sessions block:
python# First ensure session + log exist
if chat_id not in sessions:
    ...
    session_logs[chat_id] = SessionLog(WORKSPACE_ROOT, session_id)

# NOW update orchestrator — log is guaranteed to exist
orchestrator.set_session_id(session_id, session_logs[chat_id])

Bug 3 — context_agent.py: SessionLog is re-instantiated from disk instead of using the live instance
python# _build_conversation_text — Source 2:
if len(clean) < 4:
    from session_log import SessionLog
    workspace_root = getattr(memory_store, "workspace_root", Path.cwd())
    if session_id:
        session_log = SessionLog(workspace_root, session_id)  # ← creates NEW instance from disk
This ignores the session_log parameter already passed into extract(). It creates a brand new SessionLog from disk every time — which means it misses messages that were appended in-memory but not yet flushed, and adds unnecessary disk reads. The passed session_log instance is never used.
Fix — use the passed session_log parameter directly:
python# In _build_conversation_text signature, accept session_log parameter
def _build_conversation_text(self, messages, memory_store, session_id, user_text, session_log=None):
    ...
    if len(clean) < 4 and session_log is not None:
        log_messages = session_log.recent(20)
        ...
    elif len(clean) < 4 and session_id:
        # fallback: load from disk only if no live instance given
        ...

Bug 4 — context_agent.py: Cache key doesn't include session_id
pythoncache_key = f"{user_text[:80]}:{len(messages)}"
Two different Telegram chats sending the same message with the same messages length will get each other's cached context. The cache key must include session_id.
Fix:
pythoncache_key = f"{session_id or ''}:{user_text[:80]}:{len(messages)}"

Bug 5 — context_agent.py: _build_conversation_text missing session_log parameter in the call signature
The extract() method receives session_log and passes it to _build_conversation_text:
pythonconversation_lines = self._build_conversation_text(
    messages, memory_store, session_id, user_text, session_log  # ← passed here
)
But _build_conversation_text's signature is:
pythondef _build_conversation_text(self, messages, memory_store, session_id, user_text):
    # ← no session_log parameter
So session_log is silently dropped. The method never receives it, falls into the re-instantiate-from-disk path (Bug 3).
Fix — add the parameter:
pythondef _build_conversation_text(self, messages, memory_store, session_id, user_text, session_log=None):

Bug 6 — telegram_bot.py: mem_context injected as system message BEFORE ContextAgent runs but AFTER messages list is passed
python# Inject relevant memories as context
mem_context = memory.format_memory_context(text, n=4)
if mem_context:
    sessions[chat_id].append({"role": "system", "content": mem_context})
# ... then hive.delegate() → orchestrator.run(text, sessions[chat_id])
The mem_context system message gets appended to sessions[chat_id] which is then passed to orchestrator.run() → _extract_clean_history() which skips system messages. So the memory injection is wasted. But worse — it bloats messages with system messages that confuse the session history and the compressed summaries.
Fix — either inject memory directly into the system prompt inside the orchestrator (already done via _inject_memory()), or remove the duplicate injection in telegram_bot.py.

Bug 7 — context_agent.py: _build_conversation_text signature mismatch from synthesize()
The legacy synthesize() method calls _call_llm() directly and works fine. But it should ideally be deprecated or clearly flagged since it bypasses SessionLog entirely — causing the "synthesize still used somewhere" silent failure if any old code path calls it.

Summary Table
#FileBugImpact1chat.pysession_log used before definedCrash on CLI startup2telegram_bot.pyset_session_id() called before SessionLog createdSessionLog never passed to orchestrator for new chats3context_agent.pyRe-creates SessionLog from disk, ignores passed instanceMisses in-flight messages, extra disk reads4context_agent.pyCache key missing session_idCross-chat context contamination5context_agent.py_build_conversation_text missing session_log paramSessionLog never used, always falls back to disk re-init6telegram_bot.pymem_context injected as system msg into historyWasted memory injection, pollutes history7context_agent.pysynthesize() legacy path bypasses SessionLogOld callers get zero session context
Bugs 1, 2, 3, 4, 5 are all connected — they form one chain that explains why context is still broken. Fix them in this order: 5 → 3 → 2 → 1 → 4 → 6.