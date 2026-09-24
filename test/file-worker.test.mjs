import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { runFileToolInWorker } from '../src/tool-worker.mjs';

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
