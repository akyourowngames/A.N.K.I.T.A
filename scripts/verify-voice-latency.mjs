/** Real planner/TTS and device discovery, simulated mic startup, no recording/playback.
 * Measures transcript-to-final-player handoff, not physical speech-to-ear latency.
 * Usage: node scripts/verify-voice-latency.mjs [--cli /path/to/src/core/cli.mjs] [--voice-provider modal]
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';
import { loadConfig } from '../src/core/config.mjs';
import { createVoiceBrain } from '../src/core/voice-session.mjs';
import { configuredSecrets, redactText } from '../src/core/redact.mjs';

const INPUT_STARTUP_MS = 1000; // Script-only simulation of openVoiceInput's existing startup guard.
const RUN_TIMEOUT_MS = 60000; // Milliseconds: bound live cloud requests and child cleanup.
const REQUESTS = ['Hello, how are you?', 'I am good, what about you?', 'Thanks, that helps.'];
const TYPED_MODEL = 'latency-fixture'; // Local gateway only; voice uses the real configured Meta planner.
const arguments_ = process.argv.slice(2);
const cliIndex = arguments_.indexOf('--cli');
const cli = cliIndex < 0 ? new URL('../src/core/cli.mjs', import.meta.url).href : pathToFileURL(path.resolve(arguments_[cliIndex + 1])).href;
const config = loadConfig();
// Voice planner under test can be swapped without editing .env, so the same
// harness measures "before" and "after" on identical prompts.
const voiceProviderIndex = arguments_.indexOf('--voice-provider');
if (voiceProviderIndex >= 0) {
  const override = String(arguments_[voiceProviderIndex + 1] || '').trim().toLowerCase();
  assert.ok(override, '--voice-provider needs a provider name.');
  config.voiceProvider = override;
  // VOICE_MODEL is provider-specific. An override run uses the target
  // provider's default unless --voice-model names one explicitly.
  const modelIndex = arguments_.indexOf('--voice-model');
  config.voiceModel = modelIndex >= 0 ? String(arguments_[modelIndex + 1] || '').trim() : '';
}
const brain = createVoiceBrain(config);
assert.ok(brain && config.sarvamApiKey, 'Set voice planner and Sarvam keys locally.');
const secrets = configuredSecrets(config);
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-latency-'));
const rows = [];
const server = http.createServer((request, response) => {
  response.setHeader('Content-Type', 'application/json');
  response.end(JSON.stringify({ data: [{ id: TYPED_MODEL, supported_parameters: ['tools'] }] }));
});
try {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  // The temporary settings file contains no keys. Secrets are inherited only in
  // the child environment and neither request payloads nor answers are logged.
  fs.writeFileSync(path.join(directory, '.env'), [
    'PROVIDER=kilo', `MODEL=${TYPED_MODEL}`, `API_BASE=http://127.0.0.1:${server.address().port}/v1`,
    `VOICE_PROVIDER=${config.voiceProvider}`, `VOICE_MODEL=${brain.model}`, `VOICE_API_BASE=${brain.client.baseUrl}`,
    'STT_PROVIDER=sarvam', 'TTS_PROVIDER=sarvam', `SARVAM_TTS_MODEL=${config.sarvamTtsModel}`,
    'VOICE_BARGE_IN=on', 'VOICE_HFP_ROUTING=off', 'MEMORY_CONSOLIDATION=off',
    'PROJECT_AUTO_DETECT=off', 'PROJECT_WORK_CAPTURE=off', 'PROJECT_AUTO_MAINTENANCE=off',
    'SUBAGENTS_ENABLED=off', 'EMBEDDINGS=off',
  ].join('\n'));
  const harness = path.join(directory, 'harness.mjs');
  const channel = new URL('../src/channels/voice.mjs', import.meta.url).href;
  fs.writeFileSync(harness, `
    import fs from 'node:fs';
    import { main } from ${JSON.stringify(cli)};
    import * as voice from ${JSON.stringify(channel)};
    let turn = 0; let transcriptAt; let discoveryCount = 0; let inputCount = 0;
    const clips = new WeakMap();
    const requests = ${JSON.stringify(REQUESTS)};
    process.argv = [process.execPath, ${JSON.stringify(harness)}, '--voice', '--plain', '--no-banner'];
    const exit = new Error('cli exit');
    process.exit = code => { process.exitCode = code; throw exit; };
    if (process.env.VOICE_LATENCY_TRACE === '1') {
      console.log('LATENCY_TRACE_ENABLED');
      const originalFetch = globalThis.fetch;
      globalThis.fetch = async (url, options = {}) => {
        const started = performance.now();
        let body = {};
        try { body = JSON.parse(options.body || '{}'); } catch {}
        console.log('LATENCY_REQUEST ' + JSON.stringify({ model: body.model, messages: (body.messages || []).length,
          promptChars: JSON.stringify(body.messages || []).length, tools: (body.tools || []).length,
          toolSchemaChars: JSON.stringify(body.tools || []).length, max_tokens: body.max_tokens,
          reasoning_effort: body.reasoning_effort, stream: body.stream === true,
          toolNames: (body.tools || []).map(tool => tool.function?.name).filter(Boolean),
          toolChars: Object.fromEntries((body.tools || []).map(tool => [tool.function?.name, JSON.stringify(tool).length])) }));
        const response = await originalFetch(url, options);
        console.log('LATENCY_RESPONSE ' + JSON.stringify({ status: response.status, headersMs: Math.round(performance.now() - started), at: Math.round(performance.now()) }));
        return response;
      };
    }
    try { await main({voiceIO: {
      audioDeps: () => ({ffmpeg: true, ffplay: true}),
      detectMic: async preferred => { discoveryCount++; return voice.detectMic(preferred); },
      openVoiceInput: ({outFile}) => {
        inputCount++;
        fs.writeFileSync(outFile, 'simulated microphone');
        return {ready: new Promise(resolve => setTimeout(() => { console.log('LATENCY_INPUT_READY'); resolve(); }, ${INPUT_STARTUP_MS})), stop: async () => true};
      },
      transcribeAudio: async () => { transcriptAt = performance.now(); return {text: requests[turn++] || 'exit', languageCode: 'en-IN', confidence: 1}; },
      synthesizeSarvam: async options => { const start = performance.now(); const prewarmed = transcriptAt == null; const audio = await voice.synthesizeSarvam(options); clips.set(audio, {text: options.text, prewarmed, ttsMs: Math.round(performance.now() - start)}); return audio; },
      playMp3: async audio => {
        const clip = clips.get(audio);
        if (!clip || clip.prewarmed) return;
        console.log('LATENCY_ROW ' + JSON.stringify({round: turn, transcriptToPlayerMs: Math.round(performance.now() - transcriptAt), ttsMs: clip.ttsMs, characters: clip.text.length, sentences: clip.text.trim().split(/(?<=[.!?])\\s+/u).length, discoveryCount, inputCount}));
      },
      stopPlayback: () => {},
    }}); } catch(error) { if(error !== exit) throw error; }
  `);
  const child = spawn(process.execPath, [harness], { cwd: directory, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
    env: { ...process.env, CONFIG_DIR: path.join(directory, 'config'), NO_COLOR: '1',
      BASETEN_API_KEY: config.basetenApiKey, MODAL_PROXY_TOKEN: config.modalApiKey, SARVAM_API_KEY: config.sarvamApiKey } });
  let output = ''; let errors = ''; let captures = 0; let leaving = false;
  child.stdout.on('data', data => {
    output += data;
    const seen = output.split('LATENCY_INPUT_READY').length - 1;
    while (captures < seen) { captures++; child.stdin.write('\n'); }
    if (!leaving && output.includes('leaving voice mode')) { leaving = true; child.stdin.end('/exit\n'); }
  });
  child.stderr.on('data', data => { errors += data; });
  const code = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { child.kill(); reject(new Error('Live latency check timed out.')); }, RUN_TIMEOUT_MS);
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.on('exit', status => { clearTimeout(timer); resolve(status); });
  });
  assert.equal(code, 0, redactText(errors, { secrets }));
  for (const match of output.matchAll(/LATENCY_ROW (\{[^\r\n]+\})/g)) rows.push(JSON.parse(match[1]));
  if (process.env.VOICE_LATENCY_TRACE === '1') {
    for (const line of output.split(/\r?\n/).filter(value => /^LATENCY_(TRACE_ENABLED|REQUEST|RESPONSE)\b/.test(value))) console.log(line);
  }
  assert.equal(rows.length, REQUESTS.length, 'Every request needs a final speech clip.');
  for (const row of rows) {
    console.log(JSON.stringify(row)); assert.ok(row.characters > 0);
    if (cliIndex < 0) assert.ok(row.sentences <= 2, 'Voice should reply in one or two sentences.');
  }
  console.log(`OK: ${rows.length}/${REQUESTS.length} real planner/speech replies; mic startup simulated, audio not played.`);
} catch (error) {
  console.error(redactText(error.message, { secrets }));
  process.exitCode = 1;
} finally {
  server.closeAllConnections();
  server.close();
  fs.rmSync(directory, {recursive: true, force: true});
}
