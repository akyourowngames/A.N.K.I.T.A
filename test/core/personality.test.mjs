import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { buildSystemPrompt, Agent } from '../../src/core/agent.mjs';
import { loadConfig } from '../../src/core/config.mjs';
import { captureVoiceContext } from '../../src/core/voice-worker.mjs';
import { createVoiceNarrator } from '../../src/core/voice-narrator.mjs';
const card = await import('../../src/core/personality.mjs').catch(() => ({}));
const disk = await import('../../src/core/personality-store.mjs').catch(() => ({}));
const temp = t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-personality-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
};

test('editable personality validates bounded fields and example exchanges', () => {
  assert.equal(typeof card.normalizePersonality, 'function', 'Structured personality validation is missing');
  const profile = card.normalizePersonality({ description: 'Sassy but caring', attitude: 'bold', teasing: 'light', language: 'hinglish' });
  assert.equal(profile.description, 'Sassy but caring');
  assert.equal(profile.care, card.DEFAULT_PERSONALITY.care);
  assert.throws(() => card.normalizePersonality({ attitude: 'hostile' }), /attitude/i);
  assert.throws(() => card.normalizePersonality({ attitude: ['bold'] }), /attitude/i);
  assert.throws(() => card.normalizePersonality({ enabled: 'false' }), /enabled/i);
  assert.throws(() => card.normalizePersonality({ description: 'x'.repeat(card.PERSONALITY_LIMITS.description + 1) }), /description/i);
  assert.throws(() => card.normalizePersonality({ examples: [{ user: 'hello', assistant: '' }] }), /example/i);
  assert.throws(() => card.normalizePersonality({ unexpected: true }), /unknown/i);
});

test('personality reaches real agent prompts without changing tool rules, and stays out of background work', () => {
  const config = { agentName: 'Fixture', username: 'User', tools: false, personality: card.normalizePersonality({ description: 'Caring sharp fixture voice' }) };
  const prompt = buildSystemPrompt(config, os.tmpdir(), null, [], '', [], false);
  assert.match(prompt, /Caring sharp fixture voice/);
  assert.match(prompt, /Ground every claim in a tool result/);
  assert.match(prompt, /examples.*style|style.*examples/is);
  assert.ok(!buildSystemPrompt({ ...config, personality: { ...config.personality, enabled: false } }, os.tmpdir()).includes(config.personality.description));
  assert.ok(!buildSystemPrompt({ ...config, backgroundJob: true }, os.tmpdir()).includes(config.personality.description));
  const child = new Agent({ client: {}, config, depth: 1, memoryEnabled: false, autoProject: false });
  assert.ok(!child.systemText().includes(config.personality.description), 'Internal delegated workers stay task-focused');
});

test('personality survives a private disk round trip and invalid saves leave the prior card intact', t => {
  const dir = temp(t), file = path.join(dir, 'personality.json');
  const store = new disk.PersonalityStore(file).load();
  const profile = card.normalizePersonality({ description: 'A caring friend with attitude' });
  store.save(profile);
  assert.deepEqual(new disk.PersonalityStore(file).load().view().profile, profile);
  const before = fs.readFileSync(file, 'utf8');
  assert.throws(() => store.save({ ...profile, teasing: 'cruel' }), /teasing/i);
  assert.equal(fs.readFileSync(file, 'utf8'), before);
});

test('a damaged personality file falls back with notice and is never rewritten during load', t => {
  const file = path.join(temp(t), 'personality.json'), original = '{ damaged card';
  fs.writeFileSync(file, original);
  const view = new disk.PersonalityStore(file).load().view();
  assert.deepEqual(view.profile, card.DEFAULT_PERSONALITY);
  assert.match(view.notice, /could not|couldn't/i);
  assert.equal(fs.readFileSync(file, 'utf8'), original);
});

test('shared configuration loads the same personality card for terminal and desktop', t => {
  const dir = temp(t), personalityFile = path.join(dir, 'personality.json');
  new disk.PersonalityStore(personalityFile).save(card.normalizePersonality({ description: 'Shared local voice' }));
  const config = loadConfig(path.join(dir, 'absent.env'), { globalEnvFile: path.join(dir, 'absent-global.env'), personalityFile });
  assert.equal(config.personality.description, 'Shared local voice');
});

test('captured voice work retains its personality when the parent style changes', t => {
  const old = card.normalizePersonality({ description: 'First captured style' });
  const parent = new Agent({ client: {}, config: { tools: false, personality: old }, memoryEnabled: false, workspacePath: temp(t) });
  const captured = captureVoiceContext(parent);
  parent.config.personality = card.normalizePersonality({ description: 'Later style' });
  assert.equal(captured.config.personality.description, 'First captured style');
});

test('progress uses the editable style in its existing single call and keeps factual constraints', async t => {
  const requests = [];
  t.mock.method(globalThis, 'fetch', async (_url, options) => {
    requests.push(JSON.parse(options.body));
    return Response.json({ choices: [{ message: { content: 'The file is saved.' } }] });
  });
  let profile = card.normalizePersonality({ description: 'First custom speaking style' });
  const narrate = createVoiceNarrator({ client: { baseUrl: 'https://fixture.invalid', headers: () => ({}) }, model: 'fixture', getPersonality: () => profile });
  await narrate({ kind: 'step', transcript: 'Save the report', action: { tool: 'write_file', state: 'done' } });
  profile = card.normalizePersonality({ description: 'Second custom speaking style' });
  await narrate({ kind: 'step', transcript: 'Save the report', action: { tool: 'write_file', state: 'done' } });
  assert.equal(requests.length, 2, 'One existing narration call per update; no extra personality call');
  assert.match(requests[0].messages[0].content, /First custom speaking style/);
  assert.match(requests[1].messages[0].content, /Second custom speaking style/);
  assert.match(requests[0].messages[0].content, /observed action\/state/);
});

test('missing profile and unsupported disk versions are recoverable without rewriting', t => {
  const file = path.join(temp(t), 'personality.json');
  for (const saved of [{ version: 1 }, { version: 999, profile: card.DEFAULT_PERSONALITY }]) {
    const before = JSON.stringify(saved); fs.writeFileSync(file, before);
    assert.match(new disk.PersonalityStore(file).load().view().notice, /could not|couldn't/i);
    assert.equal(fs.readFileSync(file, 'utf8'), before);
  }
});

test('personality never displaces a discovered tool in a constrained context', async t => {
  const large = card.normalizePersonality({
    description: 'd'.repeat(card.PERSONALITY_LIMITS.description), care: 'c'.repeat(card.PERSONALITY_LIMITS.care),
    examples: Array.from({ length: card.PERSONALITY_LIMITS.examples }, () => ({
      user: 'u'.repeat(card.PERSONALITY_LIMITS.user), assistant: 'a'.repeat(card.PERSONALITY_LIMITS.assistant),
    })),
  });
  for (const personality of [card.DEFAULT_PERSONALITY, large]) {
    const agent = new Agent({ client: {}, config: { tools: true, contextWindow: 32768, subagentsEnabled: true, personality }, memoryEnabled: false, autoProject: false, workspacePath: temp(t), print: () => {}, write: () => {} });
    await agent.runToolCall({ id: 'discover', type: 'function', function: { name: 'find_tools', arguments: JSON.stringify({ query: 'delegate' }) } });
    assert.ok(agent.currentSpecs().some(spec => spec.function.name === 'delegate_task'), 'Optional style cannot evict a discovered work tool');
  }
});
