import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { checkSkillFixtures } from '../../src/skills/fixtures.mjs';

const apiUrl = new URL('../../src/skills/scaffold.mjs', import.meta.url);
async function api() { assert.ok(fs.existsSync(apiUrl), 'skill scaffolder exists'); return import(apiUrl.href); }
function root(t) { const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-scaffold-')); t.after(() => fs.rmSync(dir, { recursive: true, force: true })); return dir; }

test('scaffold creates a loadable documented skill with advisory manifest and passing golden output', async t => {
  const { scaffoldSkill } = await api();
  const dir = root(t);
  const result = scaffoldSkill({ root: dir, name: 'explain-log', permissions: ['files'], example: 'Explain this error log.' });
  assert.equal(path.basename(result), 'explain-log');
  assert.deepEqual(checkSkillFixtures(dir), { checked: 1, errors: [] });
  const manifest = JSON.parse(fs.readFileSync(path.join(result, 'plugin.json'), 'utf8'));
  assert.deepEqual(manifest.permissions, ['files']);
  assert.match(fs.readFileSync(path.join(result, 'README.md'), 'utf8'), /Explain this error log/);
  assert.throws(() => scaffoldSkill({ root: dir, name: 'explain-log', example: 'Other input' }), /exists/);
});

test('scaffold rejects traversal, invalid permissions and empty or multiline frontmatter input before writing', async t => {
  const { scaffoldSkill } = await api();
  const dir = root(t);
  for (const input of [{ name: '../escape', example: 'Hi' }, { name: 'demo', permissions: ['root'], example: 'Hi' }, { name: 'demo', example: '' }]) {
    assert.throws(() => scaffoldSkill({ root: dir, ...input }));
    assert.deepEqual(fs.readdirSync(dir), []);
  }
  scaffoldSkill({ root: dir, name: 'demo', example: 'Explain this\n---\nname: injected' });
  assert.deepEqual(checkSkillFixtures(dir).errors, []);
});

test('new skill works through the real CLI before provider login', async t => {
  const dir = root(t);
  const result = execFileSync(process.execPath, ['chat.mjs', 'new', 'skill', 'offline-demo', '--permissions', 'files', '--example', 'Explain this example', '--directory', dir], { encoding: 'utf8', env: { ...process.env, CONFIG_DIR: dir }, timeout: 10000 });
  assert.match(result, /Created skill/);
  assert.deepEqual(checkSkillFixtures(dir).errors, []);
});

test('interactive scaffolder asks exactly the three author questions', async t => {
  assert.ok(fs.existsSync(new URL('../../src/core/local-commands.mjs', import.meta.url)), 'local commands exist');
  const { runLocalCommand } = await import('../../src/core/local-commands.mjs');
  const dir = root(t), prompts = [], answers = ['interactive-demo', 'files,browser', 'Explain the current page'];
  assert.equal(await runLocalCommand(['new', 'skill', '--directory', dir], { ask: async q => { prompts.push(q); return answers.shift(); }, write: () => {} }), true);
  assert.equal(prompts.length, 3);
  assert.deepEqual(checkSkillFixtures(dir).errors, []);
});
