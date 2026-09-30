import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { McpManager } from '../src/integrations/mcp-manager.mjs';
import { CHROME_MCP_ID, chromeMcpCommand, BrowserPluginStore } from '../src/integrations/browser-plugins.mjs';
import { ChromeBrowserAdapter } from '../tools/browser/chrome.mjs';
import { PlaywrightBrowserAdapter } from '../tools/browser/playwright.mjs';
import { BrowserSessionManager } from '../tools/browser/session.mjs';
import { BrowserCredentials } from '../desktop/electron/browser-credentials.mjs';

const HOST = '127.0.0.1', MCP_TIMEOUT_MS = 25_000, NAVIGATION_TIMEOUT_MS = 5_000, POLL_MS = 50; // Disposable local fixture only.
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-job-isolation-'));
const mcp = new McpManager({ log() {} }), posts = [];
const server = http.createServer((request, response) => {
  response.setHeader('content-type', 'text/html');
  if (request.url.startsWith('/publish')) { posts.push(request.url); response.end('<title>Confirmed</title><main>Published once</main>'); return; }
  if (request.url.startsWith('/dialog')) { response.end('<title>Interrupted form</title><label>First field<input oninput="alert(\'Fixture interruption\')"></label><label>Second field<input></label>'); return; }
  response.end('<title>Job isolation</title><form action="/publish"><label>Message<input name="message"></label><label>Password<input type="password" name="password"></label><div role="checkbox" aria-checked="false" tabindex="0" onclick="this.setAttribute(\'aria-checked\',this.getAttribute(\'aria-checked\')===\'true\'?\'false\':\'true\')">Remember</div><button>Publish</button></form>');
});
await new Promise(resolve => server.listen(0, HOST, resolve));
const base = `http://${HOST}:${server.address().port}`;
const store = new BrowserPluginStore(path.join(directory, 'plugins.json')).load();
store.setEnabled('isolated', true); store.setEnabled('local', true);
const saved = { username: 'fixture-user', password: 'fixture-secret' }; // No real account or external submission.
const credentials = new BrowserCredentials({ store: { withCredentials: async (_key, use) => use({ ...saved }) }, requests: { request() { assert.fail('Job must not request credentials'); } }, emit() {} });
const manager = new BrowserSessionManager({ store, credentials,
  isolatedFactory: options => new PlaywrightBrowserAdapter(options),
  chromeFactory: (_mcp, options) => new ChromeBrowserAdapter(mcp, options),
});
const context = { config: { allowPrivateHosts: true }, browserThreadId: 'foreground', browserCredentialAllowed: true };
const ref = (snapshot, label) => snapshot.split('\n').find(line => line.includes(label) && line.includes('[ref='))?.match(/\[ref=([^\]]+)\]/)?.[1];
try {
  const bundled = chromeMcpCommand({ connection: 'profile' });
  await mcp.connect({ id: CHROME_MCP_ID, command: bundled.command, args: [...bundled.args, '--headless', `--user-data-dir=${path.join(directory, 'chrome')}`], hidden: true, initTimeoutMs: MCP_TIMEOUT_MS, requestTimeoutMs: MCP_TIMEOUT_MS });
  for (const mode of ['isolated', 'local']) {
    assert.doesNotMatch(String(await manager.run({ action: 'open', mode, url: base }, context)), /^Error/);
    const before = await manager.view(), userTab = before.tabs.find(tab => tab.active) || before.tabs[0];
    const scopeName = `job:${mode}`, scope = manager.createScope(scopeName, { mode, headless: true, profile: path.join(directory, `job-${mode}`) });
    const policy = [], jobContext = { ...context, backgroundJob: true, browserThreadId: scopeName,
      authorizeBrowser: async args => policy.push(args.action), authorizeNavigation: async url => { assert.equal(new URL(url).origin, base); },
    };
    assert.doesNotMatch(String(await scope.run({ action: 'open', url: base }, jobContext)), /^Error/);
    let snapshot = String(await scope.run({ action: 'snapshot' }, jobContext));
    assert.ok(ref(snapshot, 'Message'), snapshot);
    for (const op of ['fill', 'type']) {
      const refused = String(await scope.run({ action: 'act', op, ref: ref(snapshot, 'Password'), text: 'guessed-password' }, jobContext));
      assert.match(refused, /browser login.*credential_fields/); assert.match(refused, /No fields changed/);
      snapshot = refused;
    }
    console.log(`PRIVATE_PASSWORD_BACKEND_OK: ${mode}; generic fill/type rejected before typing`);
    if (mode === 'local') {
      const custom = String(await scope.run({ action: 'fill_form', fields: [{ ref: ref(snapshot, 'Remember'), text: 'true' }] }, jobContext));
      assert.match(custom, /Filled 1 fields/); snapshot = custom;
      console.log('CHROME_CUSTOM_TOGGLE_OK: real MCP ARIA checkbox fill retained');
    }
    if (mode === 'isolated') {
      const rawLogin = await scope.run({ action: 'login', website: base, credential_fields: [{ ref: ref(snapshot, 'Message'), credential: 'username' }, { ref: ref(snapshot, 'Password'), credential: 'password' }] }, jobContext);
      assert.doesNotMatch(rawLogin, /^Error/); const login = JSON.parse(rawLogin);
      assert.equal(login.status, 'filled'); assert.ok(!JSON.stringify(login).includes(saved.password));
      // Stored secrets have a submit guard. Posting is a separate fresh page;
      // this test never submits a password through a generic click action.
      assert.doesNotMatch(String(await scope.run({ action: 'open', url: base }, jobContext)), /^Error/);
      snapshot = String(await scope.run({ action: 'snapshot' }, jobContext));
      console.log('SAVED_JOB_LOGIN_OK: real isolated Chromium; selected refs filled; no password prompt or secret receipt');
    }
    const invalid = String(await scope.run({ action: 'fill_form', fields: [{ ref: ref(snapshot, 'Message'), text: 'must-not-write' }, { ref: ref(snapshot, 'Publish'), text: 'invalid' }] }, jobContext));
    assert.match(invalid, /No fields changed/); assert.match(invalid, /Fresh snapshot:/);
    assert.doesNotMatch(invalid, /must-not-write/);
    snapshot = invalid;
    console.log(`FILL_PREFLIGHT_BACKEND_OK: ${mode}; invalid batch rejected before any field write; fresh refs returned`);
    const fill = await scope.run({ action: 'fill_form', fields: [{ ref: ref(snapshot, 'Message'), text: `job-${mode}` }] }, jobContext);
    assert.doesNotMatch(String(fill), /^Error/);
    snapshot = String(await scope.run({ action: 'snapshot' }, jobContext));
    const clicked = String(await scope.run({ action: 'act', op: 'click', ref: ref(snapshot, 'Publish') }, jobContext));
    assert.doesNotMatch(clicked, /^Error/);
    const deadline = Date.now() + NAVIGATION_TIMEOUT_MS;
    while (posts.length < (mode === 'isolated' ? 1 : 2) && Date.now() < deadline) await delay(POLL_MS);
    assert.match(String(await scope.run({ action: 'read' }, jobContext)), /Published once/, `posts=${posts.length}; click=${clicked}`);
    const view = await scope.view(); assert.match(view.screenshot, /^data:image/);
    if (mode === 'local') assert.match(String(await scope.run({ action: 'close', tab: userTab.id }, jobContext)), /not.*owned|job/i);
    if (mode === 'local') {
      snapshot = String(await scope.run({ action: 'open', url: `${base}/dialog` }, jobContext));
      const interrupted = String(await scope.run({ action: 'fill_form', fields: [{ ref: ref(snapshot, 'First field'), text: 'first' }, { ref: ref(snapshot, 'Second field'), text: 'second' }] }, jobContext));
      assert.match(interrupted, /interrupted.*dialog/); assert.doesNotMatch(interrupted, /Filled 2 fields/);
      console.log('CHROME_INTERRUPTED_FORM_OK: real page dialog reports incomplete; no replay');
    }
    await manager.closeScope(scopeName);
    const after = await manager.view(); assert.ok(after.tabs.some(tab => tab.id === userTab.id && tab.url === userTab.url), `${mode} foreground page survived`);
    assert.ok(policy.includes('fill_form') && policy.includes('act'));
    if (mode === 'local') assert.equal(mcp.has(CHROME_MCP_ID), true);
    console.log(`JOB_BROWSER_ISOLATION_OK: ${mode}; real form submission + preview; user tab survives scope close`);
  }
  assert.equal(posts.length, 2);
  console.log('LIVE_JOB_BACKENDS_OK: Playwright + Chrome; posts=2; saved-login=1; shared connection preserved');
} finally {
  credentials.clear(); await manager.close(); await mcp.closeAll(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  assert.equal(path.dirname(fs.realpathSync(directory)), fs.realpathSync(os.tmpdir()), 'Cleanup stays inside the temporary directory');
  fs.rmSync(directory, { recursive: true, force: true });
}
