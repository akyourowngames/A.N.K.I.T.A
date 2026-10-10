import fs from 'node:fs';
import path from 'node:path';
import { parseSkillFile, skillsDir } from '../core/skills.mjs';
import { renderSkill } from '../../tools/skills/skill.mjs';
import { SKILL_FILE, FIXTURE_DIR, FIXTURE_FILE } from './layout.mjs';
import { skillArtifactPath } from './artifacts.mjs';

export function skillFolders(root = skillsDir()) {
  return fs.readdirSync(root, { withFileTypes: true }).filter(entry => entry.isDirectory()).map(entry => entry.name).sort();
}

/** Executes the deterministic skill tool output offline; never executes contributed code. */
export function checkSkillFixtures(root = skillsDir()) {
  const errors = [];
  let checked = 0;
  for (const name of skillFolders(root)) {
    try {
      skillArtifactPath(root, [name], { directory: true });
      const skill = parseSkillFile(fs.readFileSync(skillArtifactPath(root, [name, SKILL_FILE]), 'utf8'), name);
      if (skill.error) throw new Error(skill.error);
      const fixtureDir = skillArtifactPath(root, [name, FIXTURE_DIR], { directory: true });
      const fixture = JSON.parse(fs.readFileSync(skillArtifactPath(root, [name, FIXTURE_DIR, FIXTURE_FILE]), 'utf8'));
      if (fixture.input?.name !== name) throw new Error('fixture input.name must match its skill');
      // A single basename prevents fixtures from reading arbitrary local files.
      if (typeof fixture.expectedFile !== 'string' || !fixture.expectedFile || /[\\/]/.test(fixture.expectedFile) || fixture.expectedFile === '.' || fixture.expectedFile === '..') throw new Error('invalid expectedFile');
      const expectedPath = skillArtifactPath(root, [name, FIXTURE_DIR, fixture.expectedFile]);
      const realDir = fs.realpathSync(fixtureDir);
      if (path.dirname(fs.realpathSync(expectedPath)) !== realDir) throw new Error('expectedFile escapes fixtures directory');
      const expected = fs.readFileSync(expectedPath, 'utf8').replace(/\r\n/g, '\n').trimEnd();
      if (renderSkill(skill) !== expected) throw new Error('rendered output differs from golden fixture');
      checked++;
    } catch (error) { errors.push(`${name}: ${error.message}`); }
  }
  return { checked, errors };
}
