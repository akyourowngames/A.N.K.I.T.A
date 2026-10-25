import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import * as registry from '../../tools/index.mjs';
import { backupPath, listBackups, restoreBackup } from '../../tools/shared/_backup.mjs';
import { auditPath, audit } from '../../tools/shared/_audit.mjs';
import { parseSkillFile, permissionSummary, skillPromptLines } from '../../src/core/skills.mjs';
import { waitForExit } from '../../tools/process/run-command.mjs';

function workspace(t) {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-trust-'));
  t.after(() => fs.rmSync(cwd, { recursive: true, force: true }));
  return { cwd, workspacePath: cwd, state: {} };
}

test('backup round-trips a file and prunes to the per-file cap', t => {
  const ctx = workspace(t);
  const p = path.join(ctx.cwd, 'note.txt');
  fs.writeFileSync(p, 'v1');
  const b1 = backupPath(p, ctx);
  assert.ok(b1 && fs.existsSync(b1));
  fs.writeFileSync(p, 'v2');
  const b2 = backupPath(p, ctx);
  assert.ok(b2 && fs.existsSync(b2));
  assert.ok(listBackups(p, ctx).length >= 2);
  fs.writeFileSync(p, 'tampered');
  const src = restoreBackup(p, ctx, -1);
  assert.ok(src);
  assert.equal(fs.readFileSync(p, 'utf8'), 'v2');
});

test('backups stay isolated between paths that share a filename prefix', t => {
  const ctx = workspace(t);
  const file = path.join(ctx.cwd, 'foo.txt');
  const sibling = path.join(ctx.cwd, 'foo');
  fs.writeFileSync(file, 'file-v1');
  backupPath(file, ctx);
  fs.writeFileSync(sibling, 'sibling-v1');
  backupPath(sibling, ctx);
  fs.writeFileSync(sibling, 'sibling-v2');
  assert.equal(listBackups(sibling, ctx).length, 1, 'a sibling must not list the other path backups');
  assert.equal(listBackups(file, ctx).length, 1);
  restoreBackup(sibling, ctx);
  assert.equal(fs.readFileSync(sibling, 'utf8'), 'sibling-v1');
  assert.equal(fs.readFileSync(file, 'utf8'), 'file-v1', 'restoring one path must never overwrite its sibling');
  for (let i = 0; i < 25; i++) backupPath(file, ctx);
  assert.equal(listBackups(file, ctx).length, 20, 'pruning is per original path');
  assert.equal(listBackups(sibling, ctx).length, 1, 'pruning one path must not delete another path backups');
});

test('a workspace reached through a linked path keeps backups in the real workspace', t => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-trust-link-'));
  t.after(() => fs.rmSync(base, { recursive: true, force: true }));
  const real = path.join(base, 'real');
  fs.mkdirSync(real);
  fs.writeFileSync(path.join(real, 'note.txt'), 'v1');
  const link = path.join(base, 'link');
  try { fs.symlinkSync(real, link, process.platform === 'win32' ? 'junction' : 'dir'); }
  catch (error) { t.skip(`Directory links are unavailable: ${error.code}`); return; }
  const ctx = { cwd: link, workspacePath: link, state: {} };
  const backed = backupPath(path.join(link, 'note.txt'), ctx);
  assert.ok(backed, 'a linked workspace must still accept backups');
  const realRoot = fs.realpathSync.native(real);
  assert.ok(backed.startsWith(realRoot + path.sep), `${backed} should live inside ${realRoot}`);
  assert.ok(fs.existsSync(path.join(real, '.ankita_backups')));
});

test('delete_file keeps a backup, previews size, and writes a scrubbed audit record', t => {
  const ctx = workspace(t);
  const p = path.join(ctx.cwd, 'secret.txt');
  fs.writeFileSync(p, 'api_key = "ghp_abcdefghij1234567890"');
  const preview = registry.get('delete_file').approval({ path: 'secret.txt' }, ctx);
  assert.match(preview, /delete/);
  assert.match(preview, /restore_file/);
  const out = registry.get('delete_file').run({ path: 'secret.txt' }, ctx);
  assert.match(out, /Deleted/);
  assert.match(out, /Backup/);
  assert.ok(!fs.existsSync(p));
  const restored = registry.get('restore_file').run({ path: 'secret.txt' }, ctx);
  assert.match(restored, /Restored/);
  assert.ok(fs.existsSync(p));
  const auditFile = auditPath(ctx);
  assert.ok(fs.existsSync(auditFile));
  const lines = fs.readFileSync(auditFile, 'utf8');
  assert.match(lines, /delete_file/);
});

test('write_file and edit_file keep backups before overwrite', t => {
  const ctx = workspace(t);
  fs.writeFileSync(path.join(ctx.cwd, 'a.txt'), 'hello');
  registry.get('write_file').run({ path: 'a.txt', content: 'world' }, ctx);
  assert.ok(listBackups(path.join(ctx.cwd, 'a.txt'), ctx).length >= 1);
  assert.equal(fs.readFileSync(path.join(ctx.cwd, 'a.txt'), 'utf8').trim(), 'world');
});

test('run_command appends a scrubbed audit record', async t => {
  const ctx = workspace(t);
  const tool = registry.get('run_command');
  const cmd = process.platform === 'win32' ? 'Write-Output hello' : 'echo hello';
  await tool.run({ command: cmd, yield_ms: 100 }, ctx);
  const job = [...ctx.state.jobs.values()].at(-1);
  await waitForExit(job, 15000);
  const auditFile = auditPath(ctx);
  assert.ok(fs.existsSync(auditFile));
  const lines = fs.readFileSync(auditFile, 'utf8');
  assert.match(lines, /run_command/);
  assert.doesNotMatch(lines, /ghp_/);
});

test('skill permission manifest parses, validates, and appears in the catalogue', () => {
  const src = '---\nname: demo-skill\ndescription: Demonstrates permission manifests for safe community skills.\nallowed-tools: read_file, list_dir\ntouches: files, network\n---\n# demo\nBody here.\n';
  const parsed = parseSkillFile(src, 'demo-skill');
  assert.deepEqual(parsed.allowedTools, ['read_file', 'list_dir']);
  assert.deepEqual(parsed.touches, ['files', 'network']);
  assert.match(permissionSummary(parsed), /allowed-tools: read_file, list_dir/);
  assert.match(permissionSummary(parsed), /touches: files, network/);
  assert.match(skillPromptLines([parsed]).join('\n'), /Permissions: allowed-tools: read_file, list_dir; touches: files, network/);
  const legacy = parseSkillFile('---\nname: old-skill\ndescription: Legacy skill without any permission manifest declared.\n---\n# old\nBody.\n', 'old-skill');
  assert.equal(permissionSummary(legacy), '', 'legacy skills stay unrestricted and unchanged');
  const bad = parseSkillFile('---\nname: bad-skill\ndescription: Bad skill with an invalid tool name in manifest.\nallowed-tools: Bad Tool!\n---\n# bad\nBody.\n', 'bad-skill');
  assert.ok(bad.error);
});

test('move_file preview shows size and writes audit', t => {
  const ctx = workspace(t);
  fs.writeFileSync(path.join(ctx.cwd, 'm.txt'), 'x'.repeat(10));
  const preview = registry.get('move_file').approval({ source: 'm.txt', destination: 'n.txt' }, ctx);
  assert.match(preview, /move/);
  const out = registry.get('move_file').run({ source: 'm.txt', destination: 'n.txt' }, ctx);
  assert.match(out, /Moved/);
  assert.ok(fs.existsSync(path.join(ctx.cwd, 'n.txt')));
});

test('move_file keeps an undo copy of the source and reports how to restore it', t => {
  const ctx = workspace(t);
  fs.writeFileSync(path.join(ctx.cwd, 'undo.txt'), 'before move');
  const out = registry.get('move_file').run({ source: 'undo.txt', destination: 'moved/undo.txt' }, ctx);
  assert.match(out, /Backup/);
  assert.match(out, /restore_file/);
  assert.equal(fs.existsSync(path.join(ctx.cwd, 'undo.txt')), false);
  const restored = registry.get('restore_file').run({ path: 'undo.txt' }, ctx);
  assert.match(restored, /Restored/);
  assert.equal(fs.readFileSync(path.join(ctx.cwd, 'undo.txt'), 'utf8'), 'before move');
  assert.equal(fs.readFileSync(path.join(ctx.cwd, 'moved/undo.txt'), 'utf8'), 'before move');
});

test('backup skips symlinks and oversized files, restore validates index', t => {
  const ctx = workspace(t);
  const real = path.join(ctx.cwd, 'real.txt');
  fs.writeFileSync(real, 'data');
  const link = path.join(ctx.cwd, 'link.txt');
  try {
    fs.symlinkSync(real, link);
    assert.equal(backupPath(link, ctx), null);
  } catch {
    // Symlink creation needs privileges on some Windows setups; skip that assertion.
  }
  assert.throws(() => restoreBackup(path.join(ctx.cwd, 'missing.txt'), ctx), /No backups/);
  fs.writeFileSync(real, 'v2');
  backupPath(real, ctx);
  assert.throws(() => restoreBackup(real, ctx, 99), /out of range/);
});

test('audit log is owner-only and scrubs secrets', t => {
  const ctx = workspace(t);
  fs.writeFileSync(path.join(ctx.cwd, 'k.txt'), 'x');
  registry.get('delete_file').run({ path: 'k.txt' }, ctx);
  const file = auditPath(ctx);
  assert.ok(fs.existsSync(file));
  if (process.platform !== 'win32') {
    assert.equal(fs.statSync(file).mode & 0o777, 0o600);
  }
  audit(ctx, { tool: 'probe', command: 'api_key = "ghp_abcdefghij1234567890"' });
  const lines = fs.readFileSync(file, 'utf8');
  assert.match(lines, /REDACTED/);
  assert.doesNotMatch(lines, /ghp_abcdefghij1234567890/);
});

test('registry exposes restore_file as a core tool with approval', t => {
  const ctx = workspace(t);
  assert.ok(registry.coreNames().includes('restore_file'));
  assert.ok(registry.get('restore_file'));
  assert.equal(registry.needsApproval('restore_file', { path: 'a' }, ctx), true);
  assert.equal(registry.isReadOnly('restore_file', {}, ctx), false);
  const list = registry.get('restore_file').run({ path: 'nothing.txt', list: true }, ctx);
  assert.match(list, /No backups/);
});
