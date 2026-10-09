import { randomUUID } from 'node:crypto';
import { BROWSER_CONTRACT_VERSION, BASE_BROWSER_CAPABILITIES } from './contracts.mjs';
import { SNAPSHOT_LIMITS } from './refs.mjs';

// Native read/search are bounded and deterministic; document identity must be supplied by the adapter.
export const TEXT_BROWSER_CAPABILITIES = Object.freeze({ ...BASE_BROWSER_CAPABILITIES, pageTextSearch: true, chunkedRead: true });
export function createBrowserObservation({ id = randomUUID(), mode, tabId = null, url, documentId = null, controls = [], context = [], omissions = {}, capabilities = TEXT_BROWSER_CAPABILITIES }) {
  const clippedControls = Math.max(0, controls.length - SNAPSHOT_LIMITS.elements); // Control count: include additional factory clipping without guessing an unknown source count.
  const omittedControls = Number.isSafeInteger(omissions.controls) && omissions.controls >= 0 ? omissions.controls + clippedControls : null;
  return { version: BROWSER_CONTRACT_VERSION, id, mode, tabId: tabId == null ? null : String(tabId), url, documentId,
    controls: controls.slice(0, SNAPSHOT_LIMITS.elements), context,
    omissions: { frames: null, ...omissions, controls: Number.isSafeInteger(omittedControls) ? omittedControls : null,
      truncated: Boolean(omissions.truncated || clippedControls) }, capabilities: { ...capabilities } };
}
export function textObservation({ result, mode, tabId, documentId = null, capabilities = TEXT_BROWSER_CAPABILITIES }) {
  return createBrowserObservation({ id: result.id, mode, tabId, documentId, url: result.url,
    context: result.chunks, omissions: { truncated: result.truncated }, capabilities });
}
