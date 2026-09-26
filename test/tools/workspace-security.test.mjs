import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { get } from '../../tools/index.mjs';

const ui = Object.fromEntries(['red', 'bold', 'dim', 'green', 'diff'].map(k => [k, (...s) => s.join('\n')]));
function fixture(t) {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-boundary-'));
  t.after(() => fs.rmSync(base, { recursive: true, force: true }));
  const cwd = path.join(base, 'workspace'), outside = path.join(base, 'outside');
  fs.mkdirSync(cwd); fs.mkdirSync(outside);
  fs.writeFileSync(path.join(outside, 'secret.txt'), 'secret original');
  fs.writeFileSync(path.join(cwd, 'a.txt'), 'original\n');
  return { cwd, outside, ctx: { cwd } };
}
const cases = [
  ['read_file', p => ({ path: path.join(p, 'secret.txt') })],
  ['list_dir', p => ({ path: p })],
  ['glob', p => ({ path: p, pattern: '**/*' })],
  ['search_files', p => ({ path: p, pattern: 'secret' })],
  ['edit_file', p => ({ path: path.join(p, 'secret.txt'), old_string: 'secret', new_string: 'bad' })],
  ['edit_lines', p => ({ path: path.join(p, 'secret.txt'), edits: [{ start_line: 1, end_line: 1, content: 'bad' }] })],
  ['write_file', p => ({ path: path.join(p, 'secret.txt'), content: 'bad' })],
  ['create_dir', p => ({ path: path.join(p, 'created') })],
  ['delete_file', p => ({ path: path.join(p, 'secret.txt') })],
  ['move_file', p => ({ source: path.join(p, 'secret.txt'), destination: 'moved.txt' })],
  ['move_file', p => ({ source: 'a.txt', destination: path.join(p, 'moved.txt') })],
];
for (const [name, args] of cases) test(`${name} refuses outside workspace paths`, async t => {
  const { outside, ctx } = fixture(t);
  await assert.rejects(async () => get(name).run(args(outside), ctx), /workspace|outside|boundary/i);
  assert.equal(fs.readFileSync(path.join(outside, 'secret.txt'), 'utf8'), 'secret original');
});
test('traversal, sibling-prefix paths, ADS and device names are refused', async t => {
  const { cwd, ctx } = fixture(t);
  for (const p of ['../outside/secret.txt', `${cwd}-sibling/a`, 'a.txt:stream', 'NUL', 'nested/CON.txt', 'a.txt.']) {
    await assert.rejects(async () => get('write_file').run({ path: p, content: 'bad' }, ctx), /workspace|unsafe|boundary/i);
  }
});
test('interior junctions cannot escape but a workspace root junction is supported', async t => {
  const { cwd, outside, ctx } = fixture(t);
  const link = path.join(cwd, 'link');
  fs.symlinkSync(outside, link, process.platform === 'win32' ? 'junction' : 'dir');
  for (const [name, args] of cases) await assert.rejects(async () => get(name).run(args(link), ctx), /symlink|junction|workspace/i);
  const rootLink = path.join(path.dirname(cwd), 'workspace-link');
  fs.symlinkSync(cwd, rootLink, process.platform === 'win32' ? 'junction' : 'dir');
  assert.match(await get('read_file').run({ path: 'a.txt' }, { cwd: rootLink }), /original/);
});
test('delete and move refuse both current directory and workspace root aliases', async t => {
  const { cwd } = fixture(t);
  const nested = path.join(cwd, 'nested'); fs.mkdirSync(nested);
  const ctx = { cwd: nested, workspacePath: cwd };
  for (const p of [cwd, nested, path.join(nested, '.')]) {
    await assert.rejects(async () => get('delete_file').run({ path: p, recursive: true }, ctx), /root|working directory/i);
    await assert.rejects(async () => get('move_file').run({ source: p, destination: 'moved' }, ctx), /root|working directory/i);
  }
});
const edits = [
  ['edit_file', { path: 'a.txt', old_string: 'original', new_string: 'approved' }],
  ['edit_lines', { path: 'a.txt', edits: [{ mode: 'replace', start_line: 1, end_line: 1, content: 'approved' }] }],
  ['write_file', { path: 'a.txt', content: 'approved\n' }],
  ['apply_patch', { patch: '--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-original\n+approved\n' }],
];
for (const [name, args] of edits) test(`${name} rejects a change made while waiting for approval`, async t => {
  const { cwd, ctx } = fixture(t);
  const detail = get(name).approval(args, ctx, ui);
  assert.doesNotMatch(detail, /Error:|provide edits|must be/);
  fs.writeFileSync(path.join(cwd, 'a.txt'), 'original\nunapproved addition\n');
  assert.match(await get(name).run(args, ctx), /changed|approval|reapprove/i);
  assert.equal(fs.readFileSync(path.join(cwd, 'a.txt'), 'utf8'), 'original\nunapproved addition\n');
});
for (const [name, args] of edits) test(`${name} executes its unchanged approved plan`, async t => {
  const { cwd, ctx } = fixture(t);
  get(name).approval(args, ctx, ui);
  assert.doesNotMatch(await get(name).run(args, ctx), /Error:/);
  assert.equal(fs.readFileSync(path.join(cwd, 'a.txt'), 'utf8'), 'approved\n');
});
test('git inventories cannot turn tracked symlinks into outside-file reads', async t => {
  const { cwd, outside, ctx } = fixture(t);
  const tracked = path.join(cwd, 'tracked'); fs.mkdirSync(tracked);
  fs.writeFileSync(path.join(tracked, 'secret.txt'), 'ordinary');
  execFileSync('git', ['init', '-q'], { cwd, windowsHide: true });
  execFileSync('git', ['add', 'tracked/secret.txt'], { cwd, windowsHide: true });
  fs.rmSync(tracked, { recursive: true });
  fs.symlinkSync(outside, tracked, process.platform === 'win32' ? 'junction' : 'dir');
  assert.match(await get('search_files').run({ pattern: 'secret original' }, ctx), /^No matches/);
  assert.doesNotMatch(await get('glob').run({ pattern: '**/secret.txt' }, ctx), /tracked/);
});
test('approval binds arguments and new-file absence', async t => {
  const { cwd, ctx } = fixture(t), tool = get('write_file');
  const args = { path: 'new.txt', content: 'approved' };
  tool.approval(args, ctx, ui);
  args.content = 'unapproved';
  assert.match(tool.run(args, ctx), /changed|approval/i);
  tool.approval({ path: 'new.txt', content: 'approved' }, ctx, ui);
  fs.writeFileSync(path.join(cwd, 'new.txt'), 'other writer');
  assert.match(tool.run({ path: 'new.txt', content: 'approved' }, ctx), /changed|approval/i);
  assert.equal(fs.readFileSync(path.join(cwd, 'new.txt'), 'utf8'), 'other writer');
});

test('a preexisting predictable staging symlink cannot redirect an approved write', async t => {
  const { cwd, outside, ctx } = fixture(t);
  const outsideFile = path.join(outside, 'secret.txt');
  const bait = path.join(cwd, `.a.txt.${process.pid}.tmp`);
  try { fs.symlinkSync(outsideFile, bait, 'file'); }
  catch (error) { if (error.code === 'EPERM') { t.skip('File symlinks require Windows developer mode'); return; } throw error; }
  const args = { path: 'a.txt', content: 'approved' }, tool = get('write_file');
  tool.approval(args, ctx, ui);
  await tool.run(args, ctx);
  assert.equal(fs.readFileSync(outsideFile, 'utf8'), 'secret original');
  assert.equal(fs.lstatSync(path.join(cwd, 'a.txt')).isSymbolicLink(), false);
  assert.equal(fs.readFileSync(path.join(cwd, 'a.txt'), 'utf8'), 'approved');
});
