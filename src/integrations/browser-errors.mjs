// Fixed user-facing notices. Tool results retain diagnostics and recovery refs;
// status surfaces must never render page text, snapshots, stacks or call logs.
const NOTICES = Object.freeze({
  reference: { kind: 'reference', message: 'The page changed. Ankita can refresh its controls and continue.' },
  navigation: { kind: 'navigation', message: 'This page could not load. The browser is still available.' },
  connection: { kind: 'connection', message: 'The browser connection was lost. Reconnect to continue.' },
  setup: { kind: 'setup', message: 'The browser could not start. Check its setup in Plugins.' },
  preview: { kind: 'preview', message: 'The preview is catching up. The last frame is kept while it refreshes.' },
  action: { kind: 'action', message: 'That step could not finish. Ankita can inspect the page and continue.' },
});
const DEAD_CONNECTION = /connection closed|disconnected|server exited|not connected/i;
const NAVIGATION_FAILURE = /page\.goto|net::ERR_|navigation.*(?:failed|timed out)/i;
const SETUP_FAILURE = /Chromium could not start|Chromium is not downloaded|Playwright is missing/i;
const REFERENCE_FAILURE = /stale ref|unknown browser ref/i;

export function browserNotice(error, fallback = 'action') {
  const message = error instanceof Error ? error.message : String(error || '');
  const kind = error?.name === 'BrowserReferenceError' || REFERENCE_FAILURE.test(message) ? 'reference'
    : DEAD_CONNECTION.test(message) ? 'connection'
    : SETUP_FAILURE.test(message) ? 'setup'
    : NAVIGATION_FAILURE.test(message) ? 'navigation' : fallback;
  return NOTICES[kind] || NOTICES.action;
}

export function browserNeedsConnection(notice) {
  return notice?.kind === 'connection' || notice?.kind === 'setup';
}
