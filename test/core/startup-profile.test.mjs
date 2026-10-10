import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';

const url = new URL('../../src/core/startup-profile.mjs', import.meta.url);
async function api() { assert.ok(fs.existsSync(url), 'startup profiler exists'); return import(url.href); }

test('profile sorts measured milliseconds and bounds retained entries without error payloads', async () => {
  const { StartupProfile } = await api();
  let now = 0;
  const profile = new StartupProfile({ now: () => now, limit: 2 });
  now = 7; profile.finish('skill', 'fast', 0, 'ready');
  now = 20; profile.finish('plugin', 'slow', 0, 'error');
  assert.equal(profile.snapshot()[0].durationMs, 20);
  profile.finish('skill', 'new', 19, 'ready');
  assert.equal(profile.snapshot().length, 2);
  assert.match(profile.format(), /slow.*20.*ms.*error/);
  assert.match(profile.format(), /mcp disable slow/);
});

test('real skill loading records successful and malformed entries and cache hits do not replace timings', async t => {
  const { startupProfile } = await api();
  const { loadSkills, reloadSkills } = await import('../../src/core/skills.mjs');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'startup-skills-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  for (const name of ['good', 'bad']) fs.mkdirSync(path.join(root, name));
  fs.writeFileSync(path.join(root, 'good', 'SKILL.md'), '---\nname: good\ndescription: Explain the current example clearly.\n---\nFollow the user.');
  fs.writeFileSync(path.join(root, 'bad', 'SKILL.md'), 'invalid');
  startupProfile.clear(); reloadSkills(); loadSkills(root);
  const records = startupProfile.snapshot();
  assert.equal(records.find(r => r.name === 'good')?.status, 'ready');
  assert.equal(records.find(r => r.name === 'bad')?.status, 'error');
  loadSkills(root); assert.deepEqual(startupProfile.snapshot(), records);
});

test('a real MCP HTTP handshake and a failed connection both produce plugin startup timings', async t => {
  const { startupProfile } = await api();
  const { McpManager } = await import('../../src/integrations/mcp-manager.mjs');
  const server = http.createServer(async (req, res) => {
    let body = ''; for await (const chunk of req) body += chunk;
    const call = JSON.parse(body);
    if (!call.id) { res.writeHead(202); res.end(); return; }
    const result = call.method === 'initialize' ? { protocolVersion: '2025-03-26', capabilities: { tools: {} }, serverInfo: { name: 'timing-fixture', version: '1' } } : { tools: [] };
    res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ jsonrpc: '2.0', id: call.id, result }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const manager = new McpManager();
  t.after(async () => { await manager.closeAll(); await new Promise(resolve => server.close(resolve)); });
  await manager.connect({ id: 'timing-fixture', transport: 'http', url: `http://127.0.0.1:${server.address().port}` });
  assert.equal(startupProfile.snapshot().find(r => r.name === 'timing-fixture')?.status, 'ready');
  await assert.rejects(manager.connect({ id: 'failed-fixture', command: 'missing-ankita-timing-fixture' }));
  assert.equal(startupProfile.snapshot().find(r => r.name === 'failed-fixture')?.status, 'error');
});

test('desktop startup report uses the same live measurements', async () => {
  await api();
  const { DesktopEngine } = await import('../../desktop/electron/engine.mjs');
  assert.equal(typeof DesktopEngine.prototype.getStartupProfile, 'function');
  assert.match(DesktopEngine.prototype.getStartupProfile.call({}), /Startup timings/);
});
