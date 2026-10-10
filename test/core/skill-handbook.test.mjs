import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { checkSkillFixtures } from '../../src/skills/fixtures.mjs';
import { checkSkillContributions } from '../../src/skills/contributions.mjs';
import { loadSkills } from '../../src/core/skills.mjs';
import { SKILL_FILE, MANIFEST_FILE, FIXTURE_DIR, FIXTURE_FILE, EXPECTED_FILE, SKILL_DOC_FILE } from '../../src/skills/layout.mjs';

const ARTIFACTS = [SKILL_FILE, MANIFEST_FILE, `${FIXTURE_DIR}/${FIXTURE_FILE}`, `${FIXTURE_DIR}/${EXPECTED_FILE}`, SKILL_DOC_FILE];
function copyExamples(text, root) {
  const examples = [...text.matchAll(/<!-- example: ([\w./-]+) -->\s*```[^\n]*\n([\s\S]*?)\n```/g)];
  assert.deepEqual(examples.map(([, file]) => file).sort(), [...ARTIFACTS].sort(), 'exactly five unique known artifacts');
  const folder = path.resolve(root, 'hello-skill');
  // Validate the entire PR-controlled path set before the first write.
  const targets = examples.map(([, file, content]) => {
    const target = path.resolve(folder, file);
    assert.ok(target.startsWith(folder + path.sep), 'artifact stays in its temporary skill folder');
    return { target, content };
  });
  for (const { target, content } of targets) {
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, content + '\n');
  }
}

test('the complete handbook example loads and passes its real golden fixture', t => {
  const guide = new URL('../../docs/guides/skill-author-handbook.md', import.meta.url);
  assert.ok(fs.existsSync(guide), 'skill-author handbook exists');
  const text = fs.readFileSync(guide, 'utf8');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-handbook-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  copyExamples(text, root);
  assert.equal(loadSkills(root)[0]?.name, 'hello-skill');
  assert.deepEqual(checkSkillFixtures(root), { checked: 1, errors: [] });
  assert.deepEqual(checkSkillContributions(root), { checked: 1, errors: [] });
  assert.match(text, /not.*sandbox/i);
});

test('handbook paths cannot escape the example or duplicate an artifact before writing', t => {
  const text = fs.readFileSync(new URL('../../docs/guides/skill-author-handbook.md', import.meta.url), 'utf8');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'handbook-paths-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  for (const file of ['../../victim.md', SKILL_FILE]) {
    assert.throws(() => copyExamples(text.replace('example: README.md', `example: ${file}`), root), /five unique known artifacts/);
    assert.deepEqual(fs.readdirSync(root), [], 'rejects before any write');
  }
});
