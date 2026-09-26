import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { changedFiles, fileDiff, recentArtifacts, captureToolFiles, completedFileDiffs } from '../../desktop/electron/workspace.mjs';
import { isRawBrowserTool, rawBrowserStep } from '../../desktop/electron/engine.mjs';

test('raw MCP browser tools are recognized without claiming the built-in tool', () => {
  assert.equal(isRawBrowserTool('mcp__playwright__browser_navigate'), true);
  assert.equal(isRawBrowserTool('mcp__playwright__browser_take_screenshot'), true);
  assert.equal(isRawBrowserTool('browser'), false);
  assert.equal(isRawBrowserTool('mcp__ankita-chrome__take_snapshot'), false);
  assert.equal(isRawBrowserTool(''), false);
  assert.equal(rawBrowserStep('mcp__playwright__browser_navigate'), 'browser navigate');
});

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

test('artifact list surfaces browser screenshot receipts as images', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-shot-artifacts-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  fs.mkdirSync(path.join(dir, 'downloaded-images'), { recursive: true });
  const shot = path.join(dir, 'downloaded-images', 'browser-1.png');
  fs.writeFileSync(shot, Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x00]));
  const items = recentArtifacts(dir, [
    { role: 'tool', name: 'browser', args: { action: 'screenshot' }, result: JSON.stringify({ type: 'browser_screenshot', path: shot, bytes: 5, note: 'saved' }), isError: false },
    { role: 'tool', name: 'browser', args: { action: 'snapshot' }, result: 'Example page', isError: false },
  ]);
  assert.deepEqual(items.map(item => item.name), ['browser-1.png']);
});

test('artifact list surfaces raw MCP browser screenshots named in result text', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-mcp-shot-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  fs.mkdirSync(path.join(dir, '.playwright-mcp'), { recursive: true });
  fs.writeFileSync(path.join(dir, '.playwright-mcp', 'shot-1.png'), Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x00]));
  const items = recentArtifacts(dir, [
    { role: 'tool', name: 'mcp__playwright__browser_take_screenshot', args: {}, result: 'Screenshot saved to [.playwright-mcp/shot-1.png](.playwright-mcp/shot-1.png)', isError: false },
    { role: 'tool', name: 'mcp__playwright__browser_snapshot', args: {}, result: 'no image here', isError: false },
  ]);
  assert.deepEqual(items.map(item => item.name), ['shot-1.png']);
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
