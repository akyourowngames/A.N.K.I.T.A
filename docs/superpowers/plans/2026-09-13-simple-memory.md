# Simple memory implementation plan

**Goal:** Replace automatic graph memory with Jarvis-style saved conversation history and erase the old local memories and traces.

**Design:** Keep a bounded JSON chat log containing original user/assistant messages. Save synchronously with an atomic replacement; read recent exchanges in chronological order. No semantic extraction, profiles, embedding search, background consolidation or session reflection. Existing session storage continues to support resume and tool continuity. Explicit document and task tools remain separate from automatic chat memory.

**Constraints:** No keyword or regex semantic classifiers; no new dependencies; preserve credentials and integrations. Reset must remove old memory queues, graph copies, session contents, generated profiles and audit artifacts without replaying Telegram updates. The reset outside the workspace requires filesystem escalation.

- [x] Add regression tests for plain history, restart persistence, bounds, concurrent saves, clear, and exclusion of old graph/profile data.
- [x] Replace memory orchestration and automatic recall; remove background profile/sync/reflection and summary generation from chat.
- [x] Update CLI, API and memory UI to describe plain chat history accurately.
- [x] Prepare and test a scoped reset script; run backend and frontend checks.
- [x] Execute the requested data wipe and verify all targeted stores are empty or absent.

Validation: 90 focused backend/integration tests passed; the frontend production build passed. A broader suite attempt encountered the existing native ONNX runtime access violation in legacy embedding tests. The new chat-memory path does not load ONNX.

Reset: removed 699 messages, 48 sessions, 48 execution runs, 460 execution events, channel mappings/seen rows, legacy memory/inbox/vault indexes, graph copies, generated profiles, audit logs, cached audio/web data and legacy session files. Deleted 33 test-artifact directories using the sandbox identity that owned them. Verified zero rows in all conversation/execution/location tables and zero messages in the new chat log.
