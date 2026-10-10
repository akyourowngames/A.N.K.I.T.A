import { checkSkillContributions } from '../src/skills/contributions.mjs';

const result = checkSkillContributions(process.argv[2]);
for (const error of result.errors) console.error(error);
console.log(`Skill contributions: ${result.checked} checked, ${result.errors.length} errors`);
if (result.errors.length) process.exitCode = 1;
