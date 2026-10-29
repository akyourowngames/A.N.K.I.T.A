import { ROUTES, HELPER_MESSAGE, REQUEST_TIMEOUT_MS, LOOPBACK_HOST, MAX_URL_CHARS, isPageUrl } from './protocol.mjs';
import { BrowserConnection } from './connection.mjs';
import { ExtensionBrowserOperations } from './browser-operations.mjs';
import { CONTROL_SESSION_KEY as SESSION_KEY, CONTROL_MESSAGES, CONTROL_ROUTES, CONTROL_REQUEST_MS, CONTROL_ALARM, CONTROL_ALARM_MINUTES } from './control-protocol.mjs';
function addressFrom(value) {
  const url = new URL(value);
  if (url.protocol !== 'http:' || url.hostname !== LOOPBACK_HOST || !url.port || url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw new Error('Copy the pairing code from ANKITA');
  return url.origin;
}
async function post(address, route, body, token, signal, timeout = REQUEST_TIMEOUT_MS) {
  const response = await fetch(address + route, { method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) }, body: JSON.stringify(body), signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(timeout)]) : AbortSignal.timeout(timeout) });
  const result = await response.json();
  if (!response.ok) throw Object.assign(new Error(result.error || 'ANKITA could not receive this page'), { status: response.status, code: result.code });
  return result;
}
const load = async () => (await chrome.storage.local.get(SESSION_KEY))[SESSION_KEY];
const save = session => chrome.storage.local.set({ [SESSION_KEY]: session });
const executor = new ExtensionBrowserOperations();
const connection = new BrowserConnection({ load, save,
  post: (session, route, body, signal) => post(addressFrom(session.address), route, body, session.token, signal, CONTROL_REQUEST_MS),
  execute: (operation, signal, beforeDispatch) => executor.execute(operation, signal, beforeDispatch),
  onResume: () => executor.allowDebugger(),
});
const wake = () => { void connection.wake(); };
chrome.runtime.onStartup.addListener(wake);
chrome.runtime.onInstalled.addListener(wake);
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === CONTROL_ALARM) wake(); });
void chrome.alarms.create(CONTROL_ALARM, { periodInMinutes: CONTROL_ALARM_MINUTES });
wake();
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (![HELPER_MESSAGE.pair, HELPER_MESSAGE.capture, ...Object.values(CONTROL_MESSAGES)].includes(message?.type)) return;
  void (async () => {
    if (Object.values(CONTROL_MESSAGES).includes(message.type)) {
      if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL('popup.html')) throw new Error('Use the companion popup to change the browser connection');
      if (message.type === CONTROL_MESSAGES.status) { const session = await load(), state = connection.status(); return { ...state, paired: Boolean(session) && !state.needsPairing, control: session?.control === true && !state.needsPairing, paused: Boolean(session?.paused || state.paused) }; }
      const session = await load();
      const notify = route => session?.control ? post(addressFrom(session.address), route, { helperId: session.helperId }, session.token) : Promise.resolve();
      if (message.type === CONTROL_MESSAGES.disconnect) { await connection.pause(); await executor.disconnect(); await notify(CONTROL_ROUTES.disconnect).catch(() => {}); }
      if (message.type === CONTROL_MESSAGES.resume) { await notify(CONTROL_ROUTES.resume); await executor.allowDebugger(); await connection.resume(); }
      if (message.type === CONTROL_MESSAGES.unpair) { await connection.pause(); await executor.disconnect(); await notify(CONTROL_ROUTES.revoke).catch(() => {}); await chrome.storage.local.remove(SESSION_KEY); }
      return connection.status();
    }
    if (message.type === HELPER_MESSAGE.pair) {
      // The same extension popup may be opened as a tab for accessible setup/testing.
      if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL('popup.html')) throw new Error('Pair from the helper popup');
      const setup = JSON.parse(message.setup);
      const address = addressFrom(setup.address);
      const previous = (await chrome.storage.local.get(SESSION_KEY))[SESSION_KEY];
      const result = await post(address, ROUTES.pair, { code: setup.code, helperId: previous?.helperId || crypto.randomUUID() });
      await connection.pause();
      await save({ address, token: result.token, helperId: result.helperId, control: result.control === true, paused: false });
      await executor.allowDebugger();
      await connection.resume();
      return { ok: true };
    }
    if (sender.id !== chrome.runtime.id || !sender.tab || !isPageUrl(sender.url) || sender.url.length > MAX_URL_CHARS) throw new Error('Capture is available on ordinary webpages');
    const session = (await chrome.storage.local.get(SESSION_KEY))[SESSION_KEY];
    if (!session) throw new Error('Open this helper and pair it with ANKITA first');
    // The browser supplies the exact document URL, including frame identity.
    return post(addressFrom(session.address), ROUTES.capture, { ...message.ticket, title: message.title, text: message.text, url: sender.url }, session.token);
  })().then(result => respond(result)).catch(error => respond({ error: error.message }));
  return true;
});
