# GitHub issues #12, #4, #5 and #19

**Goal:** Fix desktop/server speech recognition and finish three additional fetched issues while preserving the simplified chat-log memory.

**User steering:** Pause #4, #5 and #19. Complete desktop/STT issue #12 first; preserve the other agents' existing edits without further integration.

**Plan:** Root owns shared local speech recognition, desktop microphone/VAD lifecycle, server STT routes, browser recording and voice diagnostics (#12). Independent agents own scoped filesystem tools (#4), calendar acceptance gaps (#5), and a twenty-task assistant evaluation/CI runner (#19). Shared main.py, builtin.py, README and environment configuration changes are integrated by root.

**Voice design:** Use the installed faster-whisper CPU model and sounddevice microphone capture, with bounded audio, clear errors, reusable serialized model loading, cancellation, interim/final transcript events and speech-activity interruption. One ZUMBA_STT_LANG setting reaches all clients. Hands-free listening and an optional explicitly configured activation phrase are user-controlled. Free-form command meaning is decided by the LLM interface, never hardcoded stop/exit cue lists.

**Constraints:** Preserve prior uncommitted memory work. Do not restore graph extraction or derived personal profiles. Tests isolate all data and external effects. No live email/calendar writes or GitHub issue messages. Inspect dependencies with Sonatype before declaring new requirements. Local six-second audio fixture validates real transcription without Chrome.

- [x] Reproduce #12 failures with tests, implement local voice, verify real offline fixture.
- [ ] Complete and test #4 file sandbox/kill-switch/access behavior.
- [ ] Complete and test #5 calendar gaps and setup guidance.
- [ ] Add #19 twenty-task eval, regression tests and CI.
- [ ] Integrate, review, run relevant backend tests and frontend build, and report exact limitations.

**#12 validation:** 21 tests passed with cached-model integration enabled, including Qt plus real Whisper in the isolated worker. After the final microphone-ready status change, the 20 ordinary tests passed again and mic_test.py independently transcribed the regenerated six-second fixture. Frontend production build passed. Default Realtek input supports 16 kHz mono. Windows line-ending-aware diff check passed. Live user speech, acoustic echo behavior and an actual cloud fallback call were not exercised. Remaining issue checkboxes are paused by user request.
