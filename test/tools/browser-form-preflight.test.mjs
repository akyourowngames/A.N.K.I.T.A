import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { chromium } from 'playwright';
import { PlaywrightBrowserAdapter } from '../../tools/browser/playwright.mjs';
import { ChromeBrowserAdapter } from '../../tools/browser/chrome.mjs';
import { assertFillControl, assertBatchTarget, inspectFillControl, ISOLATED_REF_PATTERN } from '../../tools/browser/refs.mjs';
import { independentRefBatch } from '../../tools/browser/operations.mjs';

const refFor = (snapshot, label) => snapshot.split('\n').find(line => line.includes(label) && line.includes('[ref='))?.match(/\[ref=([^\]]+)\]/)?.[1];
const CLEANUP = { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }; // Disposable Windows browser fixture only.

test('malformed form steps retain normal argument validation without a batch eligibility crash', () => {
  const edit = { action: 'act', ref: '1-0-1', op: 'click' };
  for (const fields of [null, {}, 'wrong', [null]]) assert.equal(independentRefBatch([{ action: 'fill_form', fields }, edit]), false);
});

test('later readonly preflight does not claim completed batch steps made no changes', () => {
  const probe = { fill: { tag: 'input', type: 'text', issue: 'readonly' }, state: {} };
  assert.throws(() => assertBatchTarget(probe, { action: 'fill_form' }, { ref: '1-0-1', text: 'new' }, ISOLATED_REF_PATTERN), error => {
    assert.equal(error.name, 'BrowserReferenceError'); assert.match(error.message, /readonly/); assert.doesNotMatch(error.message, /No fields changed/); return true;
  });
});

test('background generic filling cannot substitute guessed text for a private password', () => {
  const control = { tag: 'input', type: 'password', issue: null }, field = { ref: '1-0-0', text: 'guessed' };
  assert.throws(() => assertFillControl(control, field, ISOLATED_REF_PATTERN, true), /browser login.*credential_fields/);
  assert.doesNotThrow(() => assertFillControl(control, field, ISOLATED_REF_PATTERN, false));
});

test('show-password does not turn a known private password into a generic writable field', () => {
  const marked = { tagName: 'INPUT', type: 'text', isConnected: true, matches: () => false, getAttribute: name => name === 'data-ankita-credential' ? 'password' : null };
  const control = inspectFillControl(marked, 'data-ankita-credential');
  assert.throws(() => assertFillControl(control, { ref: '1-0-0', text: 'guessed' }, ISOLATED_REF_PATTERN, true), /browser login.*credential_fields/);
});

test('Chrome custom toggle eligibility does not broaden the Playwright fill contract', () => {
  const toggle = { tagName: 'DIV', type: '', isConnected: true, matches: () => false, getAttribute: name => name === 'role' ? 'switch' : null };
  assert.equal(inspectFillControl(toggle, 'data-ankita-credential', true).issue, null);
  assert.equal(inspectFillControl(toggle, 'data-ankita-credential', false).issue, 'not editable');
});

test('Chrome reports a dialog-interrupted batch as incomplete without replaying it', async () => {
  let mutations = 0;
  const adapter = new ChromeBrowserAdapter({ has: () => true, callTool: async name => {
    if (name.endsWith('__list_pages')) return '1: Form (https://example.com/) [selected]';
    if (name.endsWith('__take_snapshot')) return 'uid=1_1 textbox "Report text"\nuid=1_2 textbox "Second field"';
    if (name.endsWith('__evaluate_script')) return '```json\n[{"tag":"input","type":"text","issue":null},{"tag":"input","type":"text","issue":null}]\n```';
    if (name.endsWith('__fill_form')) { mutations++; return 'Filling out the element with uid 1_1 opened a dialog. The remaining elements were not filled out.'; }
    return 'ok';
  } });
  const snapshot = await adapter.run({ action: 'snapshot' });
  await assert.rejects(adapter.run({ action: 'fill_form', fields: [{ ref: refFor(snapshot, 'Report text'), text: 'first' }, { ref: refFor(snapshot, 'Second field'), text: 'second' }] }), /interrupted.*dialog/);
  assert.equal(mutations, 1);
});

test('real Chromium rejects a noneditable batch target before filling any field', async t => {
  if (!fs.existsSync(chromium.executablePath())) return t.skip('Chromium has not been downloaded');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-fill-preflight-'));
  const server = http.createServer((_request, response) => { response.setHeader('content-type', 'text/html'); response.end('<label>Report text<input value="original"></label><button>Publish report</button><label>Locked<input readonly value="locked"></label>'); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(directory, 'profile'), headless: true });
  t.after(async () => { await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); assert.equal(path.dirname(fs.realpathSync(directory)), fs.realpathSync(os.tmpdir())); await fs.promises.rm(directory, CLEANUP); });
  const ctx = { config: { allowPrivateHosts: true }, settings: { headless: true } };
  let snapshot = await adapter.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}/` }, ctx);
  for (const label of ['Publish report', 'Locked']) {
    await assert.rejects(adapter.run({ action: 'fill_form', fields: [{ ref: refFor(snapshot, 'Report text'), text: 'changed' }, { ref: refFor(snapshot, label), text: 'invalid' }] }, ctx), error => {
      assert.equal(error.name, 'BrowserReferenceError'); assert.match(error.message, /No fields changed/); assert.match(error.message, /Fresh snapshot:/); snapshot = error.message; return true;
    });
    assert.equal(await adapter.page.locator('input').first().inputValue(), 'original');
  }
  assert.match(await adapter.run({ action: 'fill_form', fields: [{ ref: refFor(snapshot, 'Report text'), text: 'changed' }] }, ctx), /Filled 1 fields/);
  assert.equal(await adapter.page.locator('input').first().inputValue(), 'changed');
  await adapter.page.locator('input').first().evaluate(element => element.addEventListener('input', () => { document.querySelectorAll('input')[1].readOnly = true; }));
  await adapter.page.locator('input[readonly]').evaluate(element => { element.readOnly = false; });
  snapshot = await adapter.run({ action: 'snapshot' }, ctx);
  await assert.rejects(adapter.run({ action: 'fill_form', fields: [{ ref: refFor(snapshot, 'Report text'), text: 'partial' }, { ref: refFor(snapshot, 'Locked'), text: 'invalid' }] }, ctx), error => {
    assert.equal(error.name, 'Error'); assert.match(error.message, /Earlier fields may have changed/); assert.doesNotMatch(error.message, /No fields changed|Fresh snapshot:/); return true;
  });
  assert.equal(await adapter.page.locator('input').first().inputValue(), 'partial');
  console.log('FILL_PREFLIGHT_LIVE_OK: invalid button and readonly targets; zero partial writes; fresh-ref recovery completed');
});

test('Chrome validates every target before issuing the form mutation', async () => {
  let mutations = 0;
  const mcp = { has: () => true, callTool: async (name, args) => {
    if (name.endsWith('__list_pages')) return '1: Form (https://example.com/) [selected]';
    if (name.endsWith('__take_snapshot')) return 'uid=1_1 textbox "Report text"\nuid=1_2 button "Publish report"';
    if (name.endsWith('__evaluate_script')) { assert.deepEqual(args.args, ['1_1', '1_2']); return '```json\n[{"tag":"input","type":"text","issue":null},{"tag":"button","type":"submit","issue":"not editable"}]\n```'; }
    if (name.endsWith('__fill_form')) mutations++;
    return 'ok';
  } };
  const adapter = new ChromeBrowserAdapter(mcp), snapshot = await adapter.run({ action: 'snapshot' });
  await assert.rejects(adapter.run({ action: 'fill_form', fields: [{ ref: refFor(snapshot, 'Report text'), text: 'changed' }, { ref: refFor(snapshot, 'Publish report'), text: 'invalid' }] }), error => {
    assert.equal(error.name, 'BrowserReferenceError'); assert.match(error.message, /No fields changed/); assert.match(error.message, /Fresh snapshot:/); return true;
  });
  assert.equal(mutations, 0);
});
