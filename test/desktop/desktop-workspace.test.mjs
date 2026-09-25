import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { changedFiles, fileDiff, recentArtifacts, captureToolFiles, completedFileDiffs } from '../../desktop/electron/workspace.mjs';

test('work review shows tracked and new files with real text diffs', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-review-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const git = (...args) => execFileSync('git', args, { cwd: dir, stdio: 'ignore' });
  git('init'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@example.test');
  fs.writeFileSync(path.join(dir, 'main.txt'), 'before\n');
  git('add', 'main.txt'); git('commit', '-m', 'initial');
  fs.writeFileSync(path.join(dir, 'main.txt'), 'after\n');
  fs.writeFileSync(path.join(dir, 'new.txt'), 'hello\n');
  fs.mkdirSync(path.join(dir, 'nested'));
  fs.writeFileSync(path.join(dir, 'nested', 'note.txt'), 'nested\n');
  const snapshot = await changedFiles(dir);
  assert.deepEqual(snapshot.files.map(item => item.path).sort(), ['main.txt', 'nested/note.txt', 'new.txt']);
  assert.match((await fileDiff(dir, 'main.txt')).diff, /-before\n\+after/);
  assert.match((await fileDiff(dir, 'new.txt')).diff, /\+hello/);
  await assert.rejects(fileDiff(dir, '../outside.txt'), /no longer in the changes list/);
});

test('artifact list includes only successful files within the workspace', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-artifacts-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  fs.writeFileSync(path.join(dir, 'created.txt'), 'ready');
  const items = recentArtifacts(dir, [
    { role: 'tool', name: 'write_file', args: { path: 'created.txt' }, result: 'Created', isError: false },
    { role: 'tool', name: 'write_file', args: { path: '../outside.txt' }, result: 'Created', isError: false },
    { role: 'tool', name: 'write_file', args: { path: 'missing.txt' }, result: 'Error: failed', isError: true },
  ]);
  assert.deepEqual(items.map(item => item.name), ['created.txt']);
});

test('file tool captures a readable diff even without Git', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-plain-review-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'main.txt');
  fs.writeFileSync(file, 'before\n');
  const captured = captureToolFiles('edit_file', { path: 'main.txt' }, dir);
  fs.writeFileSync(file, 'after\n');
  const [change] = completedFileDiffs(captured);
  assert.equal(change.path, file);
  assert.match(change.diff, /-before\n\+after/);
});
