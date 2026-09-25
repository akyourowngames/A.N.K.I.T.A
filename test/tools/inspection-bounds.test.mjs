import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { run as search } from '../../tools/filesystem/search-files.mjs';
import { run as glob } from '../../tools/filesystem/glob.mjs';

test('project search and glob respect gitignore and skip generated directories', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-ignore-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  execFileSync('git', ['init'], { cwd: dir, stdio: 'ignore' });
  fs.writeFileSync(path.join(dir, '.gitignore'), 'private.txt\n');
  fs.writeFileSync(path.join(dir, 'private.txt'), 'secretneedle');
  fs.writeFileSync(path.join(dir, 'public.txt'), 'secretneedle');
  fs.mkdirSync(path.join(dir, 'node_modules'));
  fs.writeFileSync(path.join(dir, 'node_modules', 'noise.txt'), 'secretneedle');
  assert.match(search({ pattern: 'secretneedle' }, { cwd: dir }), /public\.txt/);
  assert.doesNotMatch(search({ pattern: 'secretneedle' }, { cwd: dir }), /private\.txt|noise\.txt/);
  assert.match(glob({ pattern: '**/*.txt' }, { cwd: dir }), /public\.txt/);
  assert.doesNotMatch(glob({ pattern: '**/*.txt' }, { cwd: dir }), /private\.txt|noise\.txt/);
});
