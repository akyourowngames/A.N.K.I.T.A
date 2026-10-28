/**
 * Real Sarvam -> Meta planner -> file tools -> Sarvam check, without a microphone.
 * Does not clear the three-run physical mic/VS Code demonstration gate.
 * Usage: node scripts/verify-voice-delegation.mjs [--planner-only] [--long-report] [--play]
 * All files live in an OS temporary workspace; keys are never printed.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { loadConfig } from '../src/core/config.mjs';
import { Agent } from '../src/core/agent.mjs';
import { configuredSecrets, redactText } from '../src/core/redact.mjs';
import { createVoiceBrain, withVoiceBrain, createAcknowledgements } from '../src/core/voice-session.mjs';
import { createVoiceNarrator } from '../src/core/voice-narrator.mjs';
import { VoiceTaskStore, runVoiceTask, renderVoiceTask } from '../src/automation/voice-task.mjs';
import { synthesizeSarvam, transcribeAudio, chooseSarvamLanguage, resolveSarvamSpeaker, playMp3, summarizeForSpeech } from '../src/channels/voice.mjs';

const ROUNDS = 3; // Consecutive synthetic terminal runs; physical microphone gate remains separate.
const SAMPLE_RATE_HZ = 16000; // Mono PCM format used by the real microphone capture path.
const MAX_STT_AUDIO_SECONDS = 30; // Sarvam synchronous STT clip limit.
const EXPECTED_CONTENT = 'Workspace ready'; // Script-only fixture, never production task truth.
const SPOKEN_REQUEST = 'Workspace mein ek file banao aur usko padh kar batao.';
const COMMAND_WORDS = [/workspace/i, /file/i]; // Fail synthetic takes whose command nouns were lost.
const flags = new Set(process.argv.slice(2));
const plannerOnly = flags.has('--planner-only');
const shouldPlay = flags.has('--play');
const narrationOnly = flags.has('--narration-only');
const LONG_REPORT_SECTIONS = 18; // Script-only sections: exercise file arguments larger than the old 1024-token cap.
const expectedContent = flags.has('--long-report') ? '# Synthetic report for voice save verification\n\n' +
  Array.from({ length: LONG_REPORT_SECTIONS }, (_, index) => `## Finding ${index + 1}\n\n` +
    `This is synthetic test evidence for section ${index + 1}, not a real security advisory. ` +
    'Preserve the full observation, the affected component, the validation steps, and the expected follow-up. ' +
    'Check the source before making a claim, record what actually ran, and keep unresolved questions visible.\n\n').join('')
  : EXPECTED_CONTENT;
const loaded = loadConfig();
const secrets = configuredSecrets(loaded);
const config = { ...loaded, voiceProvider: 'baseten', tools: true, autoApprove: false,
  sttProvider: 'sarvam', memoryConsolidation: false, embeddings: false, subagentsEnabled: false,
  projectAutoDetect: false, projectWorkCapture: false, projectAutoMaintenance: false };
const brain = createVoiceBrain(config);
if (!plannerOnly && !config.sarvamApiKey) throw new Error('Set SARVAM_API_KEY locally, or use --planner-only.');
if (!plannerOnly) for (const binary of ['ffmpeg', 'ffprobe']) {
  if (spawnSync(binary, ['-version'], { stdio: 'ignore' }).status !== 0) throw new Error(`${binary} is required on PATH.`);
}

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-delegation-live-'));
const synthesize = (text, language = 'hi-IN') => synthesizeSarvam({ apiKey: config.sarvamApiKey,
  model: config.sarvamTtsModel, speaker: resolveSarvamSpeaker(config, language), languageCode: language, text });
const acknowledgements = createAcknowledgements({ synthesize });
const narrate = createVoiceNarrator({ client: brain.client, model: brain.model, secrets,
  onDiagnostic: flags.has('--narration-only') ? data => console.log(JSON.stringify({ stage: 'narration-diagnostic', ...data })) : undefined,
});
const rows = [];
try {
  if (narrationOnly) {
    const narrationCases = [
      { kind: 'step', phase: 'started', transcript: 'Write a random poem and open it in Notepad.', call: { function: { name: 'write_file', arguments: JSON.stringify({ path: 'poem.txt' }) } } },
      { kind: 'step', phase: 'started', transcript: 'Write a random poem and open it in Notepad.',
        call: { function: { name: 'run_command', arguments: JSON.stringify({ command: 'notepad poem.txt', background: true }) } },
        steps: [{ tool: 'write_file', target: 'poem.txt', state: 'done', confirmation: 'confirmed' }, { tool: 'run_command', program: 'notepad', state: 'running' }],
        previousUpdate: 'I am saving your poem.' },
      { kind: 'waiting', transcript: 'Write a random poem and open it in Notepad.', elapsedMs: 12000, steps: [{ tool: 'write_file', target: 'poem.txt', state: 'done', confirmation: 'confirmed' }, { tool: 'run_command', program: 'notepad', background: true, state: 'done', confirmation: 'submitted' }] },
      { kind: 'step_result', phase: 'completed', transcript: 'Ek kavita likho aur Notepad mein kholo.', language: 'hi-IN',
        action: { tool: 'write_file', target: 'kavita.txt' }, steps: [{ tool: 'write_file', target: 'kavita.txt', state: 'done', confirmation: 'confirmed' }] },
    ];
    for (const event of narrationCases) {
      const started = performance.now();
      const line = await narrate(event);
      if (!line) { rows.push({ kind: event.kind, ok: false }); console.error('Narration was skipped; see diagnostic above.'); continue; }
      assert.ok(!line.includes('write_file'));
      const modelMs = Math.round(performance.now() - started);
      const audio = await synthesize(line, chooseSarvamLanguage({ text: line, detected: event.language || 'en-IN' }));
      assert.ok(audio.length);
      if (shouldPlay) await playMp3(audio);
      console.log(JSON.stringify({ kind: event.kind, line, modelMs, audioBytes: audio.length, played: shouldPlay }));
      rows.push({ kind: event.kind, ok: true });
    }
    assert.ok(rows.every(row => row.ok), 'Some live narration probes were skipped or failed.');
    console.log(`OK: ${narrationCases.length}/${narrationCases.length} generated narration lines and real Sarvam speech.`);
    process.exitCode = 0;
  } else {
  const warmStarted = performance.now();
  if (!plannerOnly) await acknowledgements.prewarm();
  console.log(JSON.stringify({ stage: 'ack-warmup', ms: Math.round(performance.now() - warmStarted), microphone: false }));
  for (let round = 1; round <= ROUNDS; round++) {
    const workspace = path.join(root, `take-${round}`);
    fs.mkdirSync(workspace);
    const target = path.join(workspace, flags.has('--long-report') ? 'findings.md' : 'demo-note.txt');
    const store = new VoiceTaskStore({ directory: path.join(workspace, 'tasks'), secrets });
    let heard = { text: SPOKEN_REQUEST, languageCode: 'hi-IN', confidence: null };
    let sttMs = null;
    let audioSeconds = null;
    if (!plannerOnly) {
      const mp3 = path.join(workspace, 'request.mp3');
      const wav = path.join(workspace, 'request.wav');
      fs.writeFileSync(mp3, await synthesize(SPOKEN_REQUEST));
      const conversion = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-i', mp3,
        '-ac', '1', '-ar', String(SAMPLE_RATE_HZ), '-c:a', 'pcm_s16le', wav], { encoding: 'utf8' });
      assert.equal(conversion.status, 0, conversion.stderr);
      const probe = spawnSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', wav], { encoding: 'utf8' });
      audioSeconds = Number(probe.stdout.trim());
      console.log(JSON.stringify({ round, stage: 'input-audio', audioSeconds }));
      assert.ok(audioSeconds > 0 && audioSeconds < MAX_STT_AUDIO_SECONDS, 'Generated input must fit the STT duration limit.');
      const started = performance.now();
      heard = await transcribeAudio({ config, wavPath: wav });
      sttMs = Math.round(performance.now() - started);
      assert.ok(heard.text.trim(), 'STT must return words.');
      for (const word of COMMAND_WORDS) assert.match(heard.text, word, 'A command word was misheard; this is not a clean take.');
    }
    console.log(`Heard: ${heard.text}`);
    let active;
    let approvals = 0;
    const agent = new Agent({ client: brain.client, config, workspacePath: workspace, autoProject: false,
      allowedTools: new Set(['write_file', 'read_file']), deferTools: false, skillsEnabled: false, memoryEnabled: false,
      confirm: async name => active.approval(name, async () => { approvals++; return name === 'write_file'; }),
      print: () => {}, write: () => {},
    });
    agent.model = brain.model;
    const ackStarted = performance.now();
    const ack = plannerOnly ? null : acknowledgements.next(heard.languageCode);
    const ackSelectedMs = performance.now() - ackStarted;
    let ackPlaying = Boolean(ack && shouldPlay);
    const ackPlayback = ackPlaying ? playMp3(ack.audio).finally(() => { ackPlaying = false; }) : Promise.resolve();
    let firstText;
    let progressLines = 0;
    let progressAudio = 0;
    const started = performance.now();
    const { task } = await runVoiceTask({ store, transcript: heard.text, language: heard.languageCode, confidence: heard.confidence,
      onTrackingError: () => agent.cancel(), isPlaying: () => ackPlaying,
      speak: plannerOnly ? undefined : async (event, { signal, beginPlayback }) => {
        const line = await narrate(event, { signal });
        if (!line || signal.aborted) return;
        progressLines++;
        const audio = await synthesize(line, chooseSarvamLanguage({ text: line, detected: heard.languageCode }));
        if (!signal.aborted) { progressAudio += audio.length; if (shouldPlay && beginPlayback()) await playMp3(audio, { signal }); }
      },
      run: async (observer, task) => {
        active = task;
        const text = await withVoiceBrain(agent, brain, () => agent.send(
          `${heard.text}\nFor this isolated test: write exactly ${JSON.stringify(expectedContent)} to ${target}, then read that file with read_file. ` +
          'Use both real tools, then give one short Hinglish sentence. Do not merely describe a plan.',
          { ...observer, onDelta: () => { firstText ??= performance.now(); } }));
        return { text, error: agent.cancelled() ? 'cancelled' : null };
      },
    });
    await ackPlayback;
    assert.equal(task.status, 'done', task.error || task.summary);
    assert.equal(fs.readFileSync(target, 'utf8').trim(), expectedContent.trim());
    for (const tool of ['write_file', 'read_file']) assert.ok(task.steps.some(step => step.tool === tool && step.state === 'done'), `${tool} must have a real successful step.`);
    assert.ok(approvals > 0, 'The existing write approval gate must run.');
    let reportMs = null;
    let reportBytes = null;
    if (!plannerOnly) {
      const reportStarted = performance.now();
      const report = summarizeForSpeech(task.summary, { maxChars: config.voiceSpeakMaxChars });
      const audio = await synthesize(report, chooseSarvamLanguage({ text: report, detected: heard.languageCode }));
      reportMs = Math.round(performance.now() - reportStarted);
      reportBytes = audio.length;
      assert.ok(reportBytes > 0);
      if (shouldPlay) await playMp3(audio);
    }
    console.log(renderVoiceTask(task));
    rows.push({ round, model: brain.model, audioSeconds, sttMs, ackSelectedMs: Number(ackSelectedMs.toFixed(3)), ackBytes: ack?.audio.length ?? null,
      firstTextMs: Math.round(firstText - started), taskMs: task.endedAt - task.startedAt,
      steps: task.steps.length, approvals, progressLines, progressAudio, reportMs, reportBytes, savedCharacters: expectedContent.length, status: task.status });
  }
  console.table(rows);
  console.log(`OK: ${rows.length}/${ROUNDS} ${plannerOnly ? 'planner-only' : 'synthetic speech'} delegations. Physical mic/VS Code gate: NOT RUN.`);
  }
} catch (error) {
  console.error(redactText(error.message, { secrets }));
  process.exitCode = 1;
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}
