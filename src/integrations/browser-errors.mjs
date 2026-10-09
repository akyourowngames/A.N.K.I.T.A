// Fixed user-facing notices. Tool results retain diagnostics and recovery refs;
// status surfaces must never render page text, snapshots, stacks or call logs.
const NOTICES = Object.freeze({
  reference: { kind: 'reference', message: 'Ankita could not locate the requested control. It can refresh its view and continue.' },
  navigation: { kind: 'navigation', message: 'This page could not load. The browser is still available.' },
  connection: { kind: 'connection', message: 'The browser connection was lost. Reconnect to continue.' },
  setup: { kind: 'setup', message: 'The browser could not start. Check its setup in Plugins.' },
  preview: { kind: 'preview', message: 'The preview is catching up. The last frame is kept while it refreshes.' },
  action: { kind: 'action', message: 'That step could not finish. Ankita can inspect the page and continue.' },
  denied: { kind: 'denied', message: 'This site refused the browser request. Try Chrome local or take control.' },
  login: { kind: 'login', message: 'Sign-in needs attention. Use the secure sign-in card or take control.' },
});
const DEAD_CONNECTION = /connection closed|disconnected|server exited|not connected/i;
const NAVIGATION_FAILURE = /page\.goto|net::ERR_|navigation.*(?:failed|timed out)/i;
const SETUP_FAILURE = /Chromium could not start|Chromium is not downloaded|Playwright is missing/i;
const REFERENCE_FAILURE = /stale ref|unknown browser ref/i;
const DENIED_NAVIGATION = /Navigation refused: HTTP/i; // Adapter-owned HTTP failure, never page content.
const RECOVERABLE_NOTICES = new Set(['reference', 'preview']); // Refreshable observations need no user intervention or lost-connection warning.

export function browserNotice(error, fallback = 'action') {
  const message = error instanceof Error ? error.message : String(error || '');
  const kind = error?.name === 'BrowserReferenceError' || REFERENCE_FAILURE.test(message) ? 'reference'
    : DEAD_CONNECTION.test(message) ? 'connection'
    : SETUP_FAILURE.test(message) ? 'setup'
    : DENIED_NAVIGATION.test(message) ? 'denied'
    : NAVIGATION_FAILURE.test(message) ? 'navigation' : fallback;
  return NOTICES[kind] || NOTICES.action;
}

export function browserNeedsConnection(notice) {
  return notice?.kind === 'connection' || notice?.kind === 'setup';
}

export function browserPageFailed(notice) {
  return notice?.kind === 'navigation' || notice?.kind === 'denied';
}

export function browserNoticeIsRecoverable(notice) { return RECOVERABLE_NOTICES.has(notice?.kind); }
