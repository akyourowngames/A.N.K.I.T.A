import { ROUTES, HELPER_MESSAGE, REQUEST_TIMEOUT_MS, LOOPBACK_HOST, MAX_URL_CHARS, isPageUrl } from './protocol.mjs';
const SESSION_KEY = 'pairedDesktop'; // Extension-private storage; page scripts never receive bearer credentials.
function addressFrom(value) {
  const url = new URL(value);
  if (url.protocol !== 'http:' || url.hostname !== LOOPBACK_HOST || !url.port || url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw new Error('Copy the pairing code from ANKITA');
  return url.origin;
}
async function post(address, route, body, token) {
  const response = await fetch(address + route, { method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) }, body: JSON.stringify(body), signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'ANKITA could not receive this page');
  return result;
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (![HELPER_MESSAGE.pair, HELPER_MESSAGE.capture].includes(message?.type)) return;
  void (async () => {
    if (message.type === HELPER_MESSAGE.pair) {
      // The same extension popup may be opened as a tab for accessible setup/testing.
      if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL('popup.html')) throw new Error('Pair from the helper popup');
      const setup = JSON.parse(message.setup);
      const address = addressFrom(setup.address);
      const previous = (await chrome.storage.local.get(SESSION_KEY))[SESSION_KEY];
      const result = await post(address, ROUTES.pair, { code: setup.code, helperId: previous?.helperId || crypto.randomUUID() });
      await chrome.storage.local.set({ [SESSION_KEY]: { address, token: result.token, helperId: result.helperId } });
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
