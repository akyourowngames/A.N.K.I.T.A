import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-sequence-'));
process.env.CONFIG_DIR = path.join(root, 'config');
const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
const { ChromeBrowserAdapter } = await import('../../tools/browser/chrome.mjs');
const sequence = await import('../../tools/browser/sequence.mjs').catch(() => ({}));
test.after(() => fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));

async function fixture(t, behavior = '') {
  let submissions = 0;
  const server = http.createServer((req, res) => {
    res.setHeader('content-type', 'text/html');
    if (req.method === 'POST') { submissions++; res.end('<p>Saved once.</p>'); }
    else res.end(`<form method="post"><label>First<input name="first"></label><label>Second<input name="second"></label><button>Save</button></form><script>${behavior}</script>`);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const adapter = new PlaywrightBrowserAdapter({ profile: fs.mkdtempSync(path.join(root, 'profile-')) });
  t.after(async () => { await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const ctx = { config: { allowPrivateHosts: true, browserRuntimeV2: true }, settings: { headless: true } };
  await adapter.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}` }, ctx);
  const observation = await adapter.observe({}, ctx);
  const ref = name => observation.controls.find(control => control.name === name).ref;
  const args = { action: 'sequence', observation_id: observation.id, steps: [
    { action: 'act', op: 'fill', ref: ref('First'), text: 'one' },
    { action: 'act', op: 'fill', ref: ref('Second'), text: 'two' },
    { action: 'act', op: 'click', ref: ref('Save') },
  ] };
  return { adapter, ctx, args, submissions: () => submissions };
}

test('sequence validation refuses nested, stale, cross-tab and unsupported plans before execution', () => {
  assert.equal(typeof sequence.validateSequence, 'function');
  const observation = { id: 'source', tabId: '1', mode: 'isolated', controls: [{ ref: '1-0-0', editable: true, actionable: true }] };
  const args = { action: 'sequence', observation_id: 'source', steps: [{ action: 'act', op: 'fill', ref: '1-0-0', text: 'one' }] };
  assert.doesNotThrow(() => sequence.validateSequence(args, observation, { guardedSequences: true }));
  for (const invalid of [{ ...args, observation_id: 'old' }, { ...args, steps: [{ action: 'batch', steps: args.steps }] }, { ...args, steps: [{ ...args.steps[0], tab: '2' }] }]) {
    assert.throws(() => sequence.validateSequence(invalid, observation, { guardedSequences: true }));
  }
  assert.throws(() => sequence.validateSequence(args, observation, { guardedSequences: false }), /does not support/);
});

test('live guarded fields submit once and publish only a final snapshot', async t => {
  const { adapter, ctx, args, submissions } = await fixture(t);
  const serial = adapter.snapshotId;
  const result = await adapter.execute(args, ctx);
  assert.equal(result.status, 'executed');
  assert.equal(result.steps.length, 3);
  assert.equal(submissions(), 1);
  assert.equal(adapter.snapshotId, serial + 1);
  assert.ok(result.observation);
  console.log('SEQUENCE_SUBMIT_LIVE', JSON.stringify({ status: result.status, writes: submissions(), primitives: result.steps.length, observations: adapter.snapshotId - serial }));
});

test('same-URL replacement refuses the suffix instead of rebinding to a matching label', async t => {
  const behavior = "document.querySelector('[name=first]').oninput=()=>{const node=document.querySelector('[name=second]');node.outerHTML='<input name=second>'}";
  const { adapter, ctx, args, submissions } = await fixture(t, behavior);
  const result = await adapter.execute(args, ctx);
  assert.equal(result.status, 'partial');
  assert.deepEqual(result.steps.map(step => step.status), ['executed', 'failed', 'not_run']);
  assert.equal(await adapter.page.locator('[name=first]').inputValue(), 'one');
  assert.equal(await adapter.page.locator('[name=second]').inputValue(), '');
  assert.equal(submissions(), 0);
  assert.equal(result.steps[0].retrySafe, false);
  console.log('SEQUENCE_REPLACEMENT_LIVE', JSON.stringify({ statuses: result.steps.map(step => step.status), submissions: submissions() }));
});

test('Stop between sequence primitives preserves the first receipt and never submits', async t => {
  const { adapter, ctx, args, submissions } = await fixture(t);
  const controller = new AbortController();
  const result = await adapter.execute(args, { ...ctx, signal: controller.signal, onBrowserDispatch: event => { if (event.phase === 'complete') controller.abort(); } });
  assert.equal(result.status, 'partial');
  assert.deepEqual(result.steps.map(step => step.status), ['executed', 'failed', 'not_run']);
  assert.equal(await adapter.page.locator('[name=second]').inputValue(), '');
  assert.equal(submissions(), 0);
});

test('unsupported Chrome sequence and disabled runtime never write', async t => {
  const { adapter, ctx, args, submissions } = await fixture(t);
  const disabled = await adapter.execute(args, { ...ctx, config: { ...ctx.config, browserRuntimeV2: false } });
  assert.equal(disabled.status, 'failed');
  assert.match(disabled.error.message, /experimental runtime/i);
  assert.equal(submissions(), 0);
  let writes = 0;
  const chrome = new ChromeBrowserAdapter({ has: () => true, callTool: async name => {
    if (name.endsWith('__list_pages')) return '1: Form (https://fixture.test/) [selected]';
    writes++; return 'ok';
  } });
  const result = await chrome.execute(args, ctx);
  assert.equal(result.status, 'failed');
  assert.match(result.error.message, /does not support.*guarded sequence/i);
  assert.equal(writes, 0);
});
