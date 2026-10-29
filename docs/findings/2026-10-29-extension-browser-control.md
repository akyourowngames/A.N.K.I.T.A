# Existing-profile browser control through Ankita's extension

Research date: 2026-10-29. Status: researched design proposal. The user clarified the desired outcome and left the transport choice to the builder. No runtime changes or extension installation performed.

## Requested experience

Install Ankita's extension, connect it once, and let Ankita use the existing signed-in browser without repeating the remote-debugging connection prompt. Keep browser tools available to both typed and spoken requests. This is separate from the voice work in PR #71.

### Confirmed pairing and restart requirement

The user explicitly confirmed that pairing is a one-time setup, independent of closing and reopening the desktop app. The connection must recover when both the paired browser profile and Ankita are available again.

- Desktop close, desktop restart, browser close, browser restart, extension service-worker suspension and temporary transport loss are disconnections, not revocations. They must not delete the saved pairing or open another pairing prompt.
- Persist the pairing identity and credential on both sides. Keep transport sessions and request IDs separate from that identity so a restarted process can authenticate with a fresh session using the existing grant.
- Support either startup order: browser before desktop, and desktop before browser. Reconnect automatically with bounded retry backoff; choose named timing settings during implementation. Avoid blocking desktop startup or repeatedly probing a closed browser on the main thread.
- Reconnect authenticates the existing grant; it does not expand site access, change action approvals, attach a debugger speculatively, switch browser profiles or replay an interrupted action. In-flight writes with unknown outcomes require a fresh observation before continuing.
- Explicit Disconnect pauses automatic reconnect until the user chooses Connect again, without requiring another pairing. Explicit Unpair/Revoke removes the saved grant and requires a new pairing. Label these actions distinctly.
- Removing the extension's saved data, losing desktop pairing data or choosing a different unpaired browser profile requires setup again. Show a clear recovery message instead of silently trusting a replacement profile.
- Acceptance requires one pairing followed by multiple complete desktop and browser restarts in both startup orders, plus an extension-worker restart. No extra pairing dialog may appear. Also test revocation and prove that it prevents automatic reconnect.

## What the sources establish

- [OpenAI's browser extension guide](https://learn.chatgpt.com/docs/chrome-extension) describes extension installation, browser permission acceptance, and remembered website access. It offers an explicit allow-for-all-sites choice. It does not publish enough implementation detail to establish how its transport works or promise that Chrome never shows a debugger notice.
- [Chrome's debugger API](https://developer.chrome.com/docs/extensions/reference/api/debugger) provides a transport for supported DevTools Protocol domains through an extension, without requiring a remote-debugging port. It requires the debugger permission. It is not equivalent to unrestricted browser-level CDP access.
- [Current Chromium implementation](https://github.com/chromium/chromium/blob/main/chrome/browser/extensions/api/debugger/debugger_api.cc) creates a browser warning when an ordinary extension attaches. Cancelling the warning detaches its control sessions. Source inspection establishes the mechanism; it is not an end-to-end observation on the user's installed Chrome version.
- [Chrome's scripting API](https://developer.chrome.com/docs/extensions/reference/api/scripting) supports packaged content code and serialized functions, with scripting and matching site permissions. Ordinary DOM interactions can use this path without attaching a debugger. A synthetic DOM click is not a trusted input event and must not be presented as universally equivalent.
- [Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging?hl=en) connects an extension to a registered local host. The desktop installer must register that host, including allowed extension origins. Installing an extension alone does not install a native desktop host.
- [Microsoft Playwright's extension](https://github.com/microsoft/playwright/blob/main/packages/extension/README.md) connects to an existing browser profile. It supports a profile-specific authentication token to remove its own repeated connection approval dialog. This does not establish that Chrome's debugger notice disappears.
- [Microsoft Amplifier Browser Bridge](https://github.com/microsoft/amplifier-browser-bridge) uses injected page actions first and describes selective debugger escalation. Its [banner analysis](https://github.com/microsoft/amplifier-browser-bridge/blob/main/docs/DEBUGGER_BANNER.md) explicitly says its CDP path has not been tested end to end against real Edge. Use it as an architectural reference, not proof of production readiness or timings.
- [Chrome's remote-debugging changes](https://developer.chrome.com/blog/remote-debugging-port) require a non-default data directory for remote-debugging switches from Chrome 136. That launch-flags route does not deliver the requested existing-profile experience.

## Current Ankita code

- `src/integrations/browser-plugins.mjs`: the existing `active` connection builds a Chrome DevTools MCP command with `--autoConnect`.
- `desktop/renderer/src/components/BrowserPluginsSection.tsx`: My session tells users to enable remote debugging and says Chrome asks each time.
- `desktop/browser-helper/`: existing page-capture extension with authenticated, one-time pairing to `desktop/electron/companion-capture.mjs`. It has no browser-command receiver or debugger permission. Capture pairing must not silently become permission to control pages.
- `desktop/chatgpt-companion/`: a separate ChatGPT model-provider bridge. Its sign-in and cookie-transfer grants must retain their current meaning.
- `tools/browser/session.mjs`: common browser policies, cancellation, operation receipts, per-job ownership and coordination. Preserve these when adding a transport.

## Recommended design

Use normal extension control first, with deeper debugger access only when the operation requires it. The alternative is debugger control throughout: simpler capability parity, but Chrome's notice remains while attached. Asked about this fork under AGENTS.md section 4.4, the user answered that they do not know the internals and want their observed ChatGPT experience: posting and filling forms without repeated permission prompts. DOM-first is the builder's recommendation for that outcome, not a claim that the user selected an implementation technology.

Distinguish connection approval, website access, action approval and Chrome's own debugger notice. A user-requested post or form submission should not trigger an additional connection approval on each action after pairing. Retain the existing action policy and auto-approval preference, without inventing another extension confirmation layer or interpreting permission in webpage text as a user instruction. Remembered website access should be selectable once in setup, including all supported websites when the user chooses it; blocked sites still win.

1. Extend the existing browser helper into the general Ankita browser companion. Keep capture and browser-control grants distinct. Do not broaden the ChatGPT provider bridge as a shortcut.
2. Put browser commands behind an external MCP service and the existing browser tool contract. Connection transport does not grant new websites or change action approvals. Browser access works for typed and voice jobs alike.
3. Let the desktop installer register a native messaging host for the supported browser and the actual extension identity. Development setup needs an explicit registration command; packaged setup must not depend on a globally installed Node binary. Detect paths and browser availability at runtime.
4. Establish an authenticated local session after one-time user pairing. Persist the control grant privately, reconnect automatically, and expose Disconnect/Revoke in the extension and desktop settings. Do not turn existing capture credentials into browser-control credentials. Reject an unknown extension identity, stale pairing and untrusted webpage messages.
5. Route ordinary tab and DOM operations through packaged extension code. Keep observed element references scoped to document, frame, tab and job; invalidate them on navigation. Return observed results through the existing receipts, not guessed completion text.
6. Use the debugger for operations needing trusted input, Chrome's page accessibility tree, background screenshots, supported page JavaScript dialogs or another supported deeper capability. This does not imply access to operating-system accessibility controls. Define capabilities explicitly. Do not retry a mutating action through a second path after an uncertain result: observe first so a click or submission cannot happen twice.
7. Attach only to the job's selected tabs and detach on completion or idle. Choose an idle limit as a named setting after measuring attachment cost. Treat Chrome's Cancel as a control revocation for the affected session, not a reason to immediately reattach.
8. Keep independent jobs in separate owned tabs. Coordinate operations that share a tab; one job must not switch another job's target or reuse its references. Browser settings list paired profiles so discovery cannot attach an arbitrary profile.
9. Show Connected / Browser closed / Access removed / Another debugger is attached with actionable recovery. One-time setup replaces manual port configuration. Chrome-owned notices remain visible whenever Chrome requires them.

Builder choices proposed here, not yet agreed with the user: reuse the browser helper, use native messaging for discovery, retain the external MCP boundary, and preserve existing browser policy rather than adding another planner tool family. Host registration and browser-extension store publication are separate deliverables; the repository does not currently have the requested install-and-control flow.

## Required verification before calling it shipped

- Reproduce the current active-session prompt and capture a connection trace on an installed browser.
- Add focused regressions for one-time pairing, authenticated reconnect, revoked access, unknown origin, duplicate/stale replies, disconnect during writes, extension worker restart and profile selection.
- Run actual extension/native-host round trips: open, read, click, type, navigate, screenshot and disconnect. Compare ordinary page actions and actions requiring deeper control.
- Exercise cross-origin frames, navigation during an operation and pages rejecting synthetic input; report unsupported browser/extension pages honestly.
- Run two jobs in separate tabs, then attempts to touch the same tab. Confirm isolation and no duplicate writes after cancellation or lost responses.
- Verify Chrome Cancel blocks the affected session and does not cause repeated automatic attachment.
- Verify packaged host registration and upgrade/removal on every platform claimed as supported. A development-only test does not prove installation works for users.
- Keep the checks focused; no broad suite or release is implied by this research.

## Verification boundary

This document is based on live source/document reads and inspection of current Ankita source. No browser-control runtime has been changed, no physical connection prompt has been reproduced in this research pass, and neither transport has been live-tested here. The cited third-party code is evidence of an approach, not a dependency approved for installation or a tested implementation for Ankita.

An independent builder review found no blocking questions before implementation planning. Its terminology corrections about page accessibility and JavaScript dialogs are incorporated above. Referenced repository paths were checked as present; the document has no trailing whitespace. These checks validate the research handoff only, not browser operation.
