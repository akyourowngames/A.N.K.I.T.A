import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const moduleUrl = new URL('../../src/skills/fixtures.mjs', import.meta.url);
const source = '---\nname: demo\ndescription: Explain the selected example clearly.\n---\n# Demo\nRead before changing anything.\n';
const expected = '# Skill: demo\n---\n# Demo\nRead before changing anything.';

async function fixtureApi() {
  assert.ok(fs.existsSync(moduleUrl), 'offline skill fixture runner exists');
  return import(moduleUrl.href);
}
function setup(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-golden-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const dir = path.join(root, 'demo');
  fs.mkdirSync(path.join(dir, 'fixtures'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'SKILL.md'), source);
  fs.writeFileSync(path.join(dir, 'fixtures', 'skill.json'), JSON.stringify({ input: { name: 'demo' }, expectedFile: 'expected.md' }));
  fs.writeFileSync(path.join(dir, 'fixtures', 'expected.md'), expected);
  return { root, dir };
}

test('golden fixtures compare real rendered skill output and catch changed instructions', async t => {
  const { checkSkillFixtures } = await fixtureApi();
  const { root, dir } = setup(t);
  assert.deepEqual(checkSkillFixtures(root), { checked: 1, errors: [] });
  fs.appendFileSync(path.join(dir, 'SKILL.md'), 'Different behavior.');
  assert.match(checkSkillFixtures(root).errors.join('\n'), /demo.*output differs/);
});

test('fixtures reject missing records, malformed skills and escaping expected paths', async t => {
  const { checkSkillFixtures } = await fixtureApi();
  const { root, dir } = setup(t);
  const file = path.join(dir, 'fixtures', 'skill.json');
  fs.writeFileSync(file, JSON.stringify({ input: { name: 'demo' }, expectedFile: '../../outside.md' }));
  assert.match(checkSkillFixtures(root).errors.join('\n'), /expectedFile/);
  fs.rmSync(file);
  assert.match(checkSkillFixtures(root).errors.join('\n'), /demo/);
  fs.writeFileSync(path.join(dir, 'SKILL.md'), 'invalid');
  assert.match(checkSkillFixtures(root).errors.join('\n'), /frontmatter/);
});

test('every bundled skill has a passing offline golden fixture', async () => {
  const { checkSkillFixtures } = await fixtureApi();
  const { skillsDir } = await import('../../src/core/skills.mjs');
  const result = checkSkillFixtures(skillsDir());
  assert.ok(result.checked > 0);
  assert.deepEqual(result.errors, []);
});

test('a real fixture-directory link outside the skill is rejected', async t => {
  const { checkSkillFixtures } = await fixtureApi();
  const { root, dir } = setup(t);
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'outside-fixtures-'));
  t.after(() => fs.rmSync(outside, { recursive: true, force: true }));
  fs.renameSync(path.join(dir, 'fixtures'), path.join(outside, 'fixtures'));
  fs.symlinkSync(path.join(outside, 'fixtures'), path.join(dir, 'fixtures'), process.platform === 'win32' ? 'junction' : 'dir');
  assert.match(checkSkillFixtures(root).errors.join('\n'), /artifact.*link|artifact.*escape/);
  console.log('FIXTURE_LINK_LIVE realDirectoryLink=true outsideRootRejected=true');
});

test('skill source, fixture JSON and expected file links are rejected before reading', async t => {
  const { checkSkillFixtures } = await fixtureApi();
  const { root, dir } = setup(t);
  const realpath = fs.realpathSync;
  for (const file of ['SKILL.md', path.join('fixtures', 'skill.json'), path.join('fixtures', 'expected.md')]) {
    const target = path.join(dir, file);
    const mocked = t.mock.method(fs, 'realpathSync', value => path.resolve(String(value)) === target ? path.join(root, 'outside', file) : realpath(value));
    assert.match(checkSkillFixtures(root).errors.join('\n'), /artifact.*link/);
    mocked.mock.restore();
  }
});
