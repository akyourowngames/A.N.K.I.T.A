/** Real Sarvam input/output and Meta speech decisions; simulated interruption, no physical audio. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { loadConfig } from '../src/core/config.mjs';
import { Agent } from '../src/core/agent.mjs';
import { createVoiceBrain, createVoiceReportSpeech } from '../src/core/voice-session.mjs';
import { captureVoiceContext, runVoiceWorker } from '../src/core/voice-worker.mjs';
import { VoiceSpeechQueue } from '../src/automation/voice-speech-queue.mjs';
import { VOICE_JOBS_TOOL, VOICE_REPORTS_TOOL } from '../src/automation/voice-task-policy.mjs';
import { synthesizeSarvam, transcribeAudio, convertAudio, chooseSarvamLanguage, resolveSarvamSpeaker } from '../src/channels/voice.mjs';
import { configuredSecrets, redactText } from '../src/core/redact.mjs';

const ENV_FLAG = '--env';
const DEADLINE_MS = 90000; // Milliseconds/case: bound cloud verification without leaving a hung captured player.
const REPORTS = Object.freeze({ first: 'The research is ready. The sources are saved.', next: 'Your poem is saved.' }); // Disposable spoken fixtures.
const CASES = [
  { text: 'Haan bas, ab agli report sunao.', action: 'next' },
  { text: 'Please continue where you stopped.', action: 'resume' },
  { text: 'Start that report again from the beginning.', action: 'repeat' },
  { text: 'Skip reading the rest of that report.', action: 'dismiss' },
  { text: 'By the way, what is two plus two?', action: null },
  { text: 'Okay, then what?', action: 'contextual' }, // Ambiguous: record its contextual decision rather than mandate one interpretation.
];
const envIndex = process.argv.indexOf(ENV_FLAG);
const config = { ...loadConfig(envIndex < 0 ? undefined : process.argv[envIndex + 1]), voiceProvider: 'baseten',
  sttProvider: 'sarvam', ttsProvider: 'sarvam', tools: true, autoApprove: true, memoryConsolidation: false,
  projectAutoDetect: false, projectWorkCapture: false };
const brain = createVoiceBrain(config), secrets = configuredSecrets(config);
if (!config.sarvamApiKey) throw new Error('Restore SARVAM_API_KEY locally before the real speech interruption check.');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-interruption-live-'));
const parent = new Agent({ config, client: brain.client, workspacePath: root, memoryEnabled: false, skillsEnabled: false });
const allowedTools = new Set([VOICE_JOBS_TOOL, VOICE_REPORTS_TOOL]); // Fixture permits speech decisions only, no external effects.
class SpeechAgent extends Agent { constructor(options) { super({ ...options, allowedTools }); } }
const cache = new Map(), results = [];
const synthesize = text => {
  if (!cache.has(text)) {
    const languageCode = chooseSarvamLanguage({ text, detected: 'hi-IN' });
    cache.set(text, synthesizeSarvam({ apiKey: config.sarvamApiKey, model: config.sarvamTtsModel,
      speaker: resolveSarvamSpeaker(config, languageCode), languageCode, text }));
  }
  return cache.get(text);
};
const bounded = async work => {
  let timer;
  try { return await Promise.race([work, new Promise((_resolve, reject) => { timer = setTimeout(() => reject(new Error('Speech interruption verification timed out.')), DEADLINE_MS); })]); }
  finally { clearTimeout(timer); }
};
try {
  for (const [index, scenario] of CASES.entries()) {
    const played = [], actions = [], session = new AbortController();
    let active = 0, peak = 0, held = false, ready;
    const speaking = new Promise(resolve => { ready = resolve; });
    const queue = new VoiceSpeechQueue({ gapMs: 0, play: async (audio, { signal }) => {
      assert.ok(audio.length > 0);
      const entry = queue.active, sentence = entry.parts[entry.cursor].text;
      active++; peak = Math.max(peak, active); played.push({ id: entry.jobId, sentence });
      try {
        if (entry.jobId === 'research' && entry.cursor === 1 && !held) {
          held = true; ready(); await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }));
        }
      } finally { active--; }
    } });
    try {
      void queue.offer(createVoiceReportSpeech({ jobId: 'research', label: 'Research results', text: REPORTS.first, synthesize, signal: session.signal }));
      await bounded(speaking);
      void queue.offer(createVoiceReportSpeech({ jobId: 'poem', label: 'Poem result', text: REPORTS.next, synthesize, signal: session.signal }));
      const turn = queue.interrupt();
      const source = await synthesize(scenario.text), wav = await convertAudio(source, { to: 'wav' });
      const wavPath = path.join(root, `request-${index}.wav`); fs.writeFileSync(wavPath, wav);
      const heard = await bounded(transcribeAudio({ config, wavPath })); assert.ok(heard.text.trim());
      queue.acceptTurn(turn); queue.resume();
      const entry = { id: `interruption-${index}`, ownerId: parent.sessionId, transcript: heard.text,
        context: { ...captureVoiceContext(parent), speech: { queue, turn, signal: session.signal } } };
      const outcome = await bounded(runVoiceWorker(entry, { signal: session.signal,
        observer: { onToolCall: call => { if (call.function.name === VOICE_REPORTS_TOOL) actions.push(JSON.parse(call.function.arguments).action); } },
        controlTool: { name: VOICE_JOBS_TOOL, parameters: { type: 'object' }, run: () => '[]' },
      }, { AgentClass: SpeechAgent, brain }));
      if (!outcome.speechHandled) void queue.offer(createVoiceReportSpeech({ jobId: entry.id, label: heard.text,
        text: outcome.text, synthesize, signal: session.signal, turn }));
      queue.finishTurn(turn); await bounded(queue.drain());
      assert.equal(peak, 1);
      if (scenario.action && scenario.action !== 'contextual') assert.ok(actions.includes(scenario.action), JSON.stringify({ heard: heard.text, actions, answer: outcome.text }));
      if (scenario.action === null) {
        assert.equal(queue.reportState().find(row => row.id === 'research').state, 'suspended');
        assert.ok(played.some(row => row.id === entry.id));
      }
      const firstCount = played.filter(row => row.sentence === 'The research is ready.').length;
      assert.equal(firstCount, scenario.action === 'repeat' ? 2 : 1);
      const result = { request: scenario.text, transcript: heard.text, expected: scenario.action, actions,
        speechHandled: outcome.speechHandled, peakPlayers: peak, played: played.map(row => row.sentence) };
      results.push(result); console.log('VOICE_INTERRUPTION_CASE_OK', JSON.stringify(result));
    } finally { session.abort(); await queue.close(); }
  }
  console.log('VOICE_INTERRUPTION_LIVE_OK', JSON.stringify({ cases: results.length, realMeta: true, realSarvamSTT: true,
    realSarvamTTS: true, input: 'generated English/Hinglish, simulated VAD', output: 'captured sentence MP3 handoffs; no physical microphone or speaker' }));
} catch (error) { console.error(redactText(error.message, { secrets })); process.exitCode = 1; }
finally { fs.rmSync(root, { recursive: true, force: true }); }
