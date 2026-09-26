import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { runFileToolInWorker as run, shutdownFileToolWorkers } from '../../src/tooling/tool-worker.mjs';

async function fixture(t) {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-watchdog-'));
  t.after(() => { shutdownFileToolWorkers(); fs.rmSync(cwd, { recursive: true, force: true }); });
  fs.writeFileSync(path.join(cwd, 'bad.txt'), 'a'.repeat(20000) + '!');
  fs.writeFileSync(path.join(cwd, 'ok.txt'), 'healthy');
  await run('read_file', { path: 'ok.txt' }, { cwd });
  return cwd;
}
const bounded = promise => Promise.race([promise, new Promise((_, reject) => {
  const timer = setTimeout(() => reject(new Error('Test deadline: worker never settled')), 1500);
  promise.finally(() => clearTimeout(timer)).catch(() => {});
})]);
test('a pathological regex times out and queued reads recover', async t => {
  const cwd = await fixture(t);
  const hung = run('search_files', { path: 'bad.txt', pattern: '(a+)+$' }, { cwd, timeoutMs: 150 });
  const read = run('read_file', { path: 'ok.txt' }, { cwd });
  read.catch(() => {});
  await assert.rejects(bounded(hung), /inspection timed out/i);
  assert.match(await bounded(read), /healthy/);
});
test('Stop terminates a running regex and serves the next call', async t => {
  const cwd = await fixture(t), abort = new AbortController();
  const hung = run('search_files', { path: 'bad.txt', pattern: '(a+)+$' }, { cwd, signal: abort.signal });
  const read = run('read_file', { path: 'ok.txt' }, { cwd });
  read.catch(() => {});
  setTimeout(() => abort.abort(), 100);
  await assert.rejects(bounded(hung), /cancelled/i);
  assert.match(await bounded(read), /healthy/);
});
test('the worker preserves the explicit workspace boundary', async t => {
  const cwd = await fixture(t), nested = path.join(cwd, 'nested'); fs.mkdirSync(nested);
  assert.match(await run('read_file', { path: '../ok.txt' }, { cwd: nested, workspacePath: cwd }), /healthy/);
  await assert.rejects(run('read_file', { path: '../../outside.txt' }, { cwd: nested, workspacePath: cwd }), /workspace boundary/);
});
