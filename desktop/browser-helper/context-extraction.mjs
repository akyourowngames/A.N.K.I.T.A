import { MAX_TEXT_BYTES, CAPTURE_SCOPES, boundedText } from './protocol.mjs';

export const CAPTURE_OVERLAY_ID = 'ankita-mascot-capture-target';
const EXCLUDED = 'script,style,noscript,template,form,input,textarea,select,button,[hidden],[aria-hidden="true"],nav,footer';
const MAX_PAGE_TEXT_NODES = 5000; // DOM text nodes; bound explicit extraction on huge dynamic pages.

function textFrom(document, root, range = null) {
  const view = document.defaultView;
  if (!root || !view) return '';
  const hidden = new WeakMap(), chunks = []; let visited = 0, characters = 0;
  const excluded = element => {
    if (!element) return false;
    if (hidden.has(element)) return hidden.get(element);
    const style = view.getComputedStyle(element);
    const skip = element.matches(EXCLUDED) || element.id === CAPTURE_OVERLAY_ID || style.display === 'none' || ['hidden', 'collapse'].includes(style.visibility) || style.contentVisibility === 'hidden' || excluded(element.parentElement);
    hidden.set(element, skip); return skip;
  };
  const append = node => {
    if (excluded(node.parentElement) || (range && !range.intersectsNode(node))) return;
    const start = range?.startContainer === node ? range.startOffset : 0;
    const end = range?.endContainer === node ? range.endOffset : node.textContent.length;
    const text = node.textContent.slice(start, end).replace(/\s+/g, ' ').trim().slice(0, MAX_TEXT_BYTES - characters);
    if (text) { chunks.push(text); characters += text.length; }
  };
  if (root.nodeType === view.Node.TEXT_NODE) append(root);
  else {
    const walker = document.createTreeWalker(root, view.NodeFilter.SHOW_TEXT); let node;
    while ((node = walker.nextNode()) && visited++ < MAX_PAGE_TEXT_NODES && characters < MAX_TEXT_BYTES) append(node);
  }
  return boundedText(chunks.join('\n'));
}

export function extractPage(document) { return textFrom(document, document.querySelector('article') || document.querySelector('main') || document.body); }
export function extractContext(document) {
  const selection = document.defaultView?.getSelection();
  if (selection?.rangeCount && !selection.isCollapsed) {
    const range = selection.getRangeAt(0), text = textFrom(document, range.commonAncestorContainer, range);
    if (text) return { text, scope: CAPTURE_SCOPES.selection };
    // A selected private/hidden control must not silently cause a whole-page capture.
    return { text: '', scope: CAPTURE_SCOPES.selection };
  }
  return { text: extractPage(document), scope: CAPTURE_SCOPES.page };
}
