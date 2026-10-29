/** Self-contained function serialized into Chrome's isolated extension world. Policy is passed as data. */
export function pageOperation(request) {
  let dispatched = false;
  try {
    const { scope, stateKey, limits, staleMessage } = request;
    const ID_WORDS = 4, HEX_RADIX = 16; // Four 32-bit random words give opaque 128-bit IDs, including on ordinary HTTP pages.
    const identity = () => [...crypto.getRandomValues(new Uint32Array(ID_WORDS))].map(word => word.toString(HEX_RADIX)).join('-');
    if (request.expectedUrl && request.expectedUrl !== location.href) throw new Error(staleMessage);
    const selector = 'a[href],button,input,textarea,select,summary,[contenteditable="true"],[role="button"],[role="textbox"],[role="checkbox"],[role="combobox"],[tabindex]';
    const visible = node => { const style = getComputedStyle(node); return node.isConnected && style.visibility !== 'hidden' && style.display !== 'none' && node.getClientRects().length > 0; };
    const name = node => String(node.getAttribute('aria-label') || (node.labels && [...node.labels].map(label => label.innerText).join(' ')) || node.innerText || node.getAttribute('placeholder') || node.getAttribute('name') || '').trim().slice(0, limits.name);
    const role = node => node.getAttribute('role') || ({ A: 'link', BUTTON: 'button', TEXTAREA: 'textbox', SELECT: 'combobox', INPUT: /checkbox|radio/.test(node.type) ? node.type : 'textbox' })[node.tagName] || 'control';
    if (!globalThis[stateKey] || globalThis[stateKey].url !== location.href) globalThis[stateKey] = { documentId: identity(), scopes: new Map(), url: location.href };
    const root = globalThis[stateKey];
    const snapshot = () => {
      const refs = new Map(), controls = [...document.querySelectorAll(selector)].filter(visible).filter(node => !request.query || name(node).toLowerCase().includes(String(request.query).toLowerCase())).slice(0, limits.controls).map(node => {
        const ref = identity(); // A later snapshot cannot reassign an old ref to a different node.
        const href = node.tagName === 'A' ? node.href : null, formAction = node.type === 'submit' ? node.formAction || node.form?.action || null : null;
        refs.set(ref, { node, role: role(node), name: name(node), type: node.type, href, formAction });
        return { ref, role: role(node), name: name(node), href, formAction, disabled: Boolean(node.disabled), editable: node.matches('input,textarea,[contenteditable="true"]') };
      });
      root.scopes.set(scope, refs);
      // Each observation owns bounded refs. Old task scopes are dropped rather than growing forever.
      while (root.scopes.size > limits.scopes) root.scopes.delete(root.scopes.keys().next().value);
      return { documentId: root.documentId, url: location.href, title: document.title, controls, text: String(document.body?.innerText || '').slice(0, limits.text) };
    };
    if (request.action === 'snapshot' || request.action === 'read') return snapshot();
    const target = ref => {
      const entry = root.scopes.get(scope)?.get(ref), node = entry?.node;
      if (request.documentId !== root.documentId || !node || !visible(node) || node.disabled || node.inert || node.closest('[inert]') || entry.role !== role(node) || entry.name !== name(node) || entry.type !== node.type || entry.href !== (node.tagName === 'A' ? node.href : null) || entry.formAction !== (node.type === 'submit' ? node.formAction || node.form?.action || null : null)) throw new Error(staleMessage);
      return node;
    };
    const fill = (node, text) => {
      if (!node.matches('input,textarea,[contenteditable="true"]') || node.readOnly || node.type === 'file' || node.type === 'password') throw new Error('This control cannot be filled through the page extension. Use the browser directly for passwords or files.');
      node.focus(); dispatched = true;
      if (node.isContentEditable) node.textContent = text;
      else {
        const prototype = node.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(prototype, 'value').set.call(node, text);
      }
      node.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text })); node.dispatchEvent(new Event('change', { bubbles: true }));
    };
    if (request.action === 'fill_form') {
      const targets = request.fields.map(field => ({ node: target(field.ref), text: String(field.value ?? field.text ?? '') }));
      if (targets.some(({ node }) => !node.matches('input,textarea,[contenteditable="true"]') || node.readOnly || ['file', 'password'].includes(node.type))) throw new Error('One of the form controls cannot be filled safely');
      for (const item of targets) fill(item.node, item.text);
      return { ok: true, dispatched };
    }
    if (request.action !== 'act') throw new Error('Unsupported page operation');
    const op = request.op || 'click';
    if (op === 'scroll' && !request.ref) { dispatched = true; window.scrollBy({ top: request.deltaY, left: request.deltaX || 0, behavior: 'instant' }); return { ok: true, dispatched }; }
    const node = target(request.ref);
    if (request.inspectTarget) { node.scrollIntoView({ block: 'center', inline: 'center' }); if (request.focusTarget) node.focus(); const rect = node.getBoundingClientRect(); return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 }; }
    if (op === 'fill' || op === 'type') fill(node, (op === 'type' ? String(node.isContentEditable ? node.textContent : node.value || '') : '') + String(request.text ?? request.value ?? ''));
    else if (op === 'click') { node.scrollIntoView({ block: 'center', inline: 'center' }); dispatched = true; node.click(); }
    else if (op === 'check' || op === 'uncheck') { if (!node.matches('input[type="checkbox"],input[type="radio"]')) throw new Error('Choose a checkbox or radio control'); dispatched = true; if (node.checked !== (op === 'check')) node.click(); }
    else if (op === 'select') {
      if (node.tagName !== 'SELECT') throw new Error('Choose a select control');
      const value = String(request.value ?? request.text ?? '');
      const option = [...node.options].find(item => item.value === value || item.label === value);
      if (!option || option.disabled) throw new Error('The requested option is unavailable');
      dispatched = true; node.value = option.value; node.dispatchEvent(new Event('input', { bubbles: true })); node.dispatchEvent(new Event('change', { bubbles: true }));
    } else if (op === 'hover') { dispatched = true; node.dispatchEvent(new MouseEvent('mouseover', { bubbles: true })); node.dispatchEvent(new MouseEvent('mouseenter')); }
    else if (op === 'scroll') { dispatched = true; node.scrollBy({ top: request.deltaY, left: request.deltaX || 0, behavior: 'instant' }); }
    else throw new Error('This action needs deeper browser control');
    return { ok: true, dispatched };
  } catch (error) { return { error: error.message, dispatched }; }
}
