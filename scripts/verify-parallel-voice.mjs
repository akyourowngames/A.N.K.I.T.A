/** Real Sarvam/Meta/file concurrency; generated input and captured MP3 output, no physical headset. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { loadConfig } from '../src/core/config.mjs';
import { Agent } from '../src/core/agent.mjs';
import { createVoiceBrain, voiceReplyForSpeech } from '../src/core/voice-session.mjs';
import { captureVoiceContext, runVoiceWorker } from '../src/core/voice-worker.mjs';
import { VoiceJobs } from '../src/automation/voice-jobs.mjs';
import { VoiceTaskStore, voiceTaskReport } from '../src/automation/voice-task.mjs';
import { VoiceSpeechQueue } from '../src/automation/voice-speech-queue.mjs';
import { synthesizeSarvam, transcribeAudio, resolveSarvamSpeaker, chooseSarvamLanguage } from '../src/channels/voice.mjs';
import { configuredSecrets, redactText } from '../src/core/redact.mjs';

const ENV_FLAG = '--env';
const PCM_RATE_HZ = 16000; // Hz: same mono PCM format as microphone transcription.
const DEADLINE_MS = 60000; // Milliseconds/check: stop a failed cloud check rather than leave a blocked fixture running.
const FIXTURE_TOOLS = new Set(['read_file', 'write_file']); // This script can touch only its disposable files.
const EDIT_MARKER = 'Second edit complete'; // Script fixture only: prove the later read/modify/write kept the first poem.
const defer = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const envIndex = process.argv.indexOf(ENV_FLAG);
const loaded = loadConfig(envIndex < 0 ? undefined : process.argv[envIndex + 1]);
const config = { ...loaded, voiceProvider: 'baseten', sttProvider: 'sarvam', tools: true, autoApprove: true,
  memoryConsolidation: false, projectAutoDetect: false, projectWorkCapture: false };
const secrets = configuredSecrets(config);
const brain = createVoiceBrain(config);
if (!config.sarvamApiKey) throw new Error('Restore SARVAM_API_KEY locally before the real parallel speech check.');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'parallel-voice-live-'));
const workspace = path.join(root, 'workspace'); fs.mkdirSync(workspace);
const parent = new Agent({ config, client: brain.client, memoryEnabled: false, workspacePath: workspace });
class FixtureAgent extends Agent { constructor(options) { super({ ...options, allowedTools: FIXTURE_TOOLS }); } }
const firstLease = defer(), releaseFirst = defer(), conflictingWait = defer();
let firstId, playerCount = 0, peakPlayers = 0;
const clips = [], reports = [];
const synthesize = text => {
  const languageCode = chooseSarvamLanguage({ text, detected: 'hi-IN' });
  return synthesizeSarvam({ apiKey: config.sarvamApiKey, model: config.sarvamTtsModel,
    speaker: resolveSarvamSpeaker(config, languageCode), languageCode, text });
};
const speech = new VoiceSpeechQueue({ gapMs: config.voiceSpeechGapMs,
  play: async bytes => { playerCount++; peakPlayers = Math.max(peakPlayers, playerCount); clips.push(bytes.length); await new Promise(resolve => setImmediate(resolve)); playerCount--; },
});
const jobs = new VoiceJobs({ store: new VoiceTaskStore({ directory: path.join(root, 'jobs'), secrets }),
  run: (entry, options) => runVoiceWorker(entry, options, { AgentClass: FixtureAgent, brain,
    acquire: (...args) => jobs.acquire(...args),
    toolContext: { beforeToolExecute: async (call, ctx) => {
      if (entry.id === firstId && call.name === 'write_file') {
        firstLease.resolve();
        await Promise.race([releaseFirst.promise, new Promise((_resolve, reject) => ctx.signal.addEventListener('abort', () => reject(ctx.signal.reason), { once: true }))]);
      }
    } },
  }),
  onUpdate: job => { if (job.status === 'waiting_for_resource') conflictingWait.resolve(job); },
  onComplete: task => {
    const text = voiceReplyForSpeech(voiceTaskReport(task));
    reports.push(speech.offer({ jobId: task.id, kind: 'report', prepare: () => synthesize(text) }));
  },
});
const deadline = async promise => {
  let timer;
  try { return await Promise.race([promise, new Promise((_resolve, reject) => { timer = setTimeout(() => { reject(new Error('Parallel speech verification timed out.')); }, DEADLINE_MS); })]); }
  finally { clearTimeout(timer); }
};
try {
  const source = await synthesize('Ek chhoti kavita likho aur file mein save karo.');
  const mp3 = path.join(root, 'request.mp3'), wav = path.join(root, 'request.wav');
  fs.writeFileSync(mp3, source);
  const converted = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-i', mp3, '-ac', '1', '-ar', String(PCM_RATE_HZ), wav], { encoding: 'utf8', windowsHide: true });
  if (converted.status !== 0) throw new Error('ffmpeg could not convert the generated speech fixture.');
  const heard = await transcribeAudio({ config, wavPath: wav });
  assert.ok(heard.text.trim());
  const context = () => captureVoiceContext(parent);
  // Explicit target constraints are fixture data added after STT, not a claim of perfect spoken filename recognition.
  const a = await jobs.submit({ ownerId: parent.sessionId, transcript: `${heard.text}\nFixture constraint: write a short poem to alpha.txt with write_file, then read_file to verify it. No other paths.`, context: context() });
  firstId = a.id;
  await deadline(firstLease.promise);
  const c = await jobs.submit({ ownerId: parent.sessionId, transcript: `Read alpha.txt, keep the complete existing poem, append exactly '${EDIT_MARKER}', and save alpha.txt. Read before writing.`, context: context() });
  await deadline(conflictingWait.promise);
  const b = await jobs.submit({ ownerId: parent.sessionId, transcript: 'Write a short original poem to beta.txt with write_file, then read_file to verify it. No other paths.', context: context() });
  const second = await deadline(jobs.waitFor(b.id, { ownerId: parent.sessionId }));
  assert.equal(second.task.status, 'done', second.task.error);
  assert.equal(jobs.result(a.id, { ownerId: parent.sessionId }).status, 'running');
  assert.equal(jobs.result(c.id, { ownerId: parent.sessionId }).status, 'waiting_for_resource');
  releaseFirst.resolve();
  const [first, conflict] = await deadline(Promise.all([a, c].map(job => jobs.waitFor(job.id, { ownerId: parent.sessionId }))));
  assert.equal(first.task.status, 'done', first.task.error); assert.equal(conflict.task.status, 'done', conflict.task.error);
  const alpha = fs.readFileSync(path.join(workspace, 'alpha.txt'), 'utf8');
  assert.ok(alpha.includes(EDIT_MARKER)); assert.ok(alpha.length > EDIT_MARKER.length);
  assert.ok(fs.readFileSync(path.join(workspace, 'beta.txt'), 'utf8').length > 0);
  await deadline(Promise.all(reports)); await speech.drain();
  assert.equal(clips.length, 3); assert.ok(clips.every(bytes => bytes > 0)); assert.equal(peakPlayers, 1);
  console.log('PARALLEL_VOICE_LIVE_OK', JSON.stringify({ jobs: 3, realFileTools: true, independentFinishedBeforeFirstReleased: true,
    conflictWaitObserved: true, sameFilePreserved: true, realSarvamSTT: true, realSarvamTTSClips: clips.length, peakPlayers,
    input: 'generated speech; explicit fixture filenames after STT', output: 'captured MP3 handoff; no microphone or speaker', hold: 'deliberate first-file gate to prove concurrency and conflict handling' }));
} catch (error) { console.error(redactText(error.message, { secrets })); process.exitCode = 1; }
finally { releaseFirst.resolve(); await jobs.close(); await speech.close(); fs.rmSync(root, { recursive: true, force: true }); }
