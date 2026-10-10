import { checkSkillFixtures } from '../src/skills/fixtures.mjs';

const result = checkSkillFixtures(process.argv[2]);
for (const error of result.errors) console.error(error);
console.log(`Skill fixtures: ${result.checked} passed, ${result.errors.length} failed`);
if (result.errors.length) process.exitCode = 1;
