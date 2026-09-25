import { loadSkills } from '../../src/core/skills.mjs';
import { capOutput } from '../shared/_shared.mjs';

export const name = 'skill';
export const description = 'Load a built-in skill: repeatable workflow instructions (e.g. commit-review). Call when the task matches a skill description. Returns markdown to follow; suggested tools are hints only.';
export const needsApproval = false;
export const readOnly = true;
export const parameters = {
  type: 'object',
  properties: { name: { type: 'string', description: 'Skill name, e.g. commit-review' } },
  required: ['name'],
};

export function run(args = {}, ctx = {}) {
  const requested = String(args.name ?? '').trim().toLowerCase();
  if (ctx.disabledSkills?.has?.(requested) || ctx.disabledSkills?.includes?.(requested)) {
    return `Error: skill "${requested}" is disabled in Plugins > Skills.`;
  }
  const skills = loadSkills();
  const found = skills.find(skill => skill.name === requested);
  if (!found) return `Unknown skill "${requested}". Available: ${skills.map(skill => skill.name).join(', ') || '(none)'}.`;
  return renderSkill(found);
}

export function renderSkill(found) {
  return [
    `# Skill: ${found.name}`,
    ...(found.suggestedTools ? [`Suggested tools (hints only): ${found.suggestedTools}`] : []),
    '---',
    capOutput(found.body, 8000),
  ].join('\n');
}
