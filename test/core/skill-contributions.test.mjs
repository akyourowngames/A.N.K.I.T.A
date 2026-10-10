import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { scaffoldSkill } from '../../src/skills/scaffold.mjs';
import { skillsDir } from '../../src/core/skills.mjs';

const url = new URL('../../src/skills/contributions.mjs', import.meta.url);
async function api() { assert.ok(fs.existsSync(url), 'skill contribution gate exists'); return import(url.href); }
function setup(t) { const root = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-gate-')); t.after(() => fs.rmSync(root, { recursive: true, force: true })); const dir = scaffoldSkill({ root, name: 'demo', example: 'Explain this example', permissions: ['files'] }); return { root, dir }; }

test('contribution gate accepts the scaffold and all bundled skills', async t => {
  const { checkSkillContributions } = await api();
  const { root } = setup(t);
  assert.deepEqual(checkSkillContributions(root), { checked: 1, errors: [] });
  const bundled = checkSkillContributions(skillsDir());
  assert.ok(bundled.checked > 0);
  assert.deepEqual(bundled.errors, []);
});

test('contribution gate rejects missing docs, invalid permission manifests and fixture drift', async t => {
  const { checkSkillContributions } = await api();
  const { root, dir } = setup(t);
  fs.writeFileSync(path.join(dir, 'plugin.json'), JSON.stringify({ version: 1, permissions: ['root'] }));
  assert.match(checkSkillContributions(root).errors.join('\n'), /permissions/);
  fs.rmSync(path.join(dir, 'plugin.json'));
  assert.match(checkSkillContributions(root).errors.join('\n'), /plugin.json/);
  fs.rmSync(path.join(dir, 'README.md'));
  assert.match(checkSkillContributions(root).errors.join('\n'), /README.md/);
  fs.appendFileSync(path.join(dir, 'SKILL.md'), 'Changed behavior.');
  assert.match(checkSkillContributions(root).errors.join('\n'), /output differs/);
});

test('the dedicated pull request gate has read-only permissions and runs real offline checks', () => {
  const file = new URL('../../.github/workflows/skills.yml', import.meta.url);
  assert.ok(fs.existsSync(file), 'skill pull request workflow exists');
  const workflow = fs.readFileSync(file, 'utf8');
  assert.match(workflow, /pull_request:/);
  assert.match(workflow, /contents: read/);
  assert.match(workflow, /node scripts\/check-skills.mjs/);
  assert.doesNotMatch(workflow, /pull_request_target|continue-on-error/);
});

test('contribution manifest and documentation cannot redirect reads outside the skill', async t => {
  const { checkSkillContributions } = await api();
  const { root, dir } = setup(t), realpath = fs.realpathSync;
  for (const file of ['plugin.json', 'README.md']) {
    const target = path.join(dir, file);
    const mocked = t.mock.method(fs, 'realpathSync', value => path.resolve(String(value)) === target ? path.join(root, 'outside', file) : realpath(value));
    assert.match(checkSkillContributions(root).errors.join('\n'), /artifact.*link/);
    mocked.mock.restore();
  }
});
