# Voice tool execution repair — 29 October 2026

## Desktop audio and settings follow-up

Owner report: End during startup logged `AbortError: Voice ended` through
`engine:invoke`; speech was generated but inaudible; settings fields were cramped
and inconsistent. The startup reproduction failed with that same stack before
the fix, then resolved for both concurrent start callers after End. Prewarm
cancellation is covered separately; genuine device errors and unexpected
AbortError while still live remain public errors.

Local audio diagnosis found four active Windows outputs. Default playback was
Airdopes Stereo, while the saved microphone was the laptop Realtek array.
Outputs were unmuted. Real Sarvam/ffplay playback through Airdopes Hands-Free
exited 0 but the owner heard nothing. The laptop output test was explicitly
confirmed audible by the owner. This narrows the fault to output/headset routing;
it does not prove that the headset path is repaired. No headset-specific default
is baked into production code.

Changes: discovered Windows speaker selection in private desktop settings;
Test speakers uses saved config, real Sarvam and strict existing MP3 playback,
creates no task, and restores routing on success/failure/cancellation. Startup
and test cannot compete for the audio owner. The renderer reuses existing
Preferences form styles, theme tokens and save actions. Keys remain blank presence
indicators in public views. Device choices lock during voice; voice-state events
unlock them if voice ends from the island, with revision ordering protecting
against a slow status response. A normal player exit is described as a played
test, never as proof that it was heard.

Review found two Important issues and one related error-path gap: single-default
restore could overwrite a distinct call output; a mount-only settings snapshot
could leave controls locked; a broad AbortError guard could hide a real audio
failure. All are addressed. Output helpers now snapshot console/multimedia/call
roles and restore only roles still owned by voice; failed partial switches roll
back, later manual changes survive, and unplugging a previous output cannot break
End. HFP automatic routing shares this helper. The stale-settings browser check
failed before the event fix, and the unexpected-AbortError regression timed out
before the guard fix; both then passed. Fresh re-review reports no remaining
Critical/Important findings; its independent voice/output check passed 37/37.

Final focused verification (full suite deliberately not run, as requested):

- `node --test --test-concurrency=1 test/channels/audio-device.test.mjs test/channels/voice.test.mjs test/channels/voice-playback.test.mjs test/desktop/voice.test.mjs test/desktop/voice-engine.test.mjs test/desktop/voice-state.test.mjs test/desktop/voice-ui.test.mjs test/desktop/desktop-settings.test.mjs`
  — **121 tests, 121 pass, 0 fail, 0 skip**, 9976.6462ms.
- `npm run desktop:build` — typecheck clean, **403 modules**, exit 0.
- `node scripts/verify-desktop-voice-ui.mjs --settings-only` —
  `VOICE_SETTINGS_UI_OK: styled fields; saved output; honest test receipt; 1280/620/390px; zero renderer errors`.
  Screenshots were visually inspected. One intermediate fixture run overlapped
  an unfinished build and failed serving changing assets; rerun after the completed
  build passed. No production change was made for that harness race.
- Live revised `runVoiceAction` → `DesktopVoice.testPlayback` → Sarvam → ffplay,
  temporarily seeding a distinct real Windows call output, returned
  `DESKTOP_VOICE_AUDIO_OK {"output":"Speakers/Headphones (Realtek Audio)","cancelled":false,"allOutputRolesRestored":true,"distinctCallOutputPreserved":true}`.
  All original output roles were restored in cleanup. An attempted persisted
  speaker preference was later observed blank while the older app was still
  running; final live verification used an isolated config override and did not
  fight the running app's settings. Select and save the working speaker after
  restarting desktop dev so the updated controller owns settings.

Limits: live Node action/audio path and browser renderer fixture, not a fresh
packaged-app acceptance run; no physical headset duplex claim; no new full-project
suite. Main-process changes require restarting desktop dev. No release or merge.

## Scope and evidence

The owner requested a new polish PR after PR70, starting with skipped tools and
false music-playback claims across all tool families. Two retained voice records
claimed YouTube playback with no steps. A live Muse first-decision probe for
“Can you play me some Haryana?” returned suggestions and no calls despite a
visible find_tools schema and browser catalogue. A more explicit YouTube request
selected discovery. This is planner execution avoidance plus an unchecked final
response, not evidence of a missing browser installation.

## Design

Keep the existing agent and progressive discovery. Copy the captured conversation's
activated tool groups into each independent voice worker, without sharing mutable
sets or inheriting tool focus. All connected MCP capabilities remain discoverable.
Before final voice text becomes visible or audible, run a compact evidence check
with the same active planner and its actual requested/started/result receipts.
The checker returns ANSWER, COMPLETE, CONTINUE or BLOCKED as plain text; it uses
neither JSON mode nor a trigger-word list. COMPLETE without successful substantive
execution is refused even if the checker mistakenly approves it. An unsupported
draft gets one in-turn correction, preserving completed actions; another stops
honestly. A check failure cannot silently approve the draft. Typed chat is unchanged.
Usage and request sizes include the extra check. This adds one compact model call
per candidate final response, including normal chat; it is not zero-cost latency.

A private terminal-result tool was tried first, but two real Muse runs repeatedly
ignored it, taking 22 and 9 rounds and failing despite actual playback. That
approach was removed before review. The final design keeps the existing reply
format and checks its evidence separately, rather than depending on an unsupported
forced tool choice. Meta's tool-calling docs currently require auto choice:
https://dev.meta.ai/docs/tool-calling

Tool receipts prove execution, not every possible natural-language assertion.
The semantic checker can still misjudge an ANSWER or incomplete work. Bounded
context can omit older evidence. Site autoplay/ads/login, actual YouTube playback
and physical audibility remain separate acceptance risks.

## Implementation and checks

- [x] Reproduce with the real provider and save the before trace above.
- [x] Add failing integration cases for skipped-tool replies, bounded correction,
      real file receipts, discovery-only/denied receipts, check failure, chat overhead,
      typed-chat isolation, loaded built-in/MCP tool visibility and control capacity.
- [x] Add src/core/voice-completion.mjs and the minimal host response-policy hooks
      in src/core/agent.mjs; register and observe it in src/core/voice-worker.mjs.
- [x] Run the regression cases RED then GREEN; run affected suites and full npm test.
- [x] Exercise the live planner with browser and file tools. Use disposable profiles
      and a local media fixture for observed playback; distinguish that from YouTube.
- [x] Update the guide/changelog and this record with exact evidence and limits.
- [x] Review the diff, push a fresh branch and open a new PR; no merge or release.


## Verification and review log

- Baseline voice worker/tool/empty-recovery checks: **18/18 pass**.
- Initial unsupported-ending/discovery tests: **7 fail, 1 pass** against the old
  runtime. A file remained missing and a no-action playback claim was marked done.
- Final new regression file: **15/15 pass**, 1460.3435ms. Covers same-turn recovery
  without duplicate writes, deterministic no-action/discovery/denial rejection,
  malformed check, usage accounting, budgets, chat/typed separation, cancellation
  and inherited built-in/MCP discovery.
- One fresh review found two Important issues. Three targeted regressions failed
  before the fixes, then passed: unchecked candidate suffix, oversized original
  request and cancellation during token preparation. Full candidates are now
  checked or corrected; oversized requests fail safely. The deadline/cancellation
  race covers authentication too. Result/context truncation is explicit and the
  compact evidence input has a total byte bound. No Critical/Minor findings.
- Real default script passed both browser backends, file/read-back and chat on the
  revised design before final review hardening. Measured checker overhead was
  **1285ms isolated / 2632ms Chrome / 1060ms file / 1123ms conversation** in that
  sample, separate from the planner/tool latency. Final hardened rerun is below.
- Optional real YouTube attempt did use browser discovery, navigation, search,
  fresh refs and a playlist click. The video had paused=false, readyState=4,
  currentTime=5.99002, but adShowing=true. Its independent requested-track assertion
  therefore **failed**. The planner/checker accepted a report saying the playlist
  was loaded and should autoplay. This remains a concrete semantic limitation:
  opening/playing an ad does not prove the requested song has begun. Do not call
  this a clean YouTube-music acceptance take. Physical audio was not checked.
- The initial zero-action stored claims are not modified by this repair.
  Original-checkout uncommitted speed/provider changes and personal text files
  are outside this PR. No package version bump, merge or release is requested.

- Final hardened real-service rerun: **4/4 tasks done**, both browser backends
  dispatched the Play control and read back Playback running, poem write/read-back
  succeeded, and conversation had no work steps. Isolated: 5 planner rounds,
  8593ms total /1457ms check; Chrome: 4 rounds, 13449ms /1881ms check; file: 3 rounds,
  6658ms /1537ms check; chat: 1 generation plus check, 2091ms /976ms check.
  Output marker: VOICE_TOOL_EXECUTION_LIVE_OK browserBackends=2
  fileReadback=true chat=true physicalAudio=false youtube=false.
- Desktop typecheck/build passed: **403 modules**, Vite 8.45s. Changed-doc local
  links: **36 resolved**. Whitespace check passed.

- A final emission-order check caught approved-but-invalid printed tool markup
  leaking before the existing protocol corrector ran. Its regression failed
  first, then passed after emission moved behind that corrector. Final new file:
  **16/16 pass**. Final focused worker/completion/report/empty-recovery set is
  recorded with the completed verification below. This adjustment and named
  protocol constants followed the broad run's earlier core-test phase; focused
  checks exercise those final changes separately.

- Broad serial project run: **1752 tests, 1751 pass, 0 fail, 1 skip**,
  0 cancelled, 834436.3209ms. The npm test child exit was independently observed
  as **0**; the logging wrapper then hit a Windows stdout Unicode encoding error
  while printing its tail. The test log and child-exit receipt confirm the actual
  test outcome. The existing skip requires POSIX executable permission modes.
- Latest focused completion/worker/private-tools/empty-recovery/report-control
  checks: **48/48 pass**, 0 fail/skip/cancelled, 7739.5898ms. Includes **17** new
  completion cases. The final control-compatibility regression failed first, then
  passed: an actual private voice control result can satisfy a request even if
  the checker labels it COMPLETE rather than ANSWER. Bookkeeping/discovery alone
  still cannot prove execution. This and the final emission-order case were run
  after the broad suite's core phase, so the full count does not include these
  last two added regression cases.
- All changed production literals were inspected. Thresholds, correction prompts,
  error kind and the wire endpoint route are named constants; roles, event names,
  HTTP verb and response keys are transport protocol fields. No environment,
  account path, model or site URL is introduced into production defaults.


Integration receipt: [PR #71](https://github.com/akyourowngames/A.N.K.I.T.A/pull/71)
opened for review on branch `fix/voice-tool-execution`, based on merged PR70.
Implementation commit: `9933a4b`. No merge, version change, tag or release performed.
