import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import net from 'node:net';
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { startDesktopDev } from '../../desktop/scripts/dev-server.mjs';

const HOST_REPORT = "process.stdout.write(process.env.ANKITA_DESKTOP_DEV_URL);setInterval(()=>{},1000)"; // Real child host fixture, no GUI or user profile.
const OPTIONS = { electronPath: process.execPath, electronArgs: ['-e', HOST_REPORT], stdio: ['ignore', 'pipe', 'pipe'], logLevel: 'silent' };
async function fixture(t) {
  // Vite resolves real paths for its serving allow list. The native call is
  // required: realpathSync alone leaves an 8.3 short temp path (C:\Users\RUNNER~1\...)
  // unchanged, and Vite then 403s its own renderer.
  const root = fs.realpathSync.native(fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-dev-launcher-')));
  const occupied = http.createServer((_req, res) => res.end('unrelated server'));
  await new Promise(resolve => occupied.listen(0, '127.0.0.1', resolve));
  fs.mkdirSync(path.join(root, 'desktop', 'renderer'), { recursive: true });
  fs.writeFileSync(path.join(root, 'desktop', 'renderer', 'index.html'), '<div id="root">owned renderer fixture</div>');
  fs.writeFileSync(path.join(root, 'desktop', 'vite.config.ts'), 'export default ' + JSON.stringify({
    root: path.join(root, 'desktop', 'renderer'), server: { host: '127.0.0.1', port: occupied.address().port, strictPort: true },
  }));
  const launched = [];
  t.after(async () => {
    for (const dev of launched) await dev.close();
    await new Promise(resolve => occupied.close(resolve));
    const target = fs.realpathSync.native(root), base = fs.realpathSync.native(os.tmpdir());
    assert.ok(target.startsWith(base + path.sep) && path.basename(target).startsWith('ankita-dev-launcher-'));
    fs.rmSync(target, { recursive: true, force: true });
  });
  return { start: async options => { const dev = await startDesktopDev({ ...OPTIONS, root, ...options }); launched.push(dev); return dev; } };
}
const canConnect = url => new Promise(resolve => {
  const parsed = new URL(url), socket = net.connect(Number(parsed.port), parsed.hostname);
  socket.once('connect', () => { socket.destroy(); resolve(true); });
  socket.once('error', () => resolve(false));
});
async function assertPortReleased(url) {
  // Windows can report a TCP connect before a retired listener's reset arrives.
  // Rebinding proves the old server no longer owns the port without that false positive.
  const parsed = new URL(url), replacement = net.createServer();
  await new Promise((resolve, reject) => {
    replacement.once('error', reject);
    replacement.listen(Number(parsed.port), parsed.hostname, resolve);
  });
  await new Promise(resolve => replacement.close(resolve));
}
test('two desktop renderer servers receive separate owned ports instead of conflicting across worktrees', async t => {
  const { start } = await fixture(t);
  const urls = [];
  for (const _ of [0, 1]) {
    const dev = await start();
    const [report] = await once(dev.electron.stdout, 'data');
    assert.equal(report.toString(), dev.url, 'the host receives its own actual renderer address');
    urls.push(dev.url);
  }
  assert.notEqual(urls[0], urls[1], 'each host must use the renderer it started');
  for (const url of urls) assert.match(await (await fetch(url)).text(), /id="root"/);
});

test('host exit releases its renderer port and explicit shutdown releases both owned processes', async t => {
  const { start } = await fixture(t);
  const dev = await start({ electronArgs: ['-e', 'process.exit(7)'] });
  assert.equal((await dev.closed).code, 7);
  await assertPortReleased(dev.url);
  const next = await start();
  try { assert.equal(await canConnect(next.url), true); }
  finally { await next.close(); }
  await assertPortReleased(next.url);
  assert.notEqual(next.electron.exitCode ?? next.electron.signalCode, null);
});

test('a host launch error closes the already-started renderer instead of leaving a dev server running', async t => {
  const { start } = await fixture(t);
  await assert.rejects(start({ electronPath: import.meta.filename + '.missing-executable' }), /ENOENT/);
});
