import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { parseSkillFile, loadSkills, reloadSkills, skillPromptLines, skillsDir } from '../src/skills.mjs';
import { run as readSkill, renderSkill } from '../tools/skill.mjs';
import { buildSystemPrompt, Agent } from '../src/agent.mjs';
import { coreNames, needsApproval, isReadOnly } from '../tools/index.mjs';
import { run as findTools } from '../tools/find-tools.mjs';

const fixture = (name, description = 'Review changes carefully. Use when asked to review code.', extra = '') =>
  `---\nname: ${name}\ndescription: ${description}\n${extra}---\n# ${name}\nFollow the checklist.\n`;

test('skill parser accepts the bounded frontmatter and keeps tool hints verbatim', () => {
  const parsed = parseSkillFile(fixture('commit-review', undefined, 'suggested-tools: git, imaginary_tool\n'), 'commit-review');
  assert.equal(parsed.name, 'commit-review');
  assert.equal(parsed.suggestedTools, 'git, imaginary_tool');
  assert.equal(parsed.body, '# commit-review\nFollow the checklist.');
});

test('skill parser rejects invalid names, descriptions, body, and oversized hints', () => {
  const cases = [
    [fixture('wrong'), 'right'],
    [fixture('Bad_Name'), 'Bad_Name'],
    [fixture('valid', 'short'), 'valid'],
    [fixture('valid', 'x'.repeat(301)), 'valid'],
    ['---\ndescription: Enough words to describe this skill.\n---\nBody', 'valid'],
    ['---\nname: valid\ndescription: Enough words to describe this skill.\n---\n ', 'valid'],
    [fixture('valid', undefined, `suggested-tools: ${'x'.repeat(201)}\n`), 'valid'],
    [fixture('valid') + 'x'.repeat(12001), 'valid'],
    [`---\nname: valid\ndescription: Enough words to describe this skill.\n---\n${' '.repeat(12001)}Body`, 'valid'],
    [`---\r\nname: valid\r\ndescription: Enough words to describe this skill.\r\n---\r\n${'x\r\n'.repeat(5000)}`, 'valid'],
  ];
  for (const [source, dir] of cases) assert.ok(parseSkillFile(source, dir).error, dir);
});

test('loader skips broken entries, sorts good ones, and refreshes after a file edit', (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-skills-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  for (const name of ['zeta', 'alpha', 'broken', 'missing']) fs.mkdirSync(path.join(dir, name));
  fs.writeFileSync(path.join(dir, 'zeta', 'SKILL.md'), fixture('zeta'));
  fs.writeFileSync(path.join(dir, 'alpha', 'SKILL.md'), fixture('alpha'));
  fs.writeFileSync(path.join(dir, 'broken', 'SKILL.md'), fixture('wrong'));
  const originalError = console.error;
  const errors = [];
  console.error = (...args) => errors.push(args.join(' '));
  try {
    assert.deepEqual(loadSkills(dir).map(skill => skill.name), ['alpha', 'zeta']);
    assert.equal(errors.length, 1, 'one diagnostic for invalid entry');
    const file = path.join(dir, 'alpha', 'SKILL.md');
    fs.writeFileSync(file, fixture('alpha').replace('Follow the checklist.', 'Use the updated checklist.'));
    assert.match(loadSkills(dir)[0].body, /updated checklist/);
    reloadSkills();
    assert.match(loadSkills(dir)[0].body, /updated checklist/);
  } finally {
    console.error = originalError;
  }
});

test('missing skills directory loads empty and contributes no prompt section', () => {
  assert.deepEqual(loadSkills(path.join(os.tmpdir(), `missing-skills-${process.pid}`)), []);
  assert.deepEqual(skillPromptLines([]), []);
});

test('catalogue lines describe skills without including their full bodies', () => {
  const lines = skillPromptLines([{ name: 'review', description: 'Review code. Use when asked.', suggestedTools: 'git', body: 'SECRET BODY' }]);
  const text = lines.join('\n');
  assert.match(text, /review: Review code/);
  assert.match(text, /Suggested tools: git/);
  assert.match(text, /hints, not requirements/);
  assert.match(text, /skill\(\{"name":"review"\}\)/);
  assert.doesNotMatch(text, /SECRET BODY/);
});

test('built-in skills parse and the read-only tool returns their instructions', () => {
  const installed = loadSkills(skillsDir());
  assert.deepEqual(installed.map(skill => skill.name), ['ankita-dev', 'commit-review']);
  for (const skill of installed) assert.equal(parseSkillFile(fs.readFileSync(skill.path, 'utf8'), skill.name).name, skill.name);
  assert.ok(coreNames().includes('skill'));
  assert.equal(needsApproval('skill'), false);
  assert.equal(isReadOnly('skill'), true);
  const result = readSkill({ name: ' COMMIT-REVIEW ' });
  assert.match(result, /^# Skill: commit-review/m);
  assert.match(result, /Suggested tools \(hints only\): git/);
  assert.match(result, /Review the diff/);
  assert.match(readSkill({ name: 'unknown' }), /Available: ankita-dev, commit-review/);
});

test('skill result caps a long multibyte body to 8000 UTF-8 bytes', () => {
  const output = renderSkill({ name: 'long', suggestedTools: '', body: '🔥'.repeat(3000) });
  assert.match(output, /^# Skill: long\n---\n/);
  const body = output.split('\n---\n')[1];
  assert.ok(Buffer.byteLength(body) <= 8000);
  assert.match(body, /output truncated/);
  assert.doesNotMatch(body, /\uFFFD/);
});

test('prompt wiring adds catalogue lines and refreshes them on an agent rebase', () => {
  const config = { agentName: 'Ankita', username: 'User', tools: false };
  assert.match(buildSystemPrompt(config, process.cwd(), null, [], '', ['- test-skill: hello']), /test-skill: hello/);
  const agent = new Agent({ client: {}, config, skillsEnabled: true });
  assert.match(agent.messages[0].content, /ankita-dev:/);
  agent.messages[0].content = 'stale';
  agent.rebase();
  assert.match(agent.messages[0].content, /commit-review:/);
  agent.clear();
  assert.match(agent.messages[0].content, /ankita-dev:/);
});

test('agents outside the chat REPL have no skill prompt, schema, discovery, or execution', async () => {
  const agent = new Agent({ client: {}, config: { agentName: 'Ankita', username: 'User', tools: true } });
  assert.doesNotMatch(agent.messages[0].content, /Available skills \(chat only/);
  assert.ok(!agent.currentSpecs().some(spec => spec.function.name === 'skill'));
  assert.doesNotMatch(findTools({ query: 'skills' }, { state: agent.state, skillsEnabled: agent.skillsEnabled }), /Already loaded: skill|  skills /);
  assert.match(await agent.runToolCall({ function: { name: 'skill', arguments: '{"name":"commit-review"}' } }), /^Error:/);
});

test('one-shot /skills lists built-ins without starting a model call', () => {
  const output = execFileSync(process.execPath, ['chat.mjs', '-p', '/skills'], {
    cwd: path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'),
    encoding: 'utf8',
    timeout: 10000,
  });
  assert.match(output, /ankita-dev —/);
  assert.match(output, /commit-review —/);
});
