# ANKITA desktop companion

The desktop companion follows Coucou's black top-edge notch, compact wake tab,
graphite focus cards, teammate avatars and animated character. The main desktop
shares its palette and shows the same character in the conversation header.
It uses ANKITA's existing teammates, threads, tools, approvals and scheduled jobs.

The redesigned main window is documented in [Main desktop workbench](desktop-workbench.md).

## Interaction

- Minimize or hide the desktop to reveal the companion. Hover its wake strip and
  click **Ankita** to open it. **Open desktop** restores the main window.
- **Overview** rolls new tools upward through two activity lines, fading and
  shrinking the previous step without a scrollbar. Full tool arguments and
  output stay available through **Open conversation**.
- The teammate area has no enclosing card or pill backgrounds. It shows up to
  four mascot-style avatars in two columns, with distinct expressions and tiny
  names. Hover and accessible labels expose the full name. Scheduled jobs
  remain live activities and never appear as teammates. Additional teammates
  remain available in the conversation selector and main desktop.
- **Ask** streams the same ANKITA conversation, renders completed replies as
  Markdown, and lets you expand tool arguments and results. Reasoning events
  stay separate from the answer. **Stop** cancels the selected turn.
- Attach files through the plus button or drag them onto the companion. It uses
  the desktop's image and document readers and keeps drafts per teammate.
  The selected mascot opens a large mouth, swallows a file thumbnail, chews
  while the actual reader runs, and bounces or shakes on the reader's result.
  The main desktop header accepts the same file drops. Switching teammates
  during a read retains the file and text draft under their original teammate.
  Reduced motion skips the swallow; leaving the target closes its hungry pose.
- Permission requests open automatically. Full command/diff details scroll
  while **Deny**, **Always allow**, and **Allow** remain visible. Failed IPC
  answers remain retryable. Keyboard Y/N works outside text fields.
- Sound controls persist locally. Motion follows the OS reduced-motion setting;
  hidden or tucked mascots pause rendering. The character reacts to real
  thinking, tools, searches, approvals, failures and completed turns.

Opening tabs or restoring/minimizing the main window retains the same companion
renderer, transcript and draft. Native bounds fit the current display and clamp
a remembered center that would otherwise place the window off-screen.

## Reference and implementation

The local Coucou reference was inspected in its `windows/src/island`,
`windows/src/core`, `windows/src/views` and `windows/src/mochi` implementations.
ANKITA's existing animation port was preserved and connected to the live engine.
Its character drawing and synthesized sound cues are ANKITA's own. The software
attribution is in `desktop/THIRD_PARTY_NOTICES.md`, included in desktop packages.

The shared `desktop/shared/island-state.mjs` reducer maintains independent live
threads and matches results by tool-call identity. `DesktopEngine.islandSnapshot`
provides saved history plus current streaming state and an event watermark.
The renderer subscribes before requesting that snapshot, then replays only newer
events so startup cannot duplicate an answer or lose an in-flight tool.

Sizes, history/output limits and animation durations are named constants with
units. Shared CSS tokens supply both window palettes. Tool/event identifiers,
UI copy, fixture values in verification scripts, and CSS dimensions are literal
values by design; no provider, port or user workspace is fixed in production.

## Verification record — 2026-10-04

Before implementation, `npm run desktop:build` reproduced TS2304 from accidental
text following `WorkspacePanel.tsx`'s props type. Removing only that stray text
restored compilation. Existing unrelated worktree changes were preserved.

The reducer tests first reproduced missing live-thread behavior (6 failing
tests), then passed. Additional regressions reproduced duplicate snapshot deltas
and an off-screen wide window before their fixes. The browser check also
reproduced `long approval details must scroll while the answer buttons stay
visible`; the bounded approval layout now passes the same assertion with a
multiline diff and with a real native `write_file` approval.
An additional startup-race check reproduced a live approval being erased by
an older pending-approval snapshot. Live requests now survive that snapshot,
and resolved requests cannot reappear from it.

The user's crowded-overview screenshots were reproduced with six teammates,
long names, a scheduled job owning a teammate thread, and long tool arguments.
The regression reported seven teammate entries, a scheduled-job name in the
teammate list, a single column, and tool rows overlapping the conversation action.
Filtering scheduled activities, capping the avatar grid at four, and reserving
the footer fixes the same fixture. A separate failing assertion reported
`overview tool history needs a rolling ticker instead of a scrollbar` before
the real tool feed was connected to the Coucou-derived ticker.

The rolling feed retains call identities and real running/completed/error states,
bounds rapid bursts, pauses while hidden, settles immediately for reduced motion,
and stops its animation-frame loop when idle. Browser checks sample intermediate
upward positions, then verify successful results, burst error states and complete
conversation output. The narrow expanded-window fixture also reproduced clipped
avatars; the responsive side-by-side layout now keeps all four avatars and the
conversation/stop controls visible. An initial fixture used the collapsed height
instead of the expanded preset; it was corrected before the narrow-layout repro.

| Check | Result |
| --- | --- |
| `node --test --test-concurrency=1` | 915 tests: 914 passed, 1 skipped, 0 failed |
| Focused island geometry, animation and state suites | 28/28 passed |
| `npm run desktop:build` | TypeScript passed; Vite built 354 modules |
| `node scripts/verify-desktop-island.mjs` | 10 grouped browser checks passed; no page errors |
| `node scripts/verify-desktop-companion-native.mjs` | 3 native checks passed: 3 provider requests, 2 real tools, approved file write, four avatars, bounded rolling overview, retained draft and integer bounds |
| `git diff --check` | Passed |

The browser script runs the actual renderer in Chromium with a stub IPC surface.
It exercises tools, Markdown, teammate drafts, attachment bytes, cancellation,
approval retry/Always allow, long approval details, persisted sound, reduced
motion, four distinct avatars, long names, scheduled-job exclusion, rolling/burst
activity, actual tool states and a narrow expanded overview. It saves screenshots
to a temporary artifact directory printed on completion.

The native script copies production runtime modules unchanged into a temporary
directory to exclude the checkout's `.env`. It launches the built Electron app
with isolated configuration and a loopback SSE provider, then reads a fixture,
waits for write permission, writes a new file, streams the final answer and
restores/minimizes the desktop. No paid provider or user thread is used.
It prints the temporary directory containing native screenshots and tool proof.

Latest layout evidence: browser screenshots are in
`C:\Users\anime\AppData\Local\Temp\ankita-island-ui-tHrboL`;
production Electron screenshots are in
`C:\Users\anime\AppData\Local\Temp\ankita-companion-native-sY8p5v`.
`crowded-overview.png`, `small-overview.png` and `native-overview.png` show the
final avatar grid and activity feed. These paths are local verification artifacts,
not production configuration.

## Webpage capture and responsiveness — 2026-10-05

The Chrome/Edge helper is in `desktop/browser-helper`. Restart the desktop after
this change to load its new main-process IPC. In the companion's Settings or the
desktop mascot's small Browser helper button, choose **Open helper folder**.
On the browser's Extensions page, enable Developer mode, choose **Load unpacked**,
and select that folder. Use **Copy pairing code**, then paste into the helper
popup. Pairing is one-time per browser profile. Browser store publication is not
part of this change.

Drag the selected mascot or a teammate avatar onto an ordinary HTTP/HTTPS
webpage. The page supplies landing motion and a delivery receipt. Its helper
extracts bounded document text; its service worker derives the source URL from
browser sender metadata and sends it through the authenticated loopback bridge.
The original teammate receives a plain reference attachment with title and URL.
The existing text draft is preserved and no model request is sent automatically.
An eight-file draft holds the capture in an inbox and retries after a slot is
freed. Draft typing and token streaming do not poll that inbox.

The bridge discovers its first port and remembers it. A remembered-port conflict
reports setup failure instead of silently binding elsewhere. Pairing credentials
are separate from expiring, single-use drag tickets. Cancellation, replay, stale
desktop instances, deleted teammates, website origins, forged credentials and
oversized/unreadable captures are rejected. Browser-internal pages, extension
stores, inaccessible frames and unreadable viewers cannot promise capture.
The desktop shows setup/delivery recovery text. The OS drag image is a canvas
snapshot; source/landing animations supply the motion around it.

A live transcript profile reproduced the reported hanging with 24 completed
Markdown replies and 30 streaming updates: mean React commit cost **300.12 ms**,
p95 **442.4 ms**. Every new token re-parsed all saved replies. Completed desktop
assistant content and island Markdown now use React memoization with their real
content/identity/streaming props, so changing a reply or teammate still updates it.
The final Chromium and Edge profiles reported mean **2.42 ms / 2.35 ms**,
p95 **4.2 ms / 3.6 ms**, respectively. This
measures renderer commit work, not total frame/paint or every user workload.
Existing filesystem inspection already runs in a worker; adding another process
would not address the demonstrated repeated Markdown parsing.

The swallow geometry check reproduced the shrinking file ending **26 px above
the mouth** in a taller companion window. The thumbnail now uses each surface's
mouth anchor and shrinks around its own center. The same live check passes for
both companion and desktop mascot sizes in Chromium and Edge.

The first full serial run reported **926 tests: 923 passed, 1 skipped, 2 failed**.
Both failures reproduced alone in Windows job fixtures with a five-second wait.
`scripts/diagnose-desktop-job-startup.mjs` observed native readiness at **5494 ms**,
first output at **6755 ms**, and correct completion at **7427 ms**; the largest
caller heartbeat gap was **93 ms**, rather than a multi-second caller stall.
The draining/status fixtures now wait for actual launcher readiness before their
command-observation window. Their unchanged output/exit assertions passed **2/2**.
Production shell launcher behavior and its timeout semantics were retained.

Current capture verification:

| Check | Result |
| --- | --- |
| Focused capture, draft, interaction, geometry, animation and state suites | 42/42 passed |
| Desktop build | TypeScript passed; Vite built 362 modules |
| Actual MV3 helper in Playwright Chromium | Popup pairing, visible DOM extraction, service-worker delivery, recipient attachment, no automatic send and browser/worker restart passed |
| Actual MV3 helper in installed Edge | Same helper/bridge/renderer/restart checks passed |
| Actual desktop and island file readers | Anticipation/swallow/reading, extracted bytes, rejected files, reduced motion, preserved drafts and target-leave passed |
| Full attachment draft | Holds one receipt; freeing a slot delivers and acknowledges it once |
| Built Electron round trip | 6 grouped checks passed: real tools/approval, bounded overview, capture IPC/inbox acknowledgement, header file reader, retained draft/bounds, visible pairing controls |
| Full serial suite after fixture correction and final pairing regressions | 929 tests: 928 passed, 1 skipped, 0 failed |
| Diff and new-module whitespace checks | Passed |

Evidence (temporary local verification artifacts):

- Original profile: `C:\Users\anime\AppData\Local\Temp\ankita-mascot-capture-jmgEzx`.
- Latest Chromium reader/capacity/profile/restart check: `C:\Users\anime\AppData\Local\Temp\ankita-mascot-capture-iPW9Gg`.
- Installed Edge: `C:\Users\anime\AppData\Local\Temp\ankita-mascot-capture-CZwSqf`.
- Built Electron: `C:\Users\anime\AppData\Local\Temp\ankita-companion-native-eCokN2`.
- Existing 10 grouped UI regressions: `C:\Users\anime\AppData\Local\Temp\ankita-island-ui-mynOm0`.

Cross-app native drag transfer is dispatched in the browser fixtures; content
scripts, worker, HTTP authentication and renderer ingestion are real. Physical
OS dragging, installed Google Chrome, installer assets, macOS and Linux have not
been exercised. Helper storage survives browser/service-worker restart in both
browser runs; desktop-restart pairing and legacy credential migration pass
real-HTTP unit checks. Same-origin Chrome/Edge helpers retain independent tokens;
remembered-port conflicts fail without rebinding. The packaged helper copy has
not been tested from an installed package. The user's actual ongoing app/provider
workload was not profiled, so this does not establish that every possible hang is
resolved. Previously changed workspace files and user processes were preserved.

Literal review: shared protocol constants own drag/event IDs, limits and deadlines;
configuration and runtime discovery own bridge paths/port; body-relative constants
own new canvas geometry. HTTP status numbers, UUID/extension-ID syntax, UI copy,
manifest schema/match patterns and CSS presentation values are intentional
protocol/display literals. Verification-only URLs, credentials, file contents,
counts and profiler budgets remain in tests/scripts.

The first native fixture failures were configuration issues: an undersized model
context and the checkout's `AUTO_APPROVE=on` overriding the fixture. An isolated
runtime and appropriately sized fixture context made the approval check valid.

The serial suite was rerun during the avatar/ticker changes: 914 passed, one POSIX
permission test skipped on Windows, zero failures. Final renderer changes were
checked with the desktop build and both live scripts; the focused suites also
passed 28/28.

## Remaining coverage

For v2.5.0, the Windows unpacked package also passed the nine grouped native
checks described in [the workbench release verification](desktop-workbench.md#v250-release-verification--2026-10-05).
This includes the bundled Chrome/Edge helper files in `resources/browser-helper`
and an actual packaged Electron runtime reporting version 2.5.0. Earlier notes
about untested packaged resources describe the development-only checks above;
installer execution and physical OS drag transfer remain untested locally.

- Windows development Electron was exercised. Packaged installer/portable,
  macOS native windows and physical multi-monitor/mixed-DPI changes were not
  exercised. The already-running user window could not be captured because the
  native computer-use connection was unavailable; the user's supplied screenshots
  provided the repro, and an isolated production Electron window provided the
  final live round trip.
- Browser attachment/cancel/retry checks use stub IPC; native read/write approval
  uses real IPC and tools with a fixture model rather than a hosted provider.
- Coucou's dedicated external-session, mail and note workflows are not imported.
  ANKITA's connected apps remain available through its existing tools and main
  desktop. This is an ANKITA companion integration, not every Coucou subsystem.
