import { HELPER_MESSAGE } from './protocol.mjs';
import { CONTROL_MESSAGES, CONTROL_STATUS_MS, CONTROL_REPAIR_MESSAGE } from './control-protocol.mjs';
const status = document.querySelector('#status'), button = document.querySelector('#pair');
async function send(type) { const result = await chrome.runtime.sendMessage({ type }); if (result?.error) throw new Error(result.error); return result; }
async function refresh() {
  try {
    const state = await send(CONTROL_MESSAGES.status);
    document.querySelector('#connection').textContent = state.needsPairing ? CONTROL_REPAIR_MESSAGE : state.connected ? 'Connected to Ankita' : state.paused ? 'Connection paused' : state.paired && !state.control ? 'Page capture paired. Pair a browser-control code below to enable control.' : state.paired ? 'Waiting for Ankita — reconnects automatically' : 'Not paired';
    document.querySelector('#pairing').hidden = state.paired && state.control;
    document.querySelector('#controls').hidden = !state.paired;
    document.querySelector('#resume').hidden = !state.paused;
    document.querySelector('#disconnect').hidden = state.paused;
  } catch { document.querySelector('#connection').textContent = 'Reopen this companion to check the connection.'; }
}
for (const [id, type] of [['resume', CONTROL_MESSAGES.resume], ['disconnect', CONTROL_MESSAGES.disconnect], ['unpair', CONTROL_MESSAGES.unpair]]) document.querySelector('#' + id).addEventListener('click', async () => {
  try { await send(type); status.textContent = ''; await refresh(); } catch (error) { status.textContent = error.message; }
});
void refresh(); setInterval(() => void refresh(), CONTROL_STATUS_MS);
button.addEventListener('click', async () => {
  button.disabled = true; status.textContent = 'Pairing…';
  try {
    const result = await chrome.runtime.sendMessage({ type: HELPER_MESSAGE.pair, setup: document.querySelector('#setup').value });
    if (result?.error) throw new Error(result.error);
    status.textContent = 'Paired. Drag a teammate onto a webpage.';
    document.querySelector('#setup').value = '';
    await refresh();
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
});
