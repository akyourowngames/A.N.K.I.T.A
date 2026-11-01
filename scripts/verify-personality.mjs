import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { stripForSpeech } from '../src/channels/voice.mjs';
import { Agent } from '../src/core/agent.mjs';
import { loadConfig, CONFIG_DIR } from '../src/core/config.mjs';
import { DesktopSettingsStore, applyDesktopSettings } from '../desktop/electron/settings.mjs';
import { createVoiceBrain, createVoiceReportSpeech } from '../src/core/voice-session.mjs';
import { captureVoiceContext, runVoiceWorker } from '../src/core/voice-worker.mjs';
import { VOICE_JOBS_TOOL } from '../src/automation/voice-task-policy.mjs';
import { configuredSecrets, redactText } from '../src/core/redact.mjs';

const DEFAULT_EVALUATION_PROVIDER = 'baseten'; // Owner's selected voice planner; model and endpoint stay runtime-configured.
const OUTPUT_TOKENS = 1536; // Tokens including mandatory reasoning: enough for brief replies and small real file actions.
const TIMEOUT_MS = 60_000; // Milliseconds per independent model case.
const MAX_SENTENCES = 2; // Complete generated sentences: the owner's voice reply limit, checked before playback truncation.
const MAX_REPLY_WORDS = 40; // Words: allow natural Hinglish while rejecting long performed banter.
const POEM_LINES = 4; // Lines: the exact disposable artifact requested below.
const MAX_TOOL_ROUNDS = 6; // Rounds: allow discovery/write/read without an open-ended evaluator.
const MAX_TOOL_CALLS = 8; // Calls: bounded local-only evaluation.
const FILE_NAME = 'personality-poem.txt'; // Disposable evaluation artifact inside an OS-created workspace.
const config = applyDesktopSettings(loadConfig(), new DesktopSettingsStore(path.join(CONFIG_DIR, 'desktop-settings.json')).load().data);
const secrets = configuredSecrets(config);
const brain = createVoiceBrain({ ...config, voiceProvider: config.voiceProvider || DEFAULT_EVALUATION_PROVIDER });
if (!brain?.client || !brain.model) throw new Error('Configure the voice planner before running the personality evaluation.');
const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-personality-live-'));
const cases = [
  { id: 'caring-attitude', prompt: 'Main phir kaam taal raha hoon. Thoda daant de, par help bhi kar.' },
  { id: 'respect-feelings', prompt: 'Aaj bahut bura lag raha hai. Mazaak mat kar, bas meri baat sun.' },
  { id: 'owns-mistake', history: [{role:'user',content:'2+2 kitna hai?'},{role:'assistant',content:'5.'}], prompt: 'Tune 2+2 ko 5 bol diya tha. Galat hai.' },
  { id: 'real-file-task', tools: true, prompt: `Write a four-line original poem to ${FILE_NAME} in this workspace, then read the file back to confirm it saved. Reply to me in Hinglish.` },
];
const controlTool = { name: VOICE_JOBS_TOOL, description: 'Inspect other evaluation jobs; there are none in this isolated conversation.', parameters: {type:'object',properties:{}}, needsApproval: false, run: () => '[]' };
class EvaluationAgent extends Agent {
  constructor(options) { super({ ...options, allowedTools: new Set(options.config.tools ? ['write_file', 'read_file', VOICE_JOBS_TOOL] : []) }); }
}
try {
  const results = await Promise.allSettled(cases.map(async item => {
    const cwd = path.join(directory, item.id); await fs.mkdir(cwd);
    const parent = new Agent({ client: brain.client, config: { ...config, tools: Boolean(item.tools), model: brain.model, maxTokens: OUTPUT_TOKENS, maxTokensExplicit: true, autoApprove: true, subagentsEnabled: false, maxToolSteps: MAX_TOOL_ROUNDS, maxToolCalls: MAX_TOOL_CALLS },
      memoryEnabled: false, skillsEnabled: false, autoProject: false, workspacePath: cwd, print: () => {}, write: () => {} });
    if (item.history) parent.messages.push(...item.history);
    const tools = [], start = performance.now();
    const outcome = await runVoiceWorker({ id: item.id, ownerId: 'personality-evaluation', transcript: item.prompt, context: captureVoiceContext(parent) },
      { observer: { onToolResult: call => tools.push(call.name || call.function?.name) }, signal: AbortSignal.timeout(TIMEOUT_MS), controlTool },
      { AgentClass: EvaluationAgent, brain, autoApprove: () => true, acquire: async () => {} });
    assert.ok(outcome.text?.trim(), 'Each case needs a real final reply');
    assert.ok(!outcome.error, 'The case must finish without an execution-policy failure');

    if (item.tools) {
      const poem = await fs.readFile(path.join(cwd, FILE_NAME), 'utf8');
      assert.ok(poem.trim().split(/\r?\n/).length >= POEM_LINES, 'The real file contains the requested poem');
      assert.ok(tools.includes('write_file') && tools.includes('read_file'), 'Saving and read-back must both actually execute');
    }
    const report = createVoiceReportSpeech({ jobId: item.id, label: item.id, text: outcome.text, synthesize: async () => null });
    const rawSentences = [...new Intl.Segmenter('en', {granularity:'sentence'}).segment(stripForSpeech(outcome.text))].filter(item=>item.segment.trim()).length;
    const spokenWords = stripForSpeech(report.text).split(/\s+/u).length;
    const result = { rawSentences, spokenWords, draftOverSentenceBudget: rawSentences > MAX_SENTENCES, spokenOverWordTarget: spokenWords > MAX_REPLY_WORDS, id: item.id, prompt: item.prompt, reply: redactText(outcome.text, {secrets}), spoken: redactText(report.text, {secrets}), tools, elapsedMs: Math.round(performance.now()-start), fileVerified: Boolean(item.tools) };
    console.log(JSON.stringify(result));
    const spoken = stripForSpeech(report.text);
    const sentences = [...new Intl.Segmenter('en', {granularity:'sentence'}).segment(spoken)].filter(item => item.segment.trim());
    assert.ok(sentences.length <= MAX_SENTENCES, item.id + ': spoken report exceeded the sentence budget');
    // Word count and raw draft length are diagnostic targets, not guaranteed model behavior.
    return result;
  }));
  const failures = results.filter(result => result.status === 'rejected');
  for (const failure of failures) console.error(redactText(failure.reason?.message || 'Evaluation failed', {secrets}));
  assert.equal(failures.length, 0, 'Every live case must satisfy the checks');
  console.log(`PERSONALITY_LIVE_OK: ${results.length}/${cases.length}; configured voice planner; real Agent/voice worker; actual file write and read-back; production speech limits. Raw generation length and tone require qualitative review.`);
} catch (error) {
  console.error(redactText(error.message, {secrets})); process.exitCode = 1;
} finally {
  await fs.rm(directory, {recursive:true,force:true}); // Only this script's OS-created temporary workspace; no user artifact is touched.
}
