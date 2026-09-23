import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { spawn, spawnSync } from 'node:child_process';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-dev-tools-'));
process.env.CONFIG_DIR = root;
test.after(() => fs.rmSync(root, { recursive: true, force: true }));
const { Agent } = await import('../src/agent.mjs');
const registry = await import('../tools/index.mjs');
const call = (name, args) => ({ id: 'call-1', type: 'function', function: { name, arguments: JSON.stringify(args) } });

test('Agent gates Git mutations by action and executes read-only Git without prompting', async () => {
  const cwd = fs.mkdtempSync(path.join(root, 'git-'));
  assert.equal(spawnSync('git', ['init', cwd], { windowsHide: true }).status, 0);
  fs.writeFileSync(path.join(cwd, 'file.txt'), 'data');
  const previews = [];
  let allow = false;
  const agent = new Agent({ client: {}, config: { tools: true }, confirm: async (_name, detail) => { previews.push(detail); return allow; } });
  agent.cwd = cwd;
  assert.doesNotMatch(await agent.runToolCall(call('git', { action: 'status' })), /Error:|denied/);
  assert.equal(previews.length, 0);
  assert.match(await agent.runToolCall(call('git', { action: 'stage', paths: ['file.txt'] })), /denied/);
  assert.match(previews[0], /git.*add/);
  assert.equal(spawnSync('git', ['-C', cwd, 'diff', '--cached', '--name-only'], { encoding: 'utf8', windowsHide: true }).stdout, '');
  allow = true;
  assert.doesNotMatch(await agent.runToolCall(call('git', { action: 'stage', paths: ['file.txt'] })), /Error:|denied/);
  assert.match(spawnSync('git', ['-C', cwd, 'diff', '--cached', '--name-only'], { encoding: 'utf8', windowsHide: true }).stdout, /file.txt/);
});

test('Agent blocks denied HTTP writes before network access; displays no outgoing credentials', async t => {
  let gets = 0, posts = 0;
  const server = http.createServer((req, res) => { if (req.method === 'GET') gets++; else posts++; res.end('ok'); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  const url = `http://127.0.0.1:${server.address().port}/?key=secret-value`;
  const previews = [];
  const agent = new Agent({ client: {}, config: { tools: true }, confirm: async (_name, detail) => { previews.push(detail); return false; } });
  assert.match(await agent.runToolCall(call('http_request', { url })), /"status":200/);
  const args = { url, method: 'POST', auth: { type: 'bearer', token: 'secret-value' }, json: { secret: 'secret-value' } };
  assert.match(await agent.runToolCall(call('http_request', args)), /denied/);
  assert.equal(gets, 1); assert.equal(posts, 0);
  assert.doesNotMatch(previews[0], /secret-value/);
  assert.doesNotMatch(JSON.stringify(registry.displayArgs('http_request', args)), /secret-value/);
  assert.doesNotMatch(JSON.stringify(registry.displayArgs('http_request', '{bad secret-value')), /secret-value/);
});

test('Agent auto-approval still prepares a process identity snapshot before terminating it', async t => {
  const child = spawn(process.execPath, ['-e', 'setInterval(()=>{},1000)'], { windowsHide: true, stdio: 'ignore' });
  t.after(() => { try { child.kill(); } catch {} });
  await new Promise(resolve => child.once('spawn', resolve));
  const agent = new Agent({ client: {}, config: { tools: true, autoApprove: true }, confirm: () => assert.fail('auto approval should not prompt') });
  const result = await agent.runToolCall(call('kill_process', { pid: child.pid, force: true }));
  assert.doesNotMatch(result, /Error:|denied|snapshot.*required/i);
  if (child.exitCode === null && child.signalCode === null) await new Promise(resolve => child.once('close', resolve));
});

test('new core tools are available, Git/process schemas are deferred, and metadata depends on action', () => {
  const names = registry.coreNames();
  for (const name of ['apply_patch', 'http_request', 'job_input', 'job_wait']) assert.ok(names.includes(name));
  for (const name of ['git', 'port_status', 'kill_process', 'fetch_url']) assert.ok(!names.includes(name));
  assert.ok(registry.get('fetch_url'), 'old saved transcripts retain their legacy tool');
  assert.equal(registry.isReadOnly('git', { action: 'status' }), true);
  assert.equal(registry.isReadOnly('git', { action: 'commit' }), false);
  assert.equal(registry.needsApproval('git', { action: 'checkout' }), true);
  assert.equal(registry.isReadOnly('http_request', { method: 'POST' }), false);
  assert.equal(registry.needsApproval('http_request', { method: 'GET' }), false);
});
