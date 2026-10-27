import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { Agent } from '../../src/core/agent.mjs';
import { loadConfig } from '../../src/core/config.mjs';
import { resolveProvider, CompatibleClient } from '../../src/core/provider.mjs';

const voice = await import('../../src/core/voice-session.mjs').catch(() => ({}));
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-session-'));
test.after(() => fs.rmSync(temporary, { recursive: true, force: true }));

test('Baseten and voice settings load separately from typed chat settings', () => {
  const file = path.join(temporary, '.env');
  fs.writeFileSync(file, 'PROVIDER=kilo\nMODEL=typed-model\nVOICE_PROVIDER=Baseten\nVOICE_MODEL=voice-model\nVOICE_API_BASE=https://voice.invalid/v1\nBASETEN_API_KEY=fixture-key\nBASETEN_MAX_TOKENS=32\nBASETEN_REASONING_EFFORT=invalid\n');
  const config = loadConfig(file, { globalEnvFile: path.join(temporary, 'absent') });
  assert.equal(config.provider, 'kilo');
  assert.equal(config.model, 'typed-model');
  assert.equal(config.voiceProvider, 'baseten');
  assert.equal(config.voiceModel, 'voice-model');
  assert.equal(config.basetenMaxTokens, 400, 'reasoning needs room before any answer tokens');
  assert.equal(config.basetenReasoningEffort, 'low');
  assert.equal(resolveProvider('baseten').keyConfig, 'basetenApiKey');
});

test('voice endpoint override wins and its key never comes from the chat provider', () => {
  const brain = voice.createVoiceBrain({ voiceProvider: 'baseten', voiceApiBase: 'https://voice.invalid/v1', voiceModel: 'voice-model', basetenApiKey: 'voice-key', apiKey: 'chat-key' });
  assert.equal(brain.client.baseUrl, 'https://voice.invalid/v1');
  assert.equal(brain.client.apiKey, 'voice-key');
  assert.equal(brain.model, 'voice-model');
  assert.equal(voice.createVoiceBrain({}), null);
  assert.equal(voice.createVoiceBrain({ voiceModel: 'new-model' }, { client: {}, model: 'chat' }).model, 'new-model');
  assert.equal(voice.createVoiceBrain({ voiceProvider: 'kilo' }).client.apiKey, '');
  assert.throws(() => voice.createVoiceBrain({ voiceProvider: 'baseten' }), /BASETEN_API_KEY/);
  assert.throws(() => voice.createVoiceBrain({ voiceProvider: 'unknown' }), /VOICE_PROVIDER/);
});

test('voice turn pins the whole tool loop and restores chat after success or failure', async () => {
  const agent = { client: {}, model: 'chat', contextWindow: 32768, tool: { model: 'other' }, _activeModelClient: {}, _activeModel: 'previous' };
  const saved = { ...agent };
  const brain = { client: {}, model: 'voice', contextWindow: 131072 };
  for (const fail of [false, true]) {
    const run = voice.withVoiceBrain(agent, brain, async () => {
      assert.equal(agent.client, brain.client);
      assert.equal(agent.model, brain.model);
      assert.equal(agent.contextWindow, brain.contextWindow);
      assert.equal(agent.tool, null, 'a configured non-Meta tool model cannot take over');
      agent._activeModelClient = brain.client;
      agent._activeModel = brain.model;
      if (fail) throw new Error('fixture failure');
      return 'spoken answer';
    });
    if (fail) await assert.rejects(run, /fixture failure/);
    else assert.equal(await run, 'spoken answer');
    assert.deepEqual(agent, saved);
  }
});

test('Baseten requests use low reasoning and a safe token floor; other clients stay unchanged', async t => {
  const requests = [];
  t.mock.method(globalThis, 'fetch', async (_url, opts) => {
    requests.push(JSON.parse(opts.body));
    return Response.json({ choices: [{ message: { content: 'Ready.' } }] });
  });
  const brain = voice.createVoiceBrain({ voiceProvider: 'baseten', basetenApiKey: 'fixture-key' });
  const agent = new Agent({ client: brain.client, config: { tools: false, maxTokens: 32, maxTokensExplicit: true }, skillsEnabled: false, autoProject: false });
  agent.model = brain.model;
  await agent.streamAttempt();
  assert.equal(requests[0].reasoning_effort, 'low');
  assert.equal(requests[0].max_tokens, 400);
  agent.client = new CompatibleClient({ apiBase: 'https://chat.invalid/v1' });
  agent.config.maxTokensExplicit = false;
  await agent.streamAttempt();
  assert.equal(requests[1].reasoning_effort, undefined);
  assert.equal(requests[1].max_tokens, undefined);
});

test('acknowledgements warm once, skip failed clips and rotate in the spoken language', async () => {
  const calls = [];
  const cache = voice.createAcknowledgements({ synthesize: async (text, language) => {
    calls.push([text, language]);
    if (text.includes('Dekh')) throw new Error('voice offline');
    return Buffer.from(text);
  } });
  await cache.prewarm();
  const count = calls.length;
  await cache.prewarm();
  assert.equal(calls.length, count);
  const first = cache.next('hi-IN');
  assert.equal(first.text, 'Haan.');
  assert.equal(cache.next('hi-IN').text, 'Theek hai.');
  assert.equal(cache.next('hi-IN').text, first.text);
  assert.equal(cache.next('en-IN').text, 'Okay.');
  assert.equal(calls.find(([text]) => text === 'Haan.')[1], 'hi-IN');
  const silent = voice.createAcknowledgements({ synthesize: async () => null });
  await silent.prewarm();
  assert.equal(silent.next('hi-IN'), null);
});
