import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import * as patchTool from '../../tools/filesystem/apply-patch.mjs';

function workspace(t, files = {}) {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-patch-'));
  t.after(() => fs.rmSync(cwd, { recursive: true, force: true }));
  for (const [name, text] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(cwd, name)), { recursive: true });
    fs.writeFileSync(path.join(cwd, name), text);
  }
  return { cwd, read: name => fs.readFileSync(path.join(cwd, name), 'utf8') };
}

test('applies multiple hunks and files with exact original coordinates', t => {
  const w = workspace(t, { 'a.txt': 'one\ntwo\nthree\nfour\nfive\n', 'b.txt': 'old\n' });
  const result = patchTool.run({ patch: '--- a/a.txt\n+++ b/a.txt\n@@ -1,2 +1,3 @@\n one\n-two\n+TWO\n+extra\n@@ -4,2 +5,2 @@\n four\n-five\n+FIVE\n--- a/b.txt\n+++ b/b.txt\n@@ -1 +1 @@\n-old\n+new\n' }, w);
  assert.doesNotMatch(result, /^Error:/);
  assert.equal(w.read('a.txt'), 'one\nTWO\nextra\nthree\nfour\nFIVE\n');
  assert.equal(w.read('b.txt'), 'new\n');
});

test('creates nested files, deletes files, and moves files while editing', t => {
  const w = workspace(t, { 'old name.txt': 'before\n', 'remove.txt': 'gone\n' });
  const result = patchTool.run({ patch: 'diff --git a/old name.txt b/new name.txt\nsimilarity index 50%\nrename from old name.txt\nrename to new name.txt\n--- a/old name.txt\n+++ b/new name.txt\n@@ -1 +1 @@\n-before\n+after\ndiff --git a/remove.txt b/remove.txt\ndeleted file mode 100644\n--- a/remove.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n-gone\ndiff --git a/nested/new.txt b/nested/new.txt\nnew file mode 100644\n--- /dev/null\n+++ b/nested/new.txt\n@@ -0,0 +1 @@\n+hello\n' }, w);
  assert.doesNotMatch(result, /^Error:/);
  assert.equal(w.read('new name.txt'), 'after\n');
  assert.equal(w.read('nested/new.txt'), 'hello\n');
  assert.equal(fs.existsSync(path.join(w.cwd, 'old name.txt')), false);
  assert.equal(fs.existsSync(path.join(w.cwd, 'remove.txt')), false);
});

test('handles pure renames, quoted paths, and empty file creation/deletion', t => {
  const w = workspace(t, { 'old name.txt': 'same', 'empty': '' });
  const result = patchTool.run({ patch: 'diff --git "a/old name.txt" "b/new name.txt"\nsimilarity index 100%\nrename from old name.txt\nrename to new name.txt\ndiff --git a/empty b/empty\ndeleted file mode 100644\nindex e69de29..0000000\ndiff --git "a/new empty" "b/new empty"\nnew file mode 100644\nindex 0000000..e69de29\n' }, w);
  assert.doesNotMatch(result, /^Error:/);
  assert.equal(w.read('new name.txt'), 'same');
  assert.equal(w.read('new empty'), '');
  assert.equal(fs.existsSync(path.join(w.cwd, 'empty')), false);
});

test('preserves CRLF and correctly handles no-newline markers', t => {
  const w = workspace(t, { 'a': 'one\r\ntwo', 'b': 'old' });
  const result = patchTool.run({ patch: '--- a/a\n+++ b/a\n@@ -1,2 +1,2 @@\n one\n-two\n\\ No newline at end of file\n+TWO\n\\ No newline at end of file\n--- a/b\n+++ b/b\n@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new\n' }, w);
  assert.doesNotMatch(result, /^Error:/);
  assert.equal(w.read('a'), 'one\r\nTWO');
  assert.equal(w.read('b'), 'new\n');
});

test('validates every file before writing and rejects mismatched context', t => {
  const w = workspace(t, { a: 'old\n', b: 'actual\n' });
  const result = patchTool.run({ patch: '--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old\n+new\n--- a/b\n+++ b/b\n@@ -1 +1 @@\n-wrong\n+new\n' }, w);
  assert.match(result, /^Error:.*(context|match)/i);
  assert.equal(w.read('a'), 'old\n');
  assert.equal(w.read('b'), 'actual\n');
});

test('rejects traversal, absolute paths, binary data, and malformed hunks', t => {
  const w = workspace(t, { a: 'old\n' });
  for (const name of ['../escape', '/tmp/escape', 'C:/escape', 'dir/../../escape', 'dir\\..\\escape']) {
    assert.match(patchTool.run({ patch: `--- /dev/null\n+++ b/${name}\n@@ -0,0 +1 @@\n+bad\n` }, w), /^Error:/);
  }
  for (const patch of ['diff --git a/a b/a\nGIT binary patch\nliteral 1\nx\n', '--- a/a\n+++ b/a\n@@ -1,2 +1 @@\n-old\n+new\n', '--- a/a\n+++ b/a\n@@ -1 +7 @@\n-old\n+new\n']) {
    assert.match(patchTool.run({ patch }, w), /^Error:/);
  }
  assert.equal(w.read('a'), 'old\n');
});

test('rejects symlink parent directories', t => {
  const w = workspace(t);
  const outside = workspace(t, { a: 'outside\n' });
  fs.symlinkSync(outside.cwd, path.join(w.cwd, 'link'), 'junction');
  assert.match(patchTool.run({ patch: '--- a/link/a\n+++ b/link/a\n@@ -1 +1 @@\n-outside\n+bad\n' }, w), /^Error:.*(symlink|symbolic)/i);
  assert.equal(outside.read('a'), 'outside\n');
});

test('approval includes all changes and execution revalidates current files', t => {
  const w = workspace(t, { a: 'old\n' });
  const args = { patch: '--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old\n+new\n' };
  const ui = { bold: x => x, dim: x => x, red: x => x, diff: (a, b) => `${a} -> ${b}` };
  assert.match(patchTool.approval(args, w, ui), /old[\s\S]*new/);
  assert.equal(w.read('a'), 'old\n');
  fs.writeFileSync(path.join(w.cwd, 'a'), 'changed\n');
  assert.match(patchTool.run(args, w), /^Error:/);
  assert.equal(w.read('a'), 'changed\n');
});

test('rolls back all originals when a replacement fails', t => {
  const w = workspace(t, { a: 'old a\n', b: 'old b\n' });
  const rename = fs.renameSync;
  let failed = false;
  fs.renameSync = function (from, to) {
    if (!failed && to === path.join(w.cwd, 'b') && String(from).includes('.ankita-patch-')) {
      failed = true;
      throw new Error('injected replacement failure');
    }
    return rename.call(this, from, to);
  };
  t.after(() => { fs.renameSync = rename; });
  const result = patchTool.run({ patch: '--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old a\n+new a\n--- a/b\n+++ b/b\n@@ -1 +1 @@\n-old b\n+new b\n' }, w);
  assert.match(result, /^Error:.*injected replacement failure/);
  assert.equal(w.read('a'), 'old a\n');
  assert.equal(w.read('b'), 'old b\n');
  assert.deepEqual(fs.readdirSync(w.cwd).sort(), ['a', 'b']);
});

test('preserves executable permission and applies explicit mode changes on POSIX', { skip: process.platform === 'win32' }, t => {
  const w = workspace(t, { a: 'old\n', b: 'same\n' });
  fs.chmodSync(path.join(w.cwd, 'a'), 0o755);
  const result = patchTool.run({ patch: '--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old\n+new\ndiff --git a/b b/b\nold mode 100644\nnew mode 100755\n' }, w);
  assert.doesNotMatch(result, /^Error:/);
  assert.equal(fs.statSync(path.join(w.cwd, 'a')).mode & 0o777, 0o755);
  assert.equal(fs.statSync(path.join(w.cwd, 'b')).mode & 0o777, 0o755);
});

test('preserves CRLF in newly created files from a git diff', t => {
  const w = workspace(t);
  const result = patchTool.run({ patch: 'diff --git a/new.txt b/new.txt\nnew file mode 100644\n--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,2 @@\n+one\r\n+two\r\n' }, w);
  assert.doesNotMatch(result, /^Error:/);
  assert.equal(w.read('new.txt'), 'one\r\ntwo\r\n');
});

test('supports git octal quoted UTF-8 filenames', t => {
  const w = workspace(t, { 'caf\u00e9.txt': 'old\n' });
  const result = patchTool.run({ patch: 'diff --git "a/caf\\303\\251.txt" "b/caf\\303\\251.txt"\n--- "a/caf\\303\\251.txt"\n+++ "b/caf\\303\\251.txt"\n@@ -1 +1 @@\n-old\n+new\n' }, w);
  assert.doesNotMatch(result, /^Error:/);
  assert.equal(w.read('caf\u00e9.txt'), 'new\n');
});

test('rejects overwrite destinations, partial deletions, and binary source files', t => {
  const w = workspace(t, { old: 'original\n', existing: 'keep\n', binary: Buffer.from([0, 1, 2]) });
  for (const patch of [
    'diff --git a/old b/existing\nrename from old\nrename to existing\n',
    '--- a/old\n+++ /dev/null\n@@ -0,0 +0,0 @@\n',
    '--- a/binary\n+++ b/binary\n@@ -1 +1 @@\n-old\n+new\n',
  ]) assert.match(patchTool.run({ patch }, w), /^Error:/);
  assert.equal(w.read('old'), 'original\n');
  assert.equal(w.read('existing'), 'keep\n');
});

test('rollback restores deleted files and removes newly created directories', t => {
  const w = workspace(t, { a: 'one\n', b: 'two\n' });
  const unlink = fs.unlinkSync;
  fs.unlinkSync = function (p) {
    if (p === path.join(w.cwd, 'b')) throw new Error('injected deletion failure');
    return unlink.call(this, p);
  };
  t.after(() => { fs.unlinkSync = unlink; });
  const result = patchTool.run({ patch: '--- /dev/null\n+++ b/nested/deeper/new\n@@ -0,0 +1 @@\n+created\n--- a/a\n+++ /dev/null\n@@ -1 +0,0 @@\n-one\n--- a/b\n+++ /dev/null\n@@ -1 +0,0 @@\n-two\n' }, w);
  assert.match(result, /^Error:.*injected deletion failure/);
  assert.equal(w.read('a'), 'one\n');
  assert.equal(w.read('b'), 'two\n');
  assert.deepEqual(fs.readdirSync(w.cwd).sort(), ['a', 'b']);
});
