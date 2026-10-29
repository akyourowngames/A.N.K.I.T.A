import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { Agent } from '../../src/core/agent.mjs';
import { captureVoiceContext, runVoiceWorker } from '../../src/core/voice-worker.mjs';
import { VoiceJobs } from '../../src/automation/voice-jobs.mjs';
import { VoiceTaskStore } from '../../src/automation/voice-task.mjs';
import { isVoiceCheck, checkMessage } from '../helpers/voice-check.mjs';
import { createVoiceCompletion } from '../../src/core/voice-completion.mjs';

const call = (id, name, args) => ({ content: '', tool_calls: [{ id, type: 'function', function: { name, arguments: JSON.stringify(args) } }] });

async function fixture(t, reply, { approve = true, review = () => 'COMPLETE', config = {}, browserManager } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-completion-'));
  const bodies = [], checks = [], streamed = [], started = [], workers = [];
  const server = http.createServer(async (request, response) => {
    let raw = ''; for await (const chunk of request) raw += chunk;
    const body = JSON.parse(raw);
    let message;
    if (isVoiceCheck(body)) { const data = JSON.parse(body.messages[1].content); checks.push(data); message = checkMessage(await review(data, checks.length)); }
    else { bodies.push(body); message = await reply(body, bodies.length); }
    response.setHeader('Content-Type', 'application/json');
    response.end(JSON.stringify({ usage: { prompt_tokens: 3, completion_tokens: 1 }, choices: [{ message, finish_reason: message.tool_calls?.length ? 'tool_calls' : 'stop' }] }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const client = { baseUrl: `http://127.0.0.1:${server.address().port}`, headers: () => ({}) };
  const parent = new Agent({ client, config: { tools: true, contextWindow: 131072, maxToolSteps: 6, autoApprove: false, memoryConsolidation: false, ...config },
    memoryEnabled: false, skillsEnabled: false, autoProject: false, workspacePath: root, browserManager });
  const jobs = new VoiceJobs({ store: new VoiceTaskStore({ directory: path.join(root, 'tasks') }),
    run: (entry, options) => runVoiceWorker(entry, options, { confirm: async () => approve, onWorker: worker => workers.push(worker),
      callbacks: { onDelta: text => streamed.push(text) }, toolContext: { onToolStart: step => started.push(step.name) } }),
  });
  t.after(async () => { await jobs.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); fs.rmSync(root, { recursive: true, force: true }); });
  return { root, parent, bodies, checks, streamed, started, workers, async run(transcript) {
    const job = await jobs.submit({ ownerId: parent.sessionId, transcript, context: captureVoiceContext(parent) });
    return (await jobs.waitFor(job.id, { ownerId: parent.sessionId })).task;
  } };
}

test('an unsupported draft is withheld and the same request completes real work once', async t => {
  const f = await fixture(t, (_body, round) => {
    if (round === 1) return { content: 'Your note is saved and ready.' };
    if (round === 2) return call('save', 'write_file', { path: 'note.md', content: 'Actual saved finding' });
    if (round === 3) return call('readback', 'read_file', { path: 'note.md' });
    return { content: 'Saved and checked note.md.' };
  }, { review: (_data, check) => check === 1 ? 'CONTINUE' : 'COMPLETE' });
  const task = await f.run('Save the finding in a note.');
  assert.equal(fs.readFileSync(path.join(f.root, 'note.md'), 'utf8'), 'Actual saved finding');
  assert.equal(task.status, 'done', task.error); assert.equal(task.summary, 'Saved and checked note.md.');
  assert.equal(f.bodies.length, 4); assert.equal(f.checks.length, 2);
  assert.equal(f.started.filter(name => name === 'write_file').length, 1);
  assert.equal(f.streamed.join('').includes('Your note is saved and ready.'), false);
  assert.deepEqual(task.steps.map(step => step.tool), ['write_file', 'read_file']);
  assert.equal(f.checks[0].receipts.length, 0);
  assert.equal(f.checks[1].receipts.find(row => row.id === 'save').started, true);
  assert.equal(f.checks[1].receipts.find(row => row.id === 'readback').ok, true);
});

test('even an erroneous COMPLETE check cannot approve zero actual work; recovery is bounded', async t => {
  const f = await fixture(t, () => ({ content: 'Playing music on YouTube now.' }));
  const task = await f.run('Play some music.');
  assert.equal(task.status, 'failed'); assert.match(task.error, /stopped before completing/i);
  assert.equal(task.summary, ''); assert.equal(f.bodies.length, 2); assert.equal(f.checks.length, 2);
  assert.deepEqual(f.streamed, []);
});

test('a conversational reply needs one generation and one small check, with no pretend work', async t => {
  const f = await fixture(t, () => ({ content: 'Doing well, thanks.' }), { review: () => 'ANSWER' });
  const task = await f.run('How are you?');
  assert.equal(task.status, 'done', task.error); assert.equal(f.bodies.length, 1); assert.equal(f.checks.length, 1);
  assert.deepEqual(task.steps, []); assert.equal(f.streamed.join(''), 'Doing well, thanks.');
  assert.equal(f.workers[0].turnUsage.prompt_tokens, 6, 'checker usage must be included');
  assert.equal(f.workers[0].turnUsage.completion_tokens, 2);
  assert.equal(f.workers[0].requestMetrics.filter(row => row.kind === 'voice_result_check').length, 1);
});

test('discovery alone cannot prove playback, and an observed blocker stays unfinished', async t => {
  const f = await fixture(t, (_body, round) => round === 1 ? call('discovery', 'find_tools', { query: 'browser' })
    : { content: round === 2 ? 'Music is playing.' : 'I have not started playback.' },
  { review: (_data, count) => count === 1 ? 'COMPLETE' : 'BLOCKED' });
  const task = await f.run('Play music.');
  assert.equal(task.status, 'failed'); assert.equal(task.summary, 'I have not started playback.');
  assert.equal(f.bodies.length, 3); assert.equal(f.streamed.join('').includes('Music is playing.'), false);
});

test('a real private voice control result can satisfy its own request without a duplicate control', async t => {
  const f = await fixture(t, (_body, round) => round === 1 ? call('status', 'voice_jobs', { action: 'list' })
    : { content: 'Your voice request is running.' });
  const task = await f.run('Tell me what is running.');
  assert.equal(task.status, 'done', task.error); assert.equal(f.bodies.length, 2); assert.equal(f.checks.length, 1);
  assert.deepEqual(task.steps.map(step => step.tool), ['voice_jobs']);
});

test('denied work cannot support completed speech or execute behind approval', async t => {
  const f = await fixture(t, (_body, round) => round === 1 ? call('save', 'write_file', { path: 'denied.md', content: 'Must not exist' })
    : { content: round === 2 ? 'Saved.' : 'Saving was denied.' },
  { approve: false, review: (_data, count) => count === 1 ? 'COMPLETE' : 'BLOCKED' });
  const task = await f.run('Save a note.');
  assert.equal(task.status, 'failed'); assert.equal(fs.existsSync(path.join(f.root, 'denied.md')), false);
  assert.equal(f.started.includes('write_file'), false); assert.equal(task.summary, 'Saving was denied.');
  assert.equal(f.checks[0].receipts[0].started, false); assert.equal(f.checks[0].receipts[0].ok, false);
});

test('an untested capability refusal is corrected instead of accepted as a blocker', async t => {
  const f = await fixture(t, (_body, round) => round === 1 ? { content: 'I cannot save files.' }
    : round === 2 ? call('save', 'write_file', { path: 'possible.txt', content: 'Available tool worked' })
      : { content: 'Saved possible.txt.' }, { review: (_data, count) => count === 1 ? 'BLOCKED' : 'COMPLETE' });
  const task = await f.run('Save a note.');
  assert.equal(task.status, 'done', task.error);
  assert.equal(fs.readFileSync(path.join(f.root, 'possible.txt'), 'utf8'), 'Available tool worked');
  assert.equal(f.streamed.join('').includes('I cannot save files.'), false);
});

test('a spent step budget cannot emit an unchecked forced summary', async t => {
  const f = await fixture(t, () => ({ content: 'Already saved it.' }), { config: { maxToolSteps: 1 } });
  const task = await f.run('Save a note.');
  assert.equal(task.status, 'failed'); assert.deepEqual(f.streamed, []); assert.equal(f.bodies.length, 1);
});

test('a malformed or empty result check fails closed without exposing the draft', async t => {
  const f = await fixture(t, () => ({ content: 'Playing now.' }), { review: () => '' });
  const task = await f.run('Play music.');
  assert.equal(task.status, 'failed'); assert.match(task.error, /result check was unavailable/i);
  assert.deepEqual(f.streamed, []); assert.equal(f.bodies.length, 1);
});

test('printed tool markup is never emitted even when the semantic checker accepts the draft', async t => {
  const f = await fixture(t, (_body, round) => round === 1 ? call('page', 'browser', { action: 'snapshot' })
    : { content: round === 2 ? '[tool call: browser]\n{"action":"snapshot"}' : 'The page was checked.' },
  { review: () => 'ANSWER', browserManager: { run: async () => 'Observed page.' } });
  const task = await f.run('Check the page.');
  assert.equal(task.status, 'done', task.error);
  assert.equal(f.streamed.join(''), 'The page was checked.');
});

test('a long candidate cannot hide an unsupported claim beyond the checker input limit', async t => {
  const long = 'Detail '.repeat(500) + 'Music is playing without any browser call.';
  const f = await fixture(t, (_body, round) => ({ content: round === 1 ? long : 'Short conversational answer.' }), { review: () => 'ANSWER' });
  const task = await f.run('Say hello.');
  assert.equal(task.status, 'done', task.error); assert.equal(task.summary, 'Short conversational answer.');
  assert.equal(f.checks.length, 1); assert.equal(f.checks[0].candidate, task.summary);
  assert.equal(f.streamed.join(''), task.summary);
});

test('an oversized original request is never silently clipped into a successful judgment', async t => {
  const f = await fixture(t, () => ({ content: 'Done.' }), { review: () => 'ANSWER' });
  const task = await f.run('Context '.repeat(500) + 'Also save this in a file.');
  assert.equal(task.status, 'failed'); assert.match(task.error, /too long/i);
  assert.equal(f.checks.length, 0); assert.deepEqual(f.streamed, []);
});

test('cancellation releases a check even while token preparation is still pending', async () => {
  let started, release;
  const entered = new Promise(resolve => { started = resolve; }), held = new Promise(resolve => { release = resolve; });
  const controller = new AbortController(), completion = createVoiceCompletion({ transcript: 'Hello' });
  let settled = false;
  const pending = completion.policy.review({ content: 'Hi.', tools: [], signal: controller.signal,
    client: { ensureToken: () => { started(); return held; } } }).finally(() => { settled = true; });
  const rejected = assert.rejects(pending, { name: 'AbortError' });
  await entered; controller.abort(); await new Promise(resolve => setImmediate(resolve));
  const settledBeforeAuth = settled;
  release(); await rejected;
  assert.equal(settledBeforeAuth, true, 'a stopped job must not retain its slot until an unrelated token fetch completes');
});

test('cancelling during the result check suppresses a late accepted draft', async t => {
  let began, release;
  const checking = new Promise(resolve => { began = resolve; }), held = new Promise(resolve => { release = resolve; });
  const f = await fixture(t, () => ({ content: 'A late answer.' }), { review: async () => { began(); return held; } });
  const pending = f.run('Hello');
  await checking; f.workers[0].cancel(); release('ANSWER');
  const task = await pending;
  assert.equal(task.status, 'cancelled'); assert.deepEqual(f.streamed, []);
});

test('large receipt histories remain bounded and explicitly mark omitted evidence', async t => {
  const f = await fixture(t, (_body, round) => round <= 12
    ? call(`read-${round}`, 'read_file', { path: `report-${round}.txt` }) : { content: 'Read the reports.' },
  { config: { maxToolSteps: 16, maxToolChars: 16000 } });
  for (let i = 1; i <= 12; i++) fs.writeFileSync(path.join(f.root, `report-${i}.txt`), 'Observed report text '.repeat(400));
  const task = await f.run('Read the twelve reports.');
  assert.equal(task.status, 'done', task.error);
  const data = f.checks[0];
  assert.ok(Buffer.byteLength(JSON.stringify(data)) < 32768, 'the compact check must fit below a 32k-class window');
  assert.ok(data.receiptsOmitted > 0); assert.ok(data.receipts.some(receipt => receipt.resultTruncated));
  assert.equal(data.request, 'Read the twelve reports.'); assert.equal(data.candidate, task.summary);
});

test('typed chat keeps normal text and does not run the voice result check', async t => {
  const f = await fixture(t, () => ({ content: 'Normal typed reply.' }));
  assert.equal(await f.parent.send('Hello'), 'Normal typed reply.');
  assert.equal(f.bodies.length, 1); assert.equal(f.checks.length, 0);
});

test('fresh workers inherit discovered built-in and MCP schemas as independent snapshots', async () => {
  const remoteSpec = { type: 'function', function: { name: 'mcp__calendar__list_events', description: 'List calendar events.', parameters: { type: 'object' } } };
  const mcp = { summaries: () => [{ id: 'calendar', tools: ['list_events'], deferred: true }],
    alwaysOnIds: () => [], has: id => id === 'calendar', specs: () => [remoteSpec] };
  const parent = new Agent({ client: {}, config: { tools: true, contextWindow: 131072 }, mcp, memoryEnabled: false, skillsEnabled: false, autoProject: false });
  parent.state.activatedTools.add('browser'); parent.state.activatedTools.add('mcp:calendar');
  parent.state.toolFocus = new Set(['read_file']);
  const context = captureVoiceContext(parent); parent.state.activatedTools.clear();
  let seen;
  class Probe extends Agent { async send() { seen = this.currentSpecs().map(spec => spec.function.name); return 'probe'; } }
  await runVoiceWorker({ id: 'probe', ownerId: parent.sessionId, transcript: 'Continue browsing.', context },
    { observer: {}, signal: new AbortController().signal, controlTool: { name: 'voice_jobs', parameters: { type: 'object' }, run: () => '[]' } }, { AgentClass: Probe });
  assert.ok(seen.includes('browser')); assert.ok(seen.includes('mcp__calendar__list_events')); assert.ok(seen.includes('find_tools'));
  assert.equal(parent.state.activatedTools.size, 0);
});
