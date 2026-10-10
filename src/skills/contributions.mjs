import fs from 'node:fs';
import { skillsDir } from '../core/skills.mjs';
import { validatePalette } from '../palette/index.mjs';
import { checkSkillFixtures, skillFolders } from './fixtures.mjs';
import { MANIFEST_FILE, MANIFEST_VERSION, PERMISSION_KINDS, SKILL_DOC_FILE } from './layout.mjs';
import { skillArtifactPath } from './artifacts.mjs';

export function checkSkillContributions(root = skillsDir()) {
  const fixtures = checkSkillFixtures(root);
  const errors = [...fixtures.errors];
  for (const name of skillFolders(root)) {
    try {
      const manifest = JSON.parse(fs.readFileSync(skillArtifactPath(root, [name, MANIFEST_FILE]), 'utf8'));
      if (manifest.version !== MANIFEST_VERSION) throw new Error(`manifest version must be ${MANIFEST_VERSION}`);
      if (!Array.isArray(manifest.permissions) || manifest.permissions.some(value => !PERMISSION_KINDS.includes(value)) || new Set(manifest.permissions).size !== manifest.permissions.length) throw new Error('invalid advisory permissions');
      validatePalette(manifest.palette);
    } catch (error) { errors.push(`${name}/${MANIFEST_FILE}: ${error.message}`); }
    try {
      const docs = fs.readFileSync(skillArtifactPath(root, [name, SKILL_DOC_FILE]), 'utf8');
      if (!docs.trim() || !docs.includes(name)) throw new Error('documentation must describe the named skill');
    } catch (error) { errors.push(`${name}/${SKILL_DOC_FILE}: ${error.message}`); }
  }
  return { checked: fixtures.checked, errors };
}
