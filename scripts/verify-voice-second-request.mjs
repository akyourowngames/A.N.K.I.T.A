/** Real concurrent Meta decisions with disposable file/web tools; no microphone or app launching. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { loadConfig } from '../src/core/config.mjs';
import { Agent } from '../src/core/agent.mjs';
import { createVoiceBrain } from '../src/core/voice-session.mjs';
import { captureVoiceContext, runVoiceWorker } from '../src/core/voice-worker.mjs';
import { VoiceJobs } from '../src/automation/voice-jobs.mjs';
import { VoiceTaskStore } from '../src/automation/voice-task.mjs';
import { configuredSecrets, redactText } from '../src/core/redact.mjs';

const ENV_FLAG = '--env';
const INJECT_EMPTY_FLAG = '--inject-empty'; // Controlled fault only: discard one unexecuted real model decision after a successful save.
const DEADLINE_MS = 90000; // Milliseconds: bound the real search/model check, not production work.
const FIXTURE_TOOLS = new Set(['read_file', 'write_file', 'web_search', 'web_fetch', 'find_tools']);
const envIndex = process.argv.indexOf(ENV_FLAG);
const config = { ...loadConfig(envIndex < 0 ? undefined : process.argv[envIndex + 1]), tools: true, autoApprove: true,
  voiceProvider: 'baseten', memoryConsolidation: false, projectAutoDetect: false, projectWorkCapture: false };
const brain = createVoiceBrain(config);
const secrets = configuredSecrets(config);
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-second-request-'));
const workspace = path.join(root, 'workspace'); fs.mkdirSync(workspace);
const requests = [], inspecting = [];
let injectedEmpty = false;
const originalFetch = globalThis.fetch;
globalThis.fetch = async (url, options) => {
  const response = await originalFetch(url, options);
  if (String(url) === `${brain.client.baseUrl}/chat/completions`) {
    const body = JSON.parse(options.body);
    const record = { status: response.status, requestBytes: Buffer.byteLength(options.body), maxTokens: body.max_tokens,
      lastRole: body.messages.at(-1)?.role, tools: body.tools?.length || 0, choices: 0, textChars: 0, toolFragments: 0, reasons: [], error: false };
    requests.push(record);
    inspecting.push(response.clone().text().then(raw => {
      const frames = response.headers.get('content-type')?.includes('application/json') ? [JSON.parse(raw)] :
        raw.split('\n').filter(line => line.startsWith('data:') && line.slice(5).trim() !== '[DONE]').map(line => JSON.parse(line.slice(5)));
      for (const frame of frames) {
        record.error ||= Boolean(frame.error); record.choices += frame.choices?.length || 0;
        for (const choice of frame.choices || []) {
          const message = choice.delta || choice.message || {};
          record.textChars += message.content?.length || 0; record.toolFragments += message.tool_calls?.length || 0;
          if (choice.finish_reason) record.reasons.push(choice.finish_reason);
        }
      }
    }).catch(() => { record.parseFailed = true; }));
    const last = body.messages.at(-1);
    const savedNews = last?.role === 'tool' && body.messages.some(message => message.tool_calls?.some(call =>
      call.id === last.tool_call_id && call.function.name === 'write_file' && JSON.parse(call.function.arguments).path === 'news.md'));
    if (process.argv.includes(INJECT_EMPTY_FLAG) && !injectedEmpty && savedNews && response.ok) {
      injectedEmpty = record.injectedEmpty = true;
      return new Response(`data: ${JSON.stringify({ choices: [{ delta: { reasoning_content: 'Controlled empty-decision fault.' }, finish_reason: 'stop' }] })}\n\ndata: [DONE]\n\n`,
        { headers: { 'content-type': 'text/event-stream' } });
    }
  }
  return response;
};
class FixtureAgent extends Agent { constructor(options) { super({ ...options, allowedTools: FIXTURE_TOOLS }); } }
const parent = new Agent({ config, client: brain.client, memoryEnabled: false, workspacePath: workspace });
const jobs = new VoiceJobs({ store: new VoiceTaskStore({ directory: path.join(root, 'jobs'), secrets }),
  run: (entry, options) => runVoiceWorker(entry, options, { AgentClass: FixtureAgent, brain, acquire: (...args) => jobs.acquire(...args) }),
});
let timer;
try {
  const transcripts = [
    'Write a short original poem to poem.txt using write_file. Read it back, then give a brief result. Use only relative paths inside this workspace.',
    'Research the latest AI news using web_search, save useful findings and source URLs to news.md using write_file, then read it back and give a brief result. Use only relative paths inside this workspace.',
  ];
  const first = await jobs.submit({ ownerId: parent.sessionId, transcript: transcripts[0], context: captureVoiceContext(parent) });
  const second = await jobs.submit({ ownerId: parent.sessionId, transcript: transcripts[1], context: captureVoiceContext(parent) });
  const results = await Promise.race([Promise.all([first, second].map(job => jobs.waitFor(job.id, { ownerId: parent.sessionId }))),
    new Promise((_resolve, reject) => { timer = setTimeout(() => reject(new Error('Concurrent real planner verification timed out.')), DEADLINE_MS); })]);
  await Promise.all(inspecting);
  const outcomes = results.map(({ task }, index) => ({ request: index + 1, status: task.status, summaryChars: task.summary.length,
    error: task.error, steps: task.steps.map(step => ({ tool: step.tool, state: step.state })) }));
  console.log('VOICE_SECOND_REQUEST_TRACE', JSON.stringify({ requests, outcomes }));
  assert.ok(results.every(({ task }) => task.summary.trim()), 'Both real planners must return a report.');
  assert.ok(fs.readFileSync(path.join(workspace, 'poem.txt'), 'utf8').trim());
  assert.ok(fs.readFileSync(path.join(workspace, 'news.md'), 'utf8').trim());
  const researchSteps = results[1].task.steps;
  const saved = researchSteps.findIndex(step => step.tool === 'write_file' && step.state === 'done');
  assert.ok(saved >= 0 && researchSteps.some((step, index) => index > saved && step.tool === 'read_file' && step.state === 'done'),
    'The second task must finish its read-back after saving, even across an empty decision.');
  if (process.argv.includes(INJECT_EMPTY_FLAG)) assert.equal(injectedEmpty, true);
  console.log('VOICE_SECOND_REQUEST_LIVE_OK', JSON.stringify({ realMeta: true, independentWorkers: 2, realWebSearch: true, files: 2,
    input: 'text; isolates planner from microphone and speech output', launch: 'not exercised', controlledEmptyAfterSave: injectedEmpty }));
} catch (error) { console.error(redactText(error.message, { secrets })); console.log('VOICE_SECOND_REQUEST_TRACE', JSON.stringify({ requests })); process.exitCode = 1; }
finally { clearTimeout(timer); await jobs.close(); globalThis.fetch = originalFetch; await Promise.allSettled(inspecting); fs.rmSync(root, { recursive: true, force: true }); }
