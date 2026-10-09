import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';
import { IPC_CONTRACT } from '../../desktop/shared/version.mjs';

const STARTUP_TIMEOUT_MS = 10_000; // Milliseconds: fail a blank owned renderer without contacting providers or opening a user window.
const configFile = fileURLToPath(new URL('../../desktop/vite.config.ts', import.meta.url));
const version = JSON.parse(fs.readFileSync(new URL('../../package.json', import.meta.url), 'utf8')).version;
let vite, server, browser;

test.before(async () => {
  vite = await createServer({ configFile, server: { middlewareMode: true, hmr: false } });
  server = http.createServer((req, res) => vite.middlewares(req, res));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  browser = await chromium.launch({ headless: true });
});
test.after(async () => {
  await browser?.close(); await vite?.close(); server?.closeAllConnections();
  if (server?.listening) await new Promise(resolve => server.close(resolve));
});

for (const [surface, pathname, rootId] of [['main', '/', 'root'], ['island', '/island.html', 'island-root']]) {
  test(`the complete ${surface} renderer starts with its shipped CSP`, async t => {
    const page = await browser.newPage(), errors = [];
    t.after(() => page.close());
    page.on('pageerror', error => errors.push(error.stack || error.message));
    await page.addInitScript(({ version, contract }) => {
      const off = () => () => {};
      // Only the transport is replaced: actual entry HTML, CSP, imports and full
      // component tree run. No model or personal profile is part of this fixture.
      window.ankita = { onEvent: off, onMenuCommand: off, onUpdateEvent: off, onCursor: off,
        invoke: async action => action === 'islandSnapshot' ? { teammates: [], threads: [] } : action === 'initialize'
          ? { teammates: [], models: [], settings: { provider: 'fixture', model: '', username: '', tools: [] },
            preferences: { provider: 'fixture', model: '', appearance: 'graphite', profileSetupDone: true }, version, contract, chrome: 'inline', jobs: [] } : [],
        appAction: async () => false, updateAction: async () => false, windowAction: async () => false,
        islandAction: async () => false, openExternal: async () => false };
    }, { version, contract: IPC_CONTRACT });
    await page.goto(`http://127.0.0.1:${server.address().port}${pathname}`);
    const csp = await page.locator('meta[http-equiv="Content-Security-Policy"]').getAttribute('content');
    assert.ok(csp.includes("script-src 'self'"));
    assert.ok(!csp.includes("'unsafe-eval'"), 'fix import boundaries instead of weakening the desktop security policy');
    let mounted = false;
    try { await page.locator(`#${rootId} > *`).first().waitFor({ state: 'attached', timeout: STARTUP_TIMEOUT_MS }); mounted = true; } catch {}
    console.log('DESKTOP_STARTUP_CSP_LIVE', JSON.stringify({ surface, mounted, errors, transport: 'fixture', shippedHtml: true }));
    assert.equal(mounted, true, JSON.stringify(errors));
    assert.deepEqual(errors, []);
  });
}
