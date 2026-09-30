import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { BrowserSessionManager } from '../tools/browser/session.mjs';
import { BrowserPluginStore } from '../src/integrations/browser-plugins.mjs';

const HOST = '127.0.0.1'; // Disposable local fixture, never an external account.
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-job-preview-'));
const server = http.createServer((request, response) => {
  response.setHeader('content-type', 'text/html');
  response.end(`<title>${request.url}</title><main>Profile ${request.url}</main><button>Read followers</button>`);
});
await new Promise(resolve => server.listen(0, HOST, resolve));
const base = `http://${HOST}:${server.address().port}`;
const store = new BrowserPluginStore(path.join(directory, 'plugins.json')).load(); store.setEnabled('isolated', true);
const manager = new BrowserSessionManager({ store });
const job = manager.createScope('job-preview-test', { mode: 'isolated', independentPreview: true, profile: path.join(directory, 'profile'), headless: true });
const context = { backgroundJob: true, browserThreadId: 'job-preview-test', config: { allowPrivateHosts: true }, authorizeNavigation: async () => true, authorizeRequest: async () => true };
try {
  assert.doesNotMatch(await job.run({ action: 'open', url: `${base}/one` }, context), /^Error/);
  const second = await job.run({ action: 'open', url: `${base}/two` }, context);
  const ref = second.match(/\[ref=([^\]]+)\] button Read followers/)?.[1]; assert.ok(ref);
  const before = await job.view(), first = before.tabs.find(tab => tab.url.endsWith('/one'));
  await job.selectTab(first.id);
  const watched = await job.view(); assert.ok(watched.screenshot); assert.ok(watched.tabs.find(tab => tab.active).url.endsWith('/one'));
  const workerRead = await job.run({ action: 'read' }, context);
  assert.match(workerRead, /Profile \/two/, 'Watching page one must not redirect the worker from page two');
  const proof = await job.view({ automation: true });
  assert.ok(proof.tabs.find(tab => tab.active).url.endsWith('/two'), 'Proof follows the worker target, not the watched tab');
  assert.notEqual(proof.screenshot, watched.screenshot);
  assert.doesNotMatch(await job.run({ action: 'act', op: 'click', ref }, context), /^Error/, 'Preview switching preserves the worker snapshot refs');
  console.log('LIVE_JOB_PREVIEW_SELECTION_OK: real Chromium; watched first tab; worker read and clicked second tab with its original ref');
} finally {
  await manager.close(); await new Promise(resolve => server.close(resolve));
  assert.equal(path.dirname(fs.realpathSync(directory)), fs.realpathSync(os.tmpdir()));
  fs.rmSync(directory, { recursive: true, force: true });
}
