# Companion mascot interactions and webpage capture

Status: approved by the user's `proceed`; implemented in the checkout. Live
Chromium/Edge and built Electron verification is recorded in the companion guide.

## Outcome

Keep ANKITA's current black companion, four teammate avatars and rolling tool
feed. Make its mascots playful interaction targets that perform real extraction.
The user selected a Chrome/Edge helper for normal browser tabs instead of limiting
webpage drops to the existing ANKITA browser connection.

Dragging an avatar identifies that teammate. File drops and captured webpages
belong to that teammate even if the user selects another agent during extraction.
Extraction prepares context in the teammate's conversation; it does not silently
submit the user's existing draft. Full results remain available as attachments.

## Visible behavior

- Selecting a teammate gives its avatar a small spring, blink and focus response.
  Its color and identity also appear on the main companion mascot.
- Grabbing an avatar stretches it slightly and gives the grab transition a short
  sparkle trail. A canvas snapshot of that mascot follows the native drag cursor
  outside the desktop window; the webpage capture target supplies landing motion.
- A normal webpage recognizes that mascot drag and shows a discreet capture
  target. Dropping captures its title, URL and readable document content, including
  content already rendered in a signed-in tab. The helper acknowledges capture;
  ANKITA opens the recipient's conversation with the extracted page attachment.
- Bringing files toward the companion turns the mascot toward the cursor and
  opens a comically large mouth. Dropping pulls a file thumbnail into the mouth,
  squashes the body, closes the mouth and chews. The existing document/image
  reader runs immediately alongside the animation.
- While extraction runs, the mascot waits attentively. Success produces a happy
  bounce and the real attachment chip; rejected files get a brief surprised
  shake and an actionable error. Multiple files show their actual count.
- Hover peeks, eye tracking, selection squishes, successful attachment reveals,
  drag cancellation and a return-to-rest spring supply the smaller interactions.
  Reduced motion replaces choreography with immediate state changes. Hidden
  windows stop animation work; timers and pending effects clean up on unmount.

The swallow follows Coucou's existing upload sequence, adapted to the mascot's
actual bounds rather than copying its fixed reference window dimensions. Palette,
typography, controls, teammate cap and the current panel layout stay intact.
Extraction progress reflects the reader's actual state; animation does not invent
completion or percentage progress.

## Browser helper and desktop bridge

Ship a small Manifest V3 helper for Chrome and Edge. One-time setup loads the
helper, pairs it with ANKITA and grants webpage access. Include a local development
bundle and desktop setup instructions; store publication is outside this change.

The content script receives only ANKITA mascot drops and reads bounded content
from its document. Its service worker validates the source URL/tab against
browser-supplied sender metadata and sends the capture to the paired desktop bridge. Normal
browser/file drags retain their existing behavior. No whole-browser browsing
history or unrelated tabs are collected.

The bridge runs in the Electron main process and binds only to loopback. The OS
allocates its first port; configuration remembers the address across restarts.
If that address is unavailable, expose a reconnect/setup state instead of sending
context to a different service. Pairing creates per-helper credentials. Capture
requests authenticate that helper and consume an expiring, single-use drag ticket
bound to the original teammate and desktop instance. Credentials never travel in
the webpage drag payload. Cancellation, duplicate delivery, expired tickets and
deleted teammates produce no draft mutation.

Pass page context through the existing attachment contract as bounded plain text
with its title and source URL. Preserve page content as untrusted reference data.
Reuse the existing file types, extraction logic, byte limits and attachment cap.
An unavailable helper or extraction failure shows a recoverable status and leaves
the user's draft intact. Browser-internal pages, stores, inaccessible frames and
unreadable viewer documents cannot promise capture; explain that in helper setup
and show a recoverable companion status when a drop does not yield a receipt.

## Code boundaries

- Extend `Mascot.tsx` and the canvas engine with a cancellable interaction state
  for grab, anticipation, suction, chew, result and return-to-rest.
- Connect island/avatar drag and drop handlers and selected-agent routing in
  `Island.tsx`, `Overview.tsx` and `useIslandChat.ts`. Reuse `Composer.readFile`;
  wire the same file feedback into the main desktop where its mascot is shown.
- Keep the authenticated capture service in a dedicated Electron module. Add
  narrow preload/IPC contracts and capture-ready/error events, then feed the
  recipient's existing draft/attachment path.
- Keep the browser helper separate from the tool browser adapters. It identifies
  a physical webpage drop without changing Playwright/Chrome automation behavior.
- Share timing, geometry ratios, limits and protocol constants with comments
  stating their units and purpose. Include helper assets in the desktop package
  and preserve Coucou software attribution. Add no runtime dependency unless a
  demonstrated requirement cannot be met with existing APIs.

## Acceptance and verification

Before implementation, animation/state/document/attachment baseline suites passed
42/42 (`node --test --test-concurrency=1` with the four focused test files).

New regression coverage must demonstrate:

1. A dropped file opens the mouth, is consumed once, produces actual extracted
   content, and never moves to a teammate selected later.
2. Failed/oversized/multiple-file drops, drag-leave, Escape/cancellation and
   reduced motion leave consistent mascot and draft states.
3. A mascot dropped on a fixture webpage captures that exact page's text, title
   and URL into the original teammate's draft through the real helper/bridge.
4. Unpaired, forged, replayed, expired, wrong-instance and deleted-teammate
   captures are rejected; normal webpage drags are unaffected.
5. Pairing/reconnection, desktop restart, service-worker restart and concurrent
   agent captures retain correct identity and attachment limits.
6. The existing overview/chat/approval/native round trips stay green.

Run focused tests, live renderer/file extraction, a real extension/bridge round
trip, built Electron verification, the full serial suite, desktop build and diff
checks. Exercise Chrome and Edge where available; distinguish genuine extension
runs from stub-driven API tests. Document physical cross-app drag, packaging,
platform or browser branches that cannot be exercised in this environment.

## API references

- [Chrome content scripts](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts)
  provide page DOM access and messaging from an isolated extension context.
- [Extension network requests](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests)
  belong in the service worker with the required host permissions.
- [Microsoft Edge extension compatibility](https://learn.microsoft.com/en-us/microsoft-edge/extensions/developer-guide/port-chrome-extension)
  supports sharing Chrome-compatible extension code, with separate Edge testing.
- [Electron native drag documentation](https://www.electronjs.org/docs/latest/tutorial/native-file-drag-drop)
  describes exporting native file drags; it does not provide the receiving
  webpage identity needed by this capture interaction.
