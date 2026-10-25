import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  MAX_REPO_ROOT_DEPTH,
  findRepoRoot,
  isPathInside,
  normalizeProjectPath,
  resolveProjectForPath,
  suggestProjectForPath,
} from '../../src/memory/project-resolver.mjs';

const project = (id, value, extra = {}) => ({ id, name: id, path: value, ...extra });

test('a trailing separator is stripped and Windows paths are compared case-insensitively', () => {
  assert.equal(normalizeProjectPath('/work/app/', 'posix'), '/work/app');
  assert.equal(normalizeProjectPath('C:\\Work\\App\\', 'win32'), 'c:\\work\\app');
  assert.notEqual(normalizeProjectPath('/work/app', 'posix'), '/work/APP');
  assert.equal(normalizeProjectPath('', 'posix'), '');
});

test('containment respects the separator boundary, so foo never captures foobar', () => {
  assert.equal(isPathInside('/work/foo', '/work/foo', 'posix'), true, 'the root itself is inside');
  assert.equal(isPathInside('/work/foo', '/work/foo/src/a.js', 'posix'), true);
  assert.equal(isPathInside('/work/foo', '/work/foobar', 'posix'), false);
  assert.equal(isPathInside('/work/foo', '/work/foo/../other', 'posix'), false);
  assert.equal(isPathInside('C:\\work\\foo', 'C:\\WORK\\FOO\\src', 'win32'), true);
});

test('the longest matching project root wins over an enclosing project', () => {
  const projects = [project('outer', '/work/app'), project('inner', '/work/app/packages/ui')];
  const result = resolveProjectForPath(projects, '/work/app/packages/ui/src', { platform: 'posix' });
  assert.equal(result.reason, 'matched');
  assert.equal(result.project.id, 'inner');
});

test('archived projects never attach', () => {
  const projects = [project('old', '/work/app', { archived: true })];
  assert.deepEqual(resolveProjectForPath(projects, '/work/app/src', { platform: 'posix' }).reason, 'none');
});

test('two roots of equal length are ambiguous, not guessed', () => {
  const tied = [project('one', '/work/app'), project('two', '/work/app')];
  const result = resolveProjectForPath(tied, '/work/app/x', { platform: 'posix' });
  assert.equal(result.reason, 'ambiguous');
  assert.deepEqual(result.candidates.map(item => item.id), ['one', 'two']);
  assert.equal(result.project, null);
});

test('a folder outside every project reports none', () => {
  const projects = [project('app', '/work/app')];
  assert.deepEqual(resolveProjectForPath(projects, '/elsewhere', { platform: 'posix' }), { project: null, reason: 'none', candidates: [] });
});

test('repo discovery walks up to a .git file or directory and stops at the depth limit', (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-repo-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const nested = path.join(root, 'a', 'b', 'c');
  fs.mkdirSync(nested, { recursive: true });
  fs.writeFileSync(path.join(root, '.git'), 'gitdir: elsewhere');
  assert.equal(findRepoRoot(nested), root);
  assert.equal(findRepoRoot(root, { maxDepth: 0 }), root);
  assert.equal(findRepoRoot(path.join(root, 'a')), root);
  assert.equal(MAX_REPO_ROOT_DEPTH, 12);

  const bare = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-norepo-'));
  t.after(() => fs.rmSync(bare, { recursive: true, force: true }));
  assert.equal(findRepoRoot(bare), null);
});

test('an untracked repo suggests a project from its root, but never the home directory', (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-suggest-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const workspace = path.join(root, 'Project One');
  fs.mkdirSync(path.join(workspace, '.git'), { recursive: true });
  assert.deepEqual(suggestProjectForPath(workspace, { home: root }), { name: 'Project One', path: workspace });
  assert.equal(suggestProjectForPath(workspace, { home: workspace }), null);
  assert.equal(suggestProjectForPath(path.join(root, 'plain'), { home: root }), null);
});
