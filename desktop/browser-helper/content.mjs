import { DRAG_MIME, HELPER_MESSAGE, PROTOCOL_VERSION, MAX_TITLE_CHARS, RECEIPT_MS } from './protocol.mjs';
import { CAPTURE_OVERLAY_ID as OVERLAY_ID, extractContext } from './context-extraction.mjs';
export { extractPage } from './context-extraction.mjs';
let overlay, dismiss, depth = 0;
function target(message, result) {
  if (!overlay) {
    const host = document.createElement('div'); host.id = OVERLAY_ID;
    host.style.cssText = 'position:fixed;inset:0;z-index:2147483647;pointer-events:none';
    const shadow = host.attachShadow({ mode: 'closed' });
    shadow.innerHTML = `<style>:host{all:initial}.target{position:absolute;inset:18px;border:2px dashed #baaa83;border-radius:24px;background:#090b0d26;display:grid;place-items:end center;padding:28px;box-sizing:border-box;animation:land .3s ease-out}.label{font:14px system-ui;color:#fff;background:#141619ed;padding:14px 22px;border-radius:24px;box-shadow:0 8px 32px #0003}.face{display:inline-block;margin-right:10px;color:#baaa83;animation:peek .8s ease-in-out infinite alternate}@keyframes land{from{opacity:0;transform:scale(.98)}to{opacity:1;transform:scale(1)}}@keyframes peek{to{transform:translateY(-3px)}}@media(prefers-reduced-motion:reduce){*{animation:none!important}}</style><div class="target"><span class="label" role="status"><span class="face" aria-hidden="true">●‿●</span><span class="message"></span></span></div>`;
    document.documentElement.append(host);
    overlay = { host, text: shadow.querySelector('.message') };
  }
  overlay.text.textContent = message;
  clearTimeout(dismiss);
  if (result) dismiss = setTimeout(clear, RECEIPT_MS);
}
function clear() { overlay?.host.remove(); overlay = null; depth = 0; clearTimeout(dismiss); }
const ours = event => Array.from(event.dataTransfer?.types || []).includes(DRAG_MIME);
document.addEventListener('dragenter', event => { if (!ours(event)) return; event.preventDefault(); depth++; target('Drop your teammate here to read this page'); }, true);
document.addEventListener('dragover', event => { if (!ours(event)) return; event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; target('Drop your teammate here to read this page'); }, true);
document.addEventListener('dragleave', event => { if (ours(event) && --depth <= 0) clear(); }, true);
document.addEventListener('drop', event => {
  if (!ours(event)) return;
  event.preventDefault(); event.stopImmediatePropagation(); depth = 0;
  void (async () => {
    const ticket = JSON.parse(event.dataTransfer.getData(DRAG_MIME));
    if (ticket.version !== PROTOCOL_VERSION) throw new Error('Update the helper to match ANKITA');
    const { text, scope } = extractContext(document);
    if (!text) throw new Error('This page has no readable text');
    target('Reading this page…');
    const result = await chrome.runtime.sendMessage({ type: HELPER_MESSAGE.capture, ticket, title: document.title.slice(0,MAX_TITLE_CHARS), text, scope });
    if (result?.error) throw new Error(result.error);
    target('Page attached in ANKITA ✓', true);
  })().catch(error => target(error.message || 'Page capture failed; try again', true));
}, true);
document.addEventListener('keydown', event => { if (event.key === 'Escape') clear(); });
