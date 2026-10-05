# Companion capture implementation

Approved by the user's `proceed`; execute in this checkout without another approval gate.

1. Add tests for a pure mascot interaction timeline and a real HTTP capture bridge.
   Run `node --test --test-concurrency=1 test/desktop/mascot-interaction.test.mjs test/desktop/companion-capture.test.mjs` before implementing; retain the failure trace.
2. Add shared interaction/protocol modules. Implement bounded, authenticated loopback
   pairing, one-use teammate/surface tickets, persistent credentials, cancellation,
   capture inbox and acknowledgement. Integrate gated Electron IPC and shutdown.
3. Ship a Manifest V3 helper: isolated page drop listener, bounded DOM extraction,
   service-worker sender validation and bridge delivery, pairing popup. Include its
   unpacked assets in desktop packaging.
4. Add renderer capture/draft and file interaction hooks. Pin asynchronous reads to
   their original thread and preserve drafts. Extend the mascot engine with a large
   mouth and apply grab, swallow, chewing, result and reduced-motion poses. Connect
   island avatars, selected mascot, desktop header and real attachment readers.
5. Run focused regressions, real renderer file ingestion and extension/HTTP round
   trips, existing native fixture, full serial suite, desktop build and diff checks.
   Record evidence and uncovered physical drag/browser/package paths in the guide.

Interfaces: bridge `start/close/setup/register/cancel/inbox/ack`; shared protocol
defines limits, endpoints, drag MIME and renderer events. A ticket carries only
instance/ticket identity; helper credentials remain in extension storage. Incoming
captures become plain-text attachments, never an automatic model request.

Completed 2026-10-05: all five steps implemented and exercised. Initial new-path
tests failed 6/6 before implementation. Final focused checks pass 42/42, the full
serial suite passes 928 with one skip and zero failures, the desktop build passes,
and actual Chromium/Edge helpers plus built Electron round trips pass. Performance
profiling also reproduced and removed repeated saved-reply Markdown parsing.
See `docs/guides/desktop-companion.md` for trace counts, artifacts, setup and
remaining physical-drag/package/platform coverage. Existing workspace changes
were preserved; no dependencies, user processes or user conversations were changed.
