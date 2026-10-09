import { createHash } from 'node:crypto';

// UTF-8 byte/item ceilings: quoted task evidence is bounded separately from obsolete control trees.
export const BROWSER_EVIDENCE_LIMITS = Object.freeze({ bytes: 16000, items: 16, chunkBytes: 2048 });
export const BROWSER_EVIDENCE_NOTICE = 'Browser evidence limit reached. Use find with a specific phrase or read a smaller chunk; oversized evidence was not retained.';
const STALLED_GUIDANCE = 'The observed page is unchanged. Read back the requested outcome, choose a different method or take control; do not repeat a possible submission.';
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');

/** Captured quotations only. No semantic fact extraction and no personal-memory writes. */
export function captureBrowserEvidence(previous, result, callId, { maxBytes = BROWSER_EVIDENCE_LIMITS.bytes, maxItems = BROWSER_EVIDENCE_LIMITS.items, maxChunkBytes = BROWSER_EVIDENCE_LIMITS.chunkBytes } = {}) {
  const items = [...(previous?.items || [])];
  const chunks = [...(result.observation?.context || []), ...(result.observations || []).flatMap(observation => observation.context || [])];
  const candidates = [...(result.evidence || []).filter(evidence => chunks.some(chunk => chunk.observationId === evidence.observationId && chunk.sourceUrl === evidence.sourceUrl && chunk.text.includes(evidence.text))), ...chunks];
  const keys = new Set(items.map(item => hash([item.sourceUrl, item.text])));
  let notice = previous?.notice || null;
  let bytes = Buffer.byteLength(JSON.stringify(items));
  for (const candidate of candidates) {
    if (!candidate.text || typeof candidate.text !== 'string' || !candidate.sourceUrl || !candidate.observationId) continue;
    const key = hash([candidate.sourceUrl, candidate.text]);
    if (keys.has(key)) continue;
    const item = { id: key, callId, sourceUrl: candidate.sourceUrl, observationId: candidate.observationId, text: candidate.text };
    const nextBytes = Buffer.byteLength(JSON.stringify([...items, item]));
    if (Buffer.byteLength(item.text) > maxChunkBytes || items.length >= maxItems || nextBytes > maxBytes) { notice = BROWSER_EVIDENCE_NOTICE; continue; }
    items.push(item); keys.add(key); bytes = nextBytes;
  }
  return { items, bytes, notice };
}

/** Ignore ephemeral refs/observation IDs. Observed change is separate from goal verification. */
export function recordBrowserProgress(previous, result, { maxRepeats }) {
  if (!Number.isInteger(maxRepeats) || maxRepeats < 1) throw new Error('Browser progress requires a positive recovery bound.');
  const observation = result.observation;
  const fingerprint = observation ? hash([observation.tabId, observation.url, observation.documentId,
    observation.controls.map(control => [control.frameId, control.role, control.name, control.states, control.editable, control.actionable]),
    observation.context.map(chunk => [chunk.sourceUrl, chunk.frameId, chunk.start, chunk.end, chunk.text])]) : previous?.fingerprint ?? null;
  const changed = Boolean(observation && fingerprint !== previous?.fingerprint);
  const noProgress = changed ? 0 : (previous?.noProgress || 0) + 1;
  const stalled = noProgress >= maxRepeats;
  const recoveryCount = Math.min(maxRepeats, (previous?.recoveryCount || 0) + (result.error || stalled ? 1 : 0));
  return { fingerprint, changed, noProgress, stalled, recoveryCount, status: result.status, goalVerified: false,
    guidance: result.error?.recovery || (stalled ? STALLED_GUIDANCE : null) };
}
