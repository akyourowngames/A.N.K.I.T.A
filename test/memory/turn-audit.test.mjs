import test from 'node:test';
import assert from 'node:assert/strict';
import {
  AUDIT_MAX_BYTES,
  createTurnAudit,
  finishTurnAudit,
  noteFileEffects,
  noteToolUse,
} from '../../src/memory/turn-audit.mjs';
import { FILE_EFFECT_TOOLS } from '../../src/core/tool-effects.mjs';

const cwd = process.cwd();

test('tool names are capped and duplicates counted once', () => {
  const audit = createTurnAudit({ maxTools: 2 });
  noteToolUse(audit, 'read_file');
  noteToolUse(audit, 'read_file');
  noteToolUse(audit, 'git');
  noteToolUse(audit, 'web_search');
  assert.deepEqual(audit.tools, ['read_file', 'git']);
  assert.equal(audit.dropped, 1);
  assert.equal(audit.changed, false, 'read-only tools do not claim a change');
});

test('a file-effect tool marks the turn changed even before paths are known', () => {
  const audit = createTurnAudit();
  noteToolUse(audit, 'write_file');
  assert.equal(audit.changed, true);
  assert.ok(FILE_EFFECT_TOOLS.includes('write_file'));
});

test('paths are workspace-relative, deduped, and capped', () => {
  const audit = createTurnAudit({ maxFiles: 2 });
  noteFileEffects(audit, 'write_file', { path: 'src/a.js' }, cwd);
  noteFileEffects(audit, 'edit_file', { path: 'src/a.js', old: 'x', new: 'y' }, cwd);
  noteFileEffects(audit, 'write_file', { path: 'src/b.js' }, cwd);
  noteFileEffects(audit, 'write_file', { path: 'src/c.js' }, cwd);
  assert.deepEqual(audit.files, ['src/a.js', 'src/b.js']);
  assert.equal(audit.dropped, 1);
  assert.equal(audit.changed, true);
});

test('moves record both ends and patches record their files, without arguments or output', () => {
  const audit = createTurnAudit();
  noteFileEffects(audit, 'move_file', { source: 'old.js', destination: 'new.js', secret: 'do-not-store' }, cwd);
  noteFileEffects(audit, 'apply_patch', { patch: '--- a/src/x.js\n+++ b/src/x.js\n@@ -1 +1 @@\n-a\n+b\nrename from src/y.js\nrename to src/z.js\n' }, cwd);
  const output = finishTurnAudit(audit, { termination: 'model_answer', turnId: 'turn-1' });
  assert.deepEqual(output.files, ['old.js', 'new.js', 'src/x.js', 'src/y.js', 'src/z.js']);
  assert.equal(output.changed, true);
  assert.equal(output.turnId, 'turn-1');
  assert.equal(output.termination, 'model_answer');
  assert.doesNotMatch(JSON.stringify(output), /do-not-store/);
  assert.doesNotMatch(JSON.stringify(output), /-a\\n\+b/, 'patch contents stay out');
});

test('a finished audit fits the byte bound even with many long paths', () => {
  const audit = createTurnAudit({ maxFiles: 100, maxTools: 100 });
  for (let i = 0; i < 100; i++) noteFileEffects(audit, 'write_file', { path: `${'d'.repeat(180)}/${i}.js` }, cwd);
  for (let i = 0; i < 100; i++) noteToolUse(audit, `tool_${'n'.repeat(180)}_${i}`);
  const output = finishTurnAudit(audit, { termination: 'model_answer', turnId: 't' });
  const size = Buffer.byteLength(JSON.stringify(output), 'utf8');
  assert.ok(size <= AUDIT_MAX_BYTES, `expected <= ${AUDIT_MAX_BYTES}, got ${size}`);
  assert.ok(output.dropped > 0);
});

test('no audit means no work, and finish still returns a stable shape', () => {
  const output = finishTurnAudit(null);
  assert.deepEqual(output, { turnId: null, tools: [], files: [], changed: false, termination: null, dropped: 0 });
});
