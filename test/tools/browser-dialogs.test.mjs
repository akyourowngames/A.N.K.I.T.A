import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-dialog-'));
process.env.CONFIG_DIR = path.join(root, 'config');
const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
const { ChromeBrowserAdapter } = await import('../../tools/browser/chrome.mjs');
const browser = await import('../../tools/browser/browser.mjs');
test.after(() => fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));

test('live confirm waits for an explicit decision and never repeats the triggering click', async t => {
  let writes = 0;
  const server = http.createServer((req, res) => {
    if (req.method === 'POST') { writes++; res.end('saved'); return; }
    res.setHeader('content-type', 'text/html');
    res.end(`<button onclick="if(confirm('Save this note?'))fetch('/save',{method:'POST'}).then(()=>document.querySelector('main').textContent='Confirmed');else document.querySelector('main').textContent='Cancelled'">Save</button><main></main>`);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(root, 'profile') });
  t.after(async () => { await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const ctx = { config: { allowPrivateHosts: true, browserRuntimeV2: true }, settings: { headless: true } };
  const opened = await adapter.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}` }, ctx);
  let ref = /\[ref=([^\]]+)\] button Save/.exec(opened)[1];
  const click = () => adapter.execute({ action: 'act', op: 'click', ref }, ctx);
  const first = await click();
  assert.equal(first.status, 'uncertain');
  assert.equal(first.attention.dialog.type, 'confirm');
  assert.equal(writes, 0);
  const pending = await adapter.execute({ action: 'snapshot' }, ctx);
  assert.match(pending.output, /handle_dialog/);
  const dismissed = await adapter.execute({ action: 'handle_dialog', decision: 'dismiss' }, ctx);
  assert.equal(dismissed.status, 'executed');
  assert.equal(writes, 0);
  const current = await adapter.run({ action: 'snapshot' }, ctx);
  ref = /\[ref=([^\]]+)\] button Save/.exec(current)[1];
  assert.equal((await click()).status, 'uncertain');
  assert.equal((await adapter.execute({ action: 'handle_dialog', decision: 'accept' }, ctx)).status, 'executed');
  await adapter.page.waitForFunction(() => document.querySelector('main').textContent === 'Confirmed');
  assert.equal(writes, 1);
  console.log('DIALOG_CONFIRM_LIVE', JSON.stringify({ explicitDecisions: 2, writes, automaticReplay: false }));
});

test('dialog decisions use mutation approval and prompt input stays hidden in previews', () => {
  assert.equal(browser.needsApproval({ action: 'handle_dialog', decision: 'accept' }), true);
  assert.ok(!JSON.stringify(browser.display({ action: 'handle_dialog', decision: 'accept', prompt_text: 'private text' })).includes('private text'));
});

test('Chrome dialog handling uses the approved operation and refuses unsupported capabilities', async () => {
  const calls = [];
  const adapter = new ChromeBrowserAdapter({ has: () => true, findTool: () => ({}), callTool: async (name, args) => {
    calls.push({ name, args });
    if (name.endsWith('__list_pages')) return '1: Page (https://fixture.test/) [selected]\n# Open dialog\nprompt: Note.\nCall handle_dialog to handle it before continuing.';
    if (name.endsWith('__handle_dialog')) return 'Successfully accepted the dialog';
    return 'uid=1_1 button "Continue"';
  } });
  const result = await adapter.execute({ action: 'handle_dialog', decision: 'accept', prompt_text: 'fixture note' });
  assert.equal(result.status, 'executed');
  assert.equal(calls.find(call => call.name.endsWith('__handle_dialog')).args.promptText, 'fixture note');
  adapter.mcp.findTool = () => null;
  const unsupported = await adapter.execute({ action: 'handle_dialog', decision: 'dismiss' });
  assert.equal(unsupported.status, 'failed');
  assert.match(unsupported.error.message, /does not support.*dialog/i);
});

test('prompt input is explicit and a dialog inside a sequence leaves the suffix untouched', async t => {
  const server = http.createServer((_req, res) => {
    res.setHeader('content-type', 'text/html');
    res.end('<form><label>First<input oninput="prompt(\'A note?\')"></label><label>Second<input></label><button type="button">Save</button></form>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(root, 'prompt-profile') });
  t.after(async () => { await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const ctx = { config: { allowPrivateHosts: true, browserRuntimeV2: true }, settings: { headless: true } };
  await adapter.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}` }, ctx);
  const observation = adapter.observation;
  const ref = name => observation.controls.find(control => control.name === name).ref;
  const result = await adapter.execute({ action: 'sequence', observation_id: observation.id, steps: [
    { action: 'act', op: 'fill', ref: ref('First'), text: 'one' },
    { action: 'act', op: 'fill', ref: ref('Second'), text: 'two' },
    { action: 'act', op: 'click', ref: ref('Save') },
  ] }, ctx);
  assert.deepEqual(result.steps.map(step => step.status), ['uncertain', 'not_run', 'not_run']);
  assert.equal(result.attention.dialog.type, 'prompt');
  const invalid = await adapter.execute({ action: 'handle_dialog', decision: 'invented' }, ctx);
  assert.equal(invalid.status, 'failed');
  assert.equal((await adapter.execute({ action: 'handle_dialog', decision: 'accept', prompt_text: 'selected note' }, ctx)).status, 'executed');
  assert.equal(await adapter.page.locator('input').nth(0).inputValue(), 'one');
  assert.equal(await adapter.page.locator('input').nth(1).inputValue(), '');
});
