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

test('parallel voice capacity is bounded separately from typed subagents', () => {
  const file = path.join(temporary, 'parallel.env');
  fs.writeFileSync(file, 'VOICE_MAX_PARALLEL_JOBS=99\nSUBAGENTS_ENABLED=off\n');
  assert.equal(loadConfig(file, { globalEnvFile: path.join(temporary, 'absent') }).voiceMaxParallelJobs, 8);
  fs.writeFileSync(file, 'VOICE_MAX_PARALLEL_JOBS=2\n');
  assert.equal(loadConfig(file, { globalEnvFile: path.join(temporary, 'absent') }).voiceMaxParallelJobs, 2);
});

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

test('Modal voice settings compose the proxy token and keep a safe token floor', () => {
  const file = path.join(temporary, 'modal.env');
  fs.writeFileSync(file, 'MODAL_PROXY_TOKEN_ID=token-id\nMODAL_PROXY_TOKEN_SECRET=token-secret\nMODAL_BASE_URL=https://deployment.invalid/v1\nMODAL_MAX_TOKENS=32\nMODAL_REASONING_EFFORT=high\n');
  const config = loadConfig(file, { globalEnvFile: path.join(temporary, 'absent') });
  assert.equal(config.modalApiKey, 'token-id.token-secret', 'the two proxy parts become one bearer token');
  assert.equal(config.modalBaseUrl, 'https://deployment.invalid/v1');
  assert.equal(config.modalModel, 'deepseek-ai/DeepSeek-V4.1-Flash-1017');
  assert.equal(config.modalMaxTokens, 400, 'reasoning needs room before any answer tokens');
  assert.equal(config.modalReasoningEffort, 'high');
  const brain = voice.createVoiceBrain({ ...config, voiceProvider: 'modal' });
  assert.equal(brain.client.baseUrl, 'https://deployment.invalid/v1');
  assert.equal(brain.client.apiKey, 'token-id.token-secret');
  assert.deepEqual(brain.client.requestDefaults, { max_tokens: 400, reasoning_effort: 'high' });
  const defaults = voice.createVoiceBrain({ voiceProvider: 'modal', modalBaseUrl: 'https://deployment.invalid/v1', modalApiKey: 'fixture' });
  assert.equal(defaults.client.requestDefaults.reasoning_effort, 'low', 'the deployment rejects minimal; low is its floor');
  assert.equal(defaults.contextWindow, 1_048_576, 'the advertised deployment window is used for voice only');
  assert.throws(() => voice.createVoiceBrain({ voiceProvider: 'modal', modalApiKey: 'fixture' }), /MODAL_BASE_URL/);
  const combined = loadConfig((() => {
    const combinedFile = path.join(temporary, 'modal-combined.env');
    fs.writeFileSync(combinedFile, 'MODAL_PROXY_TOKEN=combined-token\nMODAL_PROXY_TOKEN_ID=ignored-id\nMODAL_PROXY_TOKEN_SECRET=ignored-secret\n');
    return combinedFile;
  })(), { globalEnvFile: path.join(temporary, 'absent') });
  assert.equal(combined.modalApiKey, 'combined-token', 'a rotated combined token wins over stale parts');
});

test('Modal requests carry the lowest supported reasoning and never inherit chat settings', async t => {
  const requests = [];
  t.mock.method(globalThis, 'fetch', async (_url, opts) => {
    requests.push(JSON.parse(opts.body));
    return Response.json({ choices: [{ message: { content: 'Ready.' } }] });
  });
  const brain = voice.createVoiceBrain({ voiceProvider: 'modal', modalBaseUrl: 'https://modal.invalid/v1', modalApiKey: 'fixture-key' });
  const agent = new Agent({ client: brain.client, config: { tools: false, maxTokens: 32, maxTokensExplicit: true }, skillsEnabled: false, autoProject: false });
  agent.model = brain.model;
  await agent.streamAttempt();
  assert.equal(requests[0].reasoning_effort, 'low', 'the deployment rejects minimal; low is its floor');
  assert.equal(requests[0].max_tokens, 400);
  assert.equal(requests[0].model, 'deepseek-ai/DeepSeek-V4.1-Flash-1017');
  agent.client = new CompatibleClient({ apiBase: 'https://chat.invalid/v1' });
  agent.config.maxTokensExplicit = false;
  await agent.streamAttempt();
  assert.equal(requests[1].reasoning_effort, undefined, 'typed chat clients keep their own request shape');
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
  const agent = { client: {}, model: 'chat', systemSuffix: 'Keep existing safety instructions.', contextWindow: 32768, tool: { model: 'other' }, _activeModelClient: {}, _activeModel: 'previous' };
  const saved = { ...agent };
  const brain = { client: {}, model: 'voice', contextWindow: 131072 };
  for (const fail of [false, true]) {
    const run = voice.withVoiceBrain(agent, brain, async () => {
      assert.equal(agent.client, brain.client);
      assert.equal(agent.model, brain.model);
      assert.equal(agent.contextWindow, brain.contextWindow);
      assert.equal(agent.tool, null, 'a configured non-Meta tool model cannot take over');
      assert.ok(agent.systemSuffix.startsWith(saved.systemSuffix));
      assert.match(agent.systemSuffix, /one or two short sentences/i);
      assert.match(agent.systemSuffix, /details/i);
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

test('voice brevity applies even without a separate voice provider and leaves typed instructions intact', async () => {
  const agent = {};
  await voice.withVoiceBrain(agent, null, async () => {
    assert.match(agent.systemSuffix, /one or two short sentences/i);
  });
  assert.deepEqual(agent, {});
});

test('spoken voice replies keep two complete sentences even if the model ignores brevity', () => {
  assert.equal(voice.voiceReplyForSpeech('File ready hai. It has your poem. Want anything else?'), 'File ready hai. It has your poem.');
  assert.equal(voice.voiceReplyForSpeech('Work did not finish. Permission was denied. The model claimed success.'), 'Work did not finish. Permission was denied.');
  assert.equal(voice.voiceReplyForSpeech('- First item.\n- Second item.\n- Third item.'), 'First item. Second item.');
  assert.equal(voice.voiceReplyForSpeech('```js\nsecret()\n```'), '');
  assert.equal(voice.voiceReplyForSpeech('फाइल तैयार है। कविता सेव है। और कुछ चाहिए?'), 'फाइल तैयार है। कविता सेव है।');
  assert.equal(voice.voiceReplyForSpeech('हो गया।फाइल सेव है।तीसरी बात।'), 'हो गया। फाइल सेव है।');
});

test('report clips follow complete English and Hindi sentences and prepare lazily', async () => {
  const prepared = [];
  const item = voice.createVoiceReportSpeech({ jobId: 'report', text: 'पहला वाक्य।Second sentence. Third sentence.', turn: 4,
    synthesize: async text => { prepared.push(text); return Buffer.from(text); } });
  assert.equal(item.kind, 'report'); assert.equal(item.turn, 4);
  assert.deepEqual(item.parts.map(part => part.text), ['पहला वाक्य।', 'Second sentence.']);
  assert.deepEqual(prepared, []); assert.ok((await item.parts[1].prepare()).length); assert.deepEqual(prepared, ['Second sentence.']);
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
  agent.client = brain.client;
  await agent.streamAttempt();
  assert.equal(requests[2].max_tokens, 4096, 'file content shares the generation budget and must not be capped like spoken text');
  assert.equal(voice.voiceReplyForSpeech('Saved the file. It has your findings. Anything else?'), 'Saved the file. It has your findings.');
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

test('microphone discovery is shared within a voice session and refreshed after device failure', async () => {
  let calls = 0;
  const microphone = voice.createVoiceMicrophone({ preferred: 'selected', detect: async preferred => {
    assert.equal(preferred, 'selected');
    calls++;
    return { name: `device-${calls}` };
  } });
  assert.deepEqual(await Promise.all([microphone.get(), microphone.get()]), [{ name: 'device-1' }, { name: 'device-1' }]);
  assert.equal(calls, 1);
  microphone.invalidate();
  assert.deepEqual(await microphone.get(), { name: 'device-2' });
  const missing = voice.createVoiceMicrophone({ detect: async () => { throw new Error('unplugged'); } });
  await assert.rejects(missing.get(), /unplugged/);
  await assert.rejects(missing.get(), /unplugged/);
});
