# Personal memory, delivery, and consolidation

**Goal:** Durable personal and project memory without adding model calls to interactive turns.

**Architecture:** Atomic JSON profile storage and compact, directly available personal tools. Only explicitly pinned facts enter the system block (12 facts, 160 characters each); bounded local recall attaches transient candidates to each request without a model call. Journal completed interactive turns locally with project attribution; a tools-disabled model extracts structured facts from yesterday and older unprocessed transcripts in bounded background batches. Validate evidence and scope, persist progress, and expose unified recall. Deliver notifications through Telegram, configured HTTP service, desktop, then terminal; persist quiet-hour digests.

**Constraints:** No new dependencies. No regex intent router. No synchronous model work on chat turns. No automatic pinning of inferred memories. Use existing project memory operations. Configurable timezone, notification services, consolidation schedule and budgets. External content is data, not instructions.

- [x] Personal store/tool, bounded prompt integration, recall and persistence tests.
- [x] Notification transports, quiet-hour durable digests, daemon integration and fallback tests.
- [x] Turn journal, bounded model extraction, evidence/scope validation, restart-safe consolidation and daemon scheduling tests.
- [x] Document configuration and behavior; run full suite and local integration checks; review changes.

Validation: 288 automated tests; live gpt-4.1 checks for persistence, fresh-session pins, model consolidation, project decisions/todos, recall and replay; fresh-session food and hobby recommendations each requiring exactly one model request. Real local HTTP publishing and Windows notification API submission also passed. A 100-turn local benchmark with 1,000 facts measured 6.43 ms median and 9.35 ms p95 including retrieval, prompt refresh and journaling (model mocked only for this local measurement). Desktop display is controlled by OS notification settings; macOS/Linux commands are contract-tested rather than executed here.
