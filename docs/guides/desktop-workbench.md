# Main desktop workbench

The main window now follows the island's graphite surfaces, system typography,
mascot faces and compact controls. The desktop keeps its existing teammates,
tools, permissions, projects, plugins, scheduling and file readers.

## Layout and interaction

- The left rail switches between conversations, projects and plugins. Settings
  stays at its foot; the expanded roster includes search, names and reply previews.
- Smaller windows use a mascot rail with full names in accessible labels and
  tooltips. Teammate switching, creation and window controls remain available.
- The inset conversation surface separates identity from its project, scheduling
  and work-review strip. The transcript and composer share a bounded width.
- Empty chats show the teammate and three draft starters. These prepare text,
  append to an existing draft and focus the composer without sending a request.
- Work review, scheduled tasks and browser preview share the window's framing.
  They overlay at smaller sizes so the conversation keeps a usable width.
- Projects, apps and settings use the same typography and surfaces. Existing
  Graphite, Mono and Slate appearance settings remain available.
- Hover/press motion answers user actions. Saved teammate rows use static CSS
  faces; the selected canvas mascot retains real tool, capture and reader motion.
  Reduced motion remains effective. The Markdown memoization fix is preserved.

Run `npm run desktop:start` from the checkout to load the built renderer. In
development the existing Vite server can update the renderer directly. An
installed release does not automatically pick up these local source changes.

## Verification — 2026-10-05

The initial live regression failed with `0 !== 1` for the missing navigation
rail. After the redesign, the same script exercises the real App component.
It also reproduced a closed browser panel extending the document from **1024 px
to 1634 px**. Closed overlays now stay inside the viewport; the same assertion
passes at **1440, 1024, 800 and 640 px**.

The browser fixture dispatches production renderer events and uses isolated IPC
data. It checks draft preservation, starter actions, navigation selection, actual
Markdown, work-review diffs, compact controls, task drafting, helper setup,
appearance saves, browser preview dismissal and reduced motion. Native checks
use the production Electron modules with isolated configuration and a local model
fixture, including real filesystem tools and approval.

| Check | Result |
| --- | --- |
| Focused layout/draft/interaction tests | 8/8 passed |
| Desktop build | TypeScript passed; 365 modules built |
| Main workbench browser checks | 5 grouped checks passed; no page errors; 4 widths and 3 themes |
| Existing island browser checks | 10 grouped checks passed |
| Native Electron checks | 6 grouped checks passed; 3 provider requests and 2 real tools |
| Full serial suite | 931 tests: 930 passed, 1 skipped, 0 failed; exit 0 |
| Diff and new-file whitespace review | Passed |

Native screenshots and traces:
`C:\Users\anime\AppData\Local\Temp\ankita-companion-native-Ztr1ne`.
Island regression screenshots:
`C:\Users\anime\AppData\Local\Temp\ankita-island-ui-q5L4T2`.
Main workbench screenshots, including compact helper/jobs and all browser modes:
`C:\Users\anime\AppData\Local\Temp\ankita-workbench-EZQPIf`.

Full serial output:
`C:\Users\anime\AppData\Local\Temp\ankita-workbench-suite-09uPz5\serial-suite.log`
(`duration_ms 349925.7872`). Screenshots and test logs stay in temporary directories.
Browser preview checks exercise isolated,
Chrome and external modes with fixture IPC; website automation is not performed.

## Scope and review

Production sidebar width limits and the compose event live in
`desktop/shared/desktop-layout.mjs`. CSS sizing/motion tokens document their units;
color roles reuse the companion/theme palette. UI labels, icon paths, face
geometry and CSS presentation values are intentional display literals. Example
URLs, data, names, ports and screenshot widths exist only in verification fixtures.
No dependency or backend API was added. Existing worktree edits were retained.

Windows development Electron and Chromium are exercised. Installer/portable
packages, macOS/Linux native chrome, physical mixed-DPI monitors and the user's
ongoing provider workload are not covered by this pass. The browser preview
layout uses a fixture event; authenticated website interactions are outside this
visual redesign. Native drag transfer and helper installation remain covered as
described in [the companion guide](desktop-companion.md).

## Project, scheduling and preferences rework — 2026-10-05

The five supplied screenshots showed an unstyled scheduling action, dense project
records and sparse preferences. Projects now separate **Overview**, **Tasks** and
**Context** with keyboard-accessible tabs. The overview shows the real folder,
client, assignment and working rules. Tasks have an add form and completed-task
disclosure. Context has a multiline editor, note/decision filters, search and
dated previews that expand to show the complete record. Drafts stay with their
project while switching between projects; a failed save preserves the text.

Scheduled tasks now have one styled empty-state action, an owner mascot, readable
task names and a focused next-run/owner detail. Existing pause/resume, run/stop,
receipts and advanced settings remain available. Preferences separate the model
choice from optional limits and place saving in its own row. Background settings
show live scheduled/enabled/running counts and link each task to its owning chat,
including a missing owner's delivery conversation. Unroutable tasks are disabled.
Startup controls indicate unavailable capabilities and preserve the confirmed
value on a failed change. Pausing all tasks updates the actual shared job state.
The ordinary preferences flow no longer exposes CLI scheduler takeover commands.

The two follow-up screenshots showed hard rectangular focus outlines around the
composer and context textarea. The shared outlines were removed from desktop and
island controls; focused fields retain their ordinary subdued borders. Keyboard
navigation uses the controls' own surface/brightness feedback. CSS uses the
existing named motion tokens and theme colors. Navigation/press/record expansion
animations are finite and respect reduced motion; no idle timer or canvas loop
was added for these sections. Count labels use singular/plural copy.

### Reproduction and evidence

Before the section changes the real App fixture failed with
`projects need distinct overview, tasks and context sections: 0 !== 1`.
The baseline screenshot directory is
`C:\Users\anime\AppData\Local\Temp\ankita-workbench-PU2hGc`.
The same fixture now passes the new section/actions assertions. Focus regression
checks assert `outlineStyle === 'none'` and unchanged border colors before/after
focusing the composer, context editor and settings input in all three appearances.

| Check | Result |
| --- | --- |
| Project/settings/layout/scheduler focused tests | 56/56 passed; 0 failed |
| `verify-desktop-workbench.mjs` | 10 grouped checks passed; no page errors |
| `verify-desktop-workbench.mjs --focus-only` | Passed; all 3 themes, keyboard focus and unchanged focus borders |
| Native Electron round trip | 8 grouped checks passed; real project create/assign, task add/complete, context save and model-limit persistence |
| Existing island browser regression | 10 grouped checks passed |
| Desktop build | TypeScript passed; 365 modules; exit 0 |
| Full serial suite | 931 tests: 930 passed, 1 skipped, 0 failed; exit 0; duration_ms 341873.9957 |
| Diff/literal review | No whitespace errors; presentation values/copy are intentional; no new environment assumptions or dependencies |

Main section evidence:
`C:\Users\anime\AppData\Local\Temp\ankita-workbench-JvRLzx`.
Final focus screenshots:
`C:\Users\anime\AppData\Local\Temp\ankita-workbench-w2Wisg`.
Native project/settings evidence:
`C:\Users\anime\AppData\Local\Temp\ankita-companion-native-9ziWwd`.
Island regression evidence:
`C:\Users\anime\AppData\Local\Temp\ankita-island-ui-Vfo6wC`.
Full serial log:
`C:\Users\anime\AppData\Local\Temp\ankita-sections-suite-7iMEYa\serial-suite.log`.

The browser fixture exercises all nine settings layouts at 1280, 800 and 640 px;
the shell additionally covers 1440 and 1024 px. It saves model limits, submits
project forms, tests failure recovery, routes tasks to their owners and runs
pause/resume/run/stop actions using fixture IPC. The production Electron run
exercises actual storage and preload IPC in isolated configuration. It reads the
real startup capability but deliberately leaves OS login registration untouched;
startup changes and scheduled lifecycle button clicks use fixture IPC plus the
existing scheduler suite. Installed packages, macOS/Linux native chrome,
mixed-DPI monitors and authenticated provider/browser workloads remain uncovered.
No installer was published and the user's running app was not restarted.
The suite's single skip is the POSIX executable-permission test on Windows.

## v2.5.0 release verification — 2026-10-05

The release candidate passed a fresh serial run: **931 tests, 930 passed,
1 skipped, 0 failed**, exit 0 (`duration_ms 303276.9302`). The desktop build
passed TypeScript and built 365 renderer modules. The version in both package
files is 2.5.0; dependencies were not upgraded.

The Windows unpacked package was launched with isolated configuration through
`verify-desktop-companion-native.mjs --package-dir <package-folder>`. All nine
grouped checks passed: packaged version/resources; real read/write approval and
streaming; four-avatar island layout; authenticated capture delivery without
sending; real file ingestion and mouth animation; hide/show draft preservation;
helper pairing controls; persisted project/task/context operations; and model
limits, startup capability read and scheduled-task navigation.

The final focus-only browser regression also passed in all three themes: no
outlines or brightened borders on the composer, context editor or settings
fields, including keyboard focus. Evidence:
`C:\Users\anime\AppData\Local\Temp\ankita-workbench-IQQeXq`.

Serial output:
`C:\Users\anime\AppData\Local\Temp\ankita-250-release-suite-zCbDeh\serial-suite.log`.
Packaged native evidence:
`C:\Users\anime\AppData\Local\Temp\ankita-companion-native-nkC2pG`.
The local package used installed Electron with executable signing/editing
disabled for this diagnostic build. This validates the unpacked runtime and
helper resources, not installation, signing or Windows login registration.
Physical browser dragging, installed Google Chrome, macOS/Linux, mixed-DPI
monitors and the user's hosted-provider workload remain outside this check.
