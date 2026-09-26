import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { runFileToolInWorker, shutdownFileToolWorkers } from '../../src/tooling/tool-worker.mjs';

test('filesystem inspection runs without blocking the main event loop', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-scan-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  for (let i = 0; i < 100; i++) fs.writeFileSync(path.join(dir, `file-${i}.txt`), 'a'.repeat(5000));
  let completed = false;
  const scan = runFileToolInWorker('search_files', { pattern: 'missing', path: dir }, { cwd: dir });
  scan.then(() => { completed = true; });
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(completed, false, 'the main loop got a timer turn before inspection finished');
  assert.match(await scan, /No matches/);
});

test('cancelled inspection releases its worker and rejects promptly', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-cancel-scan-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  for (let i = 0; i < 10; i++) fs.writeFileSync(path.join(dir, `file-${i}.txt`), 'a'.repeat(5000));
  const abort = new AbortController();
  const scan = runFileToolInWorker('search_files', { pattern: 'missing', path: dir }, { cwd: dir, signal: abort.signal });
  abort.abort();
  await assert.rejects(scan, /cancelled/i);
});

/* --------------------- the resident worker stays correct ------------------ */

test('the worker is reused across calls and returns a correct result each time', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-reuse-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  fs.writeFileSync(path.join(dir, 'a.txt'), 'alpha');
  fs.writeFileSync(path.join(dir, 'b.txt'), 'beta');

  // A stale module cache would pin the first listing; re-reading proves the
  // worker is genuinely live between calls rather than a cached result.
  const first = await runFileToolInWorker('list_dir', { path: dir }, { cwd: dir });
  assert.match(first, /a\.txt/);
  fs.writeFileSync(path.join(dir, 'c.txt'), 'gamma');
  const second = await runFileToolInWorker('list_dir', { path: dir }, { cwd: dir });
  assert.match(second, /c\.txt/, 'the resident worker sees the filesystem change');

  const read = await runFileToolInWorker('read_file', { path: path.join(dir, 'b.txt') }, { cwd: dir });
  assert.match(read, /beta/, 'a different tool on the same worker still loads');
});

test('concurrent inspection calls each get their own answer', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-concurrent-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  for (let i = 0; i < 8; i++) fs.writeFileSync(path.join(dir, `f${i}.txt`), `content-${i}`);

  // A shared-request-id bug would cross the answers between callers.
  const results = await Promise.all(
    Array.from({ length: 8 }, (_, i) =>
      runFileToolInWorker('read_file', { path: path.join(dir, `f${i}.txt`) }, { cwd: dir })
    )
  );
  results.forEach((out, i) => assert.match(out, new RegExp(`content-${i}`)));
});

test('a tool error rejects that call without killing the worker', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-worker-error-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  await assert.rejects(
    runFileToolInWorker('read_file', { path: path.join(dir, 'missing.txt') }, { cwd: dir })
  );
  // The pool must survive a rejected call and serve the next one.
  fs.writeFileSync(path.join(dir, 'ok.txt'), 'recovered');
  const out = await runFileToolInWorker('read_file', { path: path.join(dir, 'ok.txt') }, { cwd: dir });
  assert.match(out, /recovered/);
});

test('cancelling one call leaves the worker usable for the next', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-cancel-reuse-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  fs.writeFileSync(path.join(dir, 'ok.txt'), 'still here');

  const abort = new AbortController();
  const cancelled = runFileToolInWorker('search_files', { pattern: 'zzz', path: dir }, { cwd: dir, signal: abort.signal });
  abort.abort();
  await assert.rejects(cancelled, /cancelled/i);

  const out = await runFileToolInWorker('read_file', { path: path.join(dir, 'ok.txt') }, { cwd: dir });
  assert.match(out, /still here/, 'the pool is not poisoned by the cancellation');
});

test('shutdown stops the worker and a later call transparently restarts it', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-restart-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  fs.writeFileSync(path.join(dir, 'ok.txt'), 'after restart');

  assert.match(await runFileToolInWorker('read_file', { path: path.join(dir, 'ok.txt') }, { cwd: dir }), /after restart/);
  shutdownFileToolWorkers();
  assert.match(await runFileToolInWorker('read_file', { path: path.join(dir, 'ok.txt') }, { cwd: dir }), /after restart/);
});

test('a non-inspection tool is refused before any worker is started', async () => {
  await assert.rejects(async () => runFileToolInWorker('run_command', { command: 'echo hi' }, { cwd: os.tmpdir() }),
    /Unsupported worker tool/);
});
