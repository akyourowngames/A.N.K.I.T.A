import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-observation-'));
process.env.CONFIG_DIR = path.join(directory, 'config');
const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
const { ChromeBrowserAdapter } = await import('../../tools/browser/chrome.mjs');
test.after(() => fs.rmSync(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));

test('live observations expose covered/inert controls, editable types and safe form context', async t => {
  const server = http.createServer((_req, res) => { res.setHeader('content-type', 'text/html'); res.end(`
    <form aria-label="Delivery"><label>Address<input value="observed address"></label>
    <label>Secret<input type="password" value="do-not-expose"></label><label>Attachment<input type="file"></label></form>
    <div style="position:relative;width:200px;height:40px"><button>Covered</button><div style="position:absolute;inset:0;background:white">Overlay</div></div>
    <div inert><button>Inactive</button></div><button>Available</button>`); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(directory, 'profile') });
  t.after(async () => { await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const ctx = { config: { allowPrivateHosts: true, browserRuntimeV2: true }, settings: { headless: true } };
  await adapter.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}` }, ctx);
  const observation = await adapter.observe({}, ctx);
  const control = name => observation.controls.find(item => item.name === name);
  assert.equal(control('Covered').actionable, false);
  assert.equal(control('Inactive').actionable, false);
  assert.equal(control('Available').actionable, true);
  assert.equal(control('Attachment').editable, false);
  assert.equal(control('Address').editable, true);
  assert.equal(control('Address').states.value, 'observed address');
  assert.equal(control('Address').group.name, 'Delivery');
  assert.equal(control('Secret').states.value, '[hidden]');
  assert.ok(!JSON.stringify(observation).includes('do-not-expose'));
  const projection = await adapter.execute({ action: 'snapshot' }, ctx);
  assert.match(projection.output, /button Covered \(actionable=false\)/);
  assert.match(projection.output, /button Inactive \(inert, actionable=false\)/);
  assert.match(projection.output, /group="Delivery"/);
  console.log('OBSERVATION_STATE_LIVE', JSON.stringify({ covered: control('Covered').actionable, fileEditable: control('Attachment').editable, form: control('Address').group.name, passwordMasked: true }));
});

test('Chrome reports missing page-text capability and refuses its operation before dispatch', async () => {
  let evaluations = 0;
  const adapter = new ChromeBrowserAdapter({ has: () => true, findTool: name => name.endsWith('__evaluate_script') ? null : {}, callTool: async name => {
    if (name.endsWith('__list_pages')) return '1: Page (https://fixture.test/) [selected]';
    if (name.endsWith('__evaluate_script')) { evaluations++; return '{}'; }
    return 'uid=1_1 button "Read"';
  } });
  const observation = await adapter.observe();
  assert.equal(observation.capabilities.pageTextSearch, false);
  const result = await adapter.execute({ action: 'find', query: 'text' });
  assert.equal(result.status, 'failed');
  assert.match(result.error.message, /does not support.*page text/i);
  assert.equal(evaluations, 0);
});
