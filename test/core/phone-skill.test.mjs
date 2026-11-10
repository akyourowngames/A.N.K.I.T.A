import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-phone-skill-'));
process.env.CONFIG_DIR = path.join(root, 'config');
test.after(() => fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));

const { loadSkills, skillPromptLines } = await import('../../src/core/skills.mjs');
const { Agent } = await import('../../src/core/agent.mjs');

const skill = loadSkills().find(item => item.name === 'phone-control');

test('phone-control skill exists, stays small and rides the phone family automatically', () => {
  assert.ok(skill, 'phone-control is installed');
  assert.deepEqual(skill.autoTools, ['phone']);
  assert.equal(skill.suggestedTools, 'phone');
  assert.match(skill.description, /Android|phone/i);
  const block = `Automatically loaded skill: phone-control\n${skill.body}`;
  assert.ok(block.length <= 6000, `automatic block is ${block.length} chars and must fit the 6000-char budget`);
  assert.match(skillPromptLines([skill], ['phone']).join('\n'), /Automatically loaded skill: phone-control/);
  assert.doesNotMatch(skillPromptLines([skill], ['git']).join('\n'), /Automatically loaded skill: phone-control/);
});

test('phone guide prefers discovery over stale ports, but never adb by hand', () => {
  assert.match(skill.body, /action="wireless"/);
  assert.match(skill.body, /mDNS/);
  assert.match(skill.body, /Never reuse an old/i);
  assert.match(skill.body, /unauthorized/i);
  assert.match(skill.body, /Do not shell out to adb/i);
  assert.doesNotMatch(skill.body, /\b\d{1,3}(?:\.\d{1,3}){3}:\d+\b/, 'no hardcoded IP:port');
});

test('phone guide is token-frugal: refs, batch, filtered logs, screenshots only when needed', () => {
  assert.match(skill.body, /action="see"/);
  assert.match(skill.body, /action="batch"/);
  assert.match(skill.body, /filter/);
  assert.match(skill.body, /screenshot.*only when/i);
  assert.match(skill.body, /do not re-list between steps/i);
});

test('locked-phone and destructive-action rules are explicit', () => {
  assert.match(skill.body, /`POWER` once/);
  assert.match(skill.body, /ask the user to unlock/i);
  assert.match(skill.body, /Never ask for, type or guess a PIN/i);
  assert.match(skill.body, /uninstall.*clear_data.*stop_recording/i);
  assert.match(skill.body, /always need approval/i);
});

test('discovering the phone family auto-loads the guide; unrelated discovery does not', async () => {
  const call = (id, name, args) => ({ id, type: 'function', function: { name, arguments: JSON.stringify(args) } });
  const config = { tools: true, model: 'fixture-model', contextWindow: 131072, historyMessages: 40, maxTokens: 1000, memoryConsolidation: false, autoApprove: true };
  const agent = new Agent({ client: {}, config, workspacePath: root, skillsEnabled: true });
  await agent.runToolCall(call('git', 'find_tools', { query: 'git' }));
  agent.refreshPrompt();
  assert.ok(!agent.messages[0].content.includes(skill.body), 'unrelated discovery must not load the phone guide');
  await agent.runToolCall(call('phone', 'find_tools', { query: 'phone', scope: 'focus' }));
  agent.refreshPrompt();
  assert.ok(agent.messages[0].content.includes(skill.body), 'phone discovery must load the complete guide');
});
