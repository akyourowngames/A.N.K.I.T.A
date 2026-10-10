import fs from 'node:fs';
import path from 'node:path';
import { SKILL_NAME_RE, parseSkillFile, skillsDir } from '../core/skills.mjs';
import { renderSkill } from '../../tools/skills/skill.mjs';
import { SKILL_FILE, MANIFEST_FILE, FIXTURE_DIR, FIXTURE_FILE, EXPECTED_FILE, SKILL_DOC_FILE, MANIFEST_VERSION, PERMISSION_KINDS } from './layout.mjs';

const EXAMPLE_MAX_CHARS = 200; // Leaves room within the skill parser's description limit.
export const SCAFFOLD_USAGE = 'ankita new skill [name] [--permissions files,network,shell,browser] [--example "input"] [--directory path]';

export function scaffoldSkill({ name, permissions = [], example, root = skillsDir() } = {}) {
  if (typeof name !== 'string' || !SKILL_NAME_RE.test(name)) throw new Error('Use a lowercase skill name with letters, digits and hyphens');
  if (!Array.isArray(permissions) || permissions.some(value => !PERMISSION_KINDS.includes(value))) throw new Error(`Permissions must be: ${PERMISSION_KINDS.join(', ')}`);
  const input = String(example || '').replace(/\s+/g, ' ').trim();
  if (!input || input.length > EXAMPLE_MAX_CHARS) throw new Error(`Example must contain 1–${EXAMPLE_MAX_CHARS} characters`);
  const access = [...new Set(permissions)];
  const source = `---\nname: ${name}\ndescription: Use when the user asks: ${input}\n---\n# ${name}\n\n1. Understand the user's request: ${input}\n2. Read relevant information using only approved tools.\n3. Ask before making changes and report the observed result.\n`;
  const skill = parseSkillFile(source, name);
  if (skill.error) throw new Error(skill.error);
  const target = path.resolve(root, name);
  fs.mkdirSync(path.resolve(root), { recursive: true });
  try { fs.mkdirSync(target); } catch (error) {
    if (error.code === 'EEXIST') throw new Error(`Skill already exists: ${name}`);
    throw error;
  }
  try {
    fs.writeFileSync(path.join(target, SKILL_FILE), source);
    fs.writeFileSync(path.join(target, MANIFEST_FILE), JSON.stringify({ version: MANIFEST_VERSION, permissions: access, palette: [] }, null, 2) + '\n');
    fs.writeFileSync(path.join(target, SKILL_DOC_FILE), `# ${name}\n\nUse when: ${skill.description}\n\nExample input: ${input}\n\nIntended access: ${access.join(', ') || 'none'}. Declarations are advisory; normal tool approvals apply.\n`);
    fs.mkdirSync(path.join(target, FIXTURE_DIR));
    fs.writeFileSync(path.join(target, FIXTURE_DIR, FIXTURE_FILE), JSON.stringify({ input: { name }, expectedFile: EXPECTED_FILE }, null, 2) + '\n');
    fs.writeFileSync(path.join(target, FIXTURE_DIR, EXPECTED_FILE), renderSkill(skill) + '\n');
    return target;
  } catch (error) {
    // Only the exclusively-created folder under the caller's root is rolled back.
    if (path.dirname(target) === path.resolve(root)) fs.rmSync(target, { recursive: true, force: true });
    throw error;
  }
}
