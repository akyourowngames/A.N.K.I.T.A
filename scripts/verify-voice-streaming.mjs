/** Live configured speech journey. Synthetic audio only; native output decodes to a temp WAV, never speakers. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { loadConfig } from '../src/core/config.mjs';
import { DesktopVoice } from '../desktop/electron/voice.mjs';
import { synthesizeSarvam, synthesizeSarvamStream, playMp3Stream, transcribeSarvam } from '../src/channels/voice.mjs';

const PHRASE = 'Voice streaming is ready.'; // Synthetic fixture; no person is recorded.
const REQUEST = 'Read the speech check result'; // Fixture request consumed by the real desktop capture loop.
const DEADLINE_MS = 90000; // Milliseconds: bound the authorized live service journey.
const POLL_MS = 20; // Milliseconds: wait for real task/audio settlement.
const PCM_SAMPLE_RATE = '16000'; // Hz: matches the desktop microphone/transcription contract.
const config = loadConfig();
console.log(JSON.stringify({ credentialsPresent: { sarvam: Boolean(config.sarvamApiKey), baseten: Boolean(config.basetenApiKey), groq: Boolean(config.groqApiKey) } }));
assert.ok(config.sarvamApiKey, 'Configure Sarvam in the existing voice settings first.');
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-live-stream-'));
const wavPath = path.join(directory, 'synthetic.wav');
const inputs = [], chunks = []; let complete = false, firstConsumedMs = null, decodeStarted, playedBeforeComplete = false;
const until = async check => { const end = Date.now() + DEADLINE_MS; while (!check()) { assert.ok(Date.now() < end, 'Live voice deadline exceeded'); await new Promise(resolve => setTimeout(resolve, POLL_MS)); } };
const fixtureConfig = { ...config, voiceWakeWord: false, voiceBargeIn: false, voiceHfpRouting: false, voiceOutputDevice: '', voiceSpeechGapMs: 0 };
const engine = { listTeammates: () => [{ id: 'speech-check' }], captureVoiceContext: () => ({}), runVoiceJob: async () => ({ text: PHRASE, error: null }), deliverVoiceJob: async () => {} };
const voice = new DesktopVoice({ engine, getConfig: () => fixtureConfig, directory, emit: () => {}, io: {
  audioDeps: () => ({ ffmpeg: true, ffplay: true }), listMicrophones: async () => [{ name: 'Synthetic input' }],
  listAudioDevices: async () => [], getDefaultRenderId: () => '', playbackIsolated: async () => false,
  openVoiceInput(options) { fs.writeFileSync(options.outFile, 'synthetic fixture'); const input = { options, ready: Promise.resolve(), stop: async () => true }; inputs.push(input); return input; },
  transcribeAudio: async () => ({ text: REQUEST, languageCode: 'en-IN' }), narrate: async () => '',
  // Receipts are hardware fixtures; only the report phrase goes to the configured service.
  synthesizeSarvam: options => options.text === PHRASE ? synthesizeSarvam(options) : Buffer.from('receipt'),
  synthesizeSarvamStream,
  playMp3: async () => {}, stopPlayback: () => {},
  async playMp3Stream(source, options) {
    decodeStarted = performance.now();
    await playMp3Stream(async function* (playerOptions) {
      for await (const chunk of source(playerOptions)) {
        firstConsumedMs ??= Math.round(performance.now() - decodeStarted);
        playedBeforeComplete ||= !complete; chunks.push(chunk.length); yield chunk;
      }
    }, { ...options, spawnImpl: () => spawn('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-f', 'mp3', '-i', 'pipe:0', '-ac', '1', '-ar', PCM_SAMPLE_RATE, '-c:a', 'pcm_s16le', '-y', wavPath],
      { windowsHide: true, stdio: ['pipe', 'ignore', 'ignore'] }) });
    complete = true;
  },
} });
try {
  await voice.start({ threadId: 'speech-check' });
  await until(() => voice.snapshot().phase === 'listening');
  const input = inputs.at(-1); input.options.onEvent({ type: 'silence_end', at: 1 }); input.options.onEvent({ type: 'silence_start', at: 2 });
  await until(() => complete || voice.snapshot().error);
  assert.equal(voice.snapshot().error, null);
  assert.ok(chunks.length && playedBeforeComplete);
  assert.ok(fs.statSync(wavPath).size > 0, 'Real native decoder must accept the streamed MP3.');
  const delivery = voice.snapshot().delivery;
  await voice.end();
  const heard = await transcribeSarvam({ apiKey: config.sarvamApiKey, model: config.sarvamSttModel, mode: config.sarvamSttMode, wavPath,
    languageCode: 'en-IN', keyterms: config.sarvamKeyterms });
  assert.match(heard.text, /ready/i, 'Generated synthetic speech must survive the configured STT round trip.');
  console.log(JSON.stringify({ desktopReport: 'done', delivery, chunks: chunks.length, bytes: chunks.reduce((sum, length) => sum + length, 0),
    firstConsumedMs, streamedIntoNativeDecoder: playedBeforeComplete, decodedWavBytes: fs.statSync(wavPath).size, transcript: heard.text,
    microphone: 'injected synthetic input', speakers: 'never played', ok: true }));
} finally { await voice.close(); fs.rmSync(directory, { recursive: true, force: true }); }
