import { HELPER_MESSAGE } from './protocol.mjs';
const status = document.querySelector('#status'), button = document.querySelector('#pair');
button.addEventListener('click', async () => {
  button.disabled = true; status.textContent = 'Pairing…';
  try {
    const result = await chrome.runtime.sendMessage({ type: HELPER_MESSAGE.pair, setup: document.querySelector('#setup').value });
    if (result?.error) throw new Error(result.error);
    status.textContent = 'Paired. Drag a teammate onto a webpage.';
    document.querySelector('#setup').value = '';
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
});
