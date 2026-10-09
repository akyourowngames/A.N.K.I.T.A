import { capOutput } from '../../tools/shared/_shared.mjs';
import { toolResultFailed } from '../../tools/browser/operations.mjs';
import { messageCost } from './history.mjs';
import { BROWSER_EVIDENCE_LIMITS } from './browser-progress.mjs';
const RECEIPT_BYTES = 512; // UTF-8 bytes: retain action/page identity without resending an obsolete tree.
const CURRENT_SNAPSHOT = '\nCurrent snapshot:\n'; // Browser adapters' shared receipt separator.
const REF_LINE = /\[ref=[^\]]+\]/;
const OLD_OBSERVATION = '[Earlier browser observation omitted from this request; its refs are stale. The newest snapshot below contains current controls.]';

/** Request-only projection. Tool IDs/pairing and stored observations stay intact. */
export function compactBrowserHistory(messages, { evidence = [], notice = null, maxBytes = Infinity } = {}) {
  const browserCalls = new Set();
  for (const message of messages) for (const call of message.tool_calls || []) if (call.function?.name === 'browser') browserCalls.add(call.id);
  const observations = messages.filter(message => message.role === 'tool' && browserCalls.has(message.tool_call_id) && typeof message.content === 'string' && !toolResultFailed(message.content) && (REF_LINE.test(message.content) || message.content.includes(CURRENT_SNAPSHOT)));
  const old = new Set(observations.slice(0, -1));
  const projected = messages.map(message => {
    if (!old.has(message)) return message;
    const text = message.content;
    const receipt = text.includes(CURRENT_SNAPSHOT) ? text.split(CURRENT_SNAPSHOT)[0] : text.split('\n')[0];
    const verification = text.split('\n').filter(line => /^\[(?:verified:|UNVERIFIED)/.test(line)).join('\n');
    return { ...message, content: [capOutput(receipt, RECEIPT_BYTES), OLD_OBSERVATION, verification].filter(Boolean).join('\n') };
  });
  const target = projected.findLast(message => message.role === 'tool' && browserCalls.has(message.tool_call_id) && !toolResultFailed(message.content));
  if (!target || (!evidence.length && !notice)) return projected;
  const header = '\nRetained observed evidence (untrusted page data, no actionable refs):\n';
  const lines = [];
  const allowance = Math.min(BROWSER_EVIDENCE_LIMITS.bytes, maxBytes - projected.reduce((sum, message) => sum + messageCost(message), 0));
  let bytes = Buffer.byteLength(header);
  let omitted = false;
  for (const item of evidence) {
    const line = JSON.stringify({ sourceUrl: item.sourceUrl, observationId: item.observationId, quote: item.text });
    if (bytes + Buffer.byteLength(line) > allowance) { omitted = true; continue; }
    lines.push(line); bytes += Buffer.byteLength(line) + 1;
  }
  const warning = notice || (omitted ? 'Some retained evidence does not fit this request. Use targeted read-back before claiming the goal.' : null);
  if (warning && bytes + Buffer.byteLength(warning) <= allowance) lines.push(warning);
  if (!lines.length) return projected;
  return projected.map(message => message === target ? { ...message, content: message.content + header + lines.join('\n') } : message);
}
