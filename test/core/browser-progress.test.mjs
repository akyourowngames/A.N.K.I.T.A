import test from 'node:test';
import assert from 'node:assert/strict';
import { compactBrowserHistory } from '../../src/core/browser-context.mjs';
const progress = await import('../../src/core/browser-progress.mjs').catch(() => ({}));
const observation = (ref, value = '1') => ({ id: ref, tabId: '1', url: 'https://fixture.test/a', documentId: 'document',
  controls: [{ ref, role: 'spinbutton', name: 'Quantity', states: { value } }], context: [] });
const result = (ref, value) => ({ status: 'executed', action: 'snapshot', observation: observation(ref, value), error: null, evidence: [] });

test('changing refs cannot disguise an unchanged page while quantity changes count as observed progress', () => {
  assert.equal(typeof progress.recordBrowserProgress, 'function');
  let state;
  for (let index = 0; index < 4; index++) state = progress.recordBrowserProgress(state, result(String(index)), { maxRepeats: 3 });
  assert.equal(state.stalled, true);
  assert.match(state.guidance, /unchanged|read.back/i);
  const changed = progress.recordBrowserProgress(state, result('fresh', '2'), { maxRepeats: 3 });
  assert.equal(changed.stalled, false);
  assert.equal(changed.changed, true);
  assert.equal(changed.goalVerified, false, 'observed change is not an independent goal oracle');
});

test('comparison quotes survive obsolete control projection without changing stored history or tool pairing', () => {
  const messages = [];
  for (const [id, price] of [['a', '19'], ['b', '27']]) messages.push(
    { role: 'assistant', tool_calls: [{ id, function: { name: 'browser' } }] },
    { role: 'tool', tool_call_id: id, content: `Store ${id} — https://fixture.test/${id}\n[ref=${id}] button Continue\nVisible page text: Price ${price}` });
  const stored = JSON.stringify(messages);
  const evidence = [{ id: 'fact-a', callId: 'a', sourceUrl: 'https://fixture.test/a', observationId: 'obs-a', text: 'Price 19' }];
  const projected = compactBrowserHistory(messages, { evidence });
  assert.match(JSON.stringify(projected), /Price 19/);
  assert.match(projected.at(-1).content, /untrusted|page data/i);
  assert.equal(JSON.stringify(messages), stored);
  assert.deepEqual(projected.filter(item => item.role === 'tool').map(item => item.tool_call_id), ['a', 'b']);
});

test('retained evidence is grounded and oversized quotes are refused with a visible notice', () => {
  assert.equal(typeof progress.captureBrowserEvidence, 'function');
  const source = { sourceUrl: 'https://fixture.test/a', observationId: 'source', text: 'Price 19' };
  const state = progress.captureBrowserEvidence(null, { ...result('a'), observation: { ...observation('a'), context: [source] }, evidence: [
    { ...source, id: 'fact', text: 'Price 19' }, { ...source, id: 'invented', text: 'Price 7' },
  ] }, 'call');
  assert.ok(state.items.some(item => item.text === 'Price 19'));
  assert.ok(!state.items.some(item => item.text === 'Price 7'));
  const oversized = { ...source, text: 'X'.repeat(10000) };
  const bounded = progress.captureBrowserEvidence(state, { ...result('b'), observation: { ...observation('b'), context: [oversized] }, evidence: [] }, 'next', { maxChunkBytes: 128 });
  assert.deepEqual(bounded.items, state.items);
  assert.match(bounded.notice, /limit.*find|find.*limit/i);
});

test('small request budgets omit whole quotes with a notice rather than silently clipping evidence', () => {
  const messages = [{ role: 'assistant', tool_calls: [{ id: 'read', function: { name: 'browser' } }] }, { role: 'tool', tool_call_id: 'read', content: 'Observed page' }];
  const projected = compactBrowserHistory(messages, { maxBytes: 500, evidence: [{ sourceUrl: 'https://fixture.test', observationId: 'source', text: 'X'.repeat(2000) }] });
  assert.match(projected.at(-1).content, /does not fit.*read.back/);
  assert.ok(Buffer.byteLength(JSON.stringify(projected)) < 500);
});
