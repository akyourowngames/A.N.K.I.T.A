import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { Agent } from '../../src/core/agent.mjs';
import { captureVoiceContext, runVoiceWorker } from '../../src/core/voice-worker.mjs';
import { VoiceSpeechQueue } from '../../src/automation/voice-speech-queue.mjs';
const api = await import('../../src/core/voice-report-control.mjs').catch(() => ({}));
const tick = () => new Promise(resolve => setImmediate(resolve));
const offer = (queue, id) => queue.offer({ jobId: id, kind: 'report', text: `${id} result.`, prepare: async () => id });
async function speech(t) {
  const heard = [], audio = new AbortController();
  const queue = new VoiceSpeechQueue({ gapMs: 0, play: async (bytes, { signal }) => {
    heard.push(bytes); if (bytes === 'poem') await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }));
  } });
  t.after(() => queue.close());
  void offer(queue, 'poem'); await tick(); void offer(queue, 'news');
  const turn = queue.interrupt(); queue.acceptTurn(turn); queue.resume();
  return { queue, heard, audio, turn };
}

test('private report control changes speech, and rejects unknown, cancelled and stale session operations', async t => {
  const h = await speech(t), control = api.createVoiceReportControl({ queue: h.queue, turn: h.turn, signal: h.audio.signal });
  assert.match(control.context, /poem/); assert.match(control.context, /news/);
  const status = JSON.parse(await control.tool.run({ action: 'status' }, {}));
  assert.ok(status.reports.some(item => item.id === 'poem' && item.state === 'suspended'));
  assert.equal(control.handled(), false);
  await assert.rejects(control.tool.run({ action: 'cancel' }, {}), /action|invalid/i);
  await control.tool.run({ action: 'next', answerRequired: false }, {}); await h.queue.drain();
  assert.equal(control.handled(), true); assert.deepEqual(h.heard, ['poem', 'news']);
  const current = h.queue.interrupt(); h.queue.acceptTurn(current);
  await assert.rejects(control.tool.run({ action: 'repeat', id: 'news' }, {}), /older|stale/i);
  h.audio.abort(); await assert.rejects(control.tool.run({ action: 'status' }, {}), /ended|cancelled/i);
});

test('resuming a fully delivered report does not claim to have scheduled audio', async () => {
  const queue = new VoiceSpeechQueue({ gapMs: 0, play: async () => {} });
  await offer(queue, 'done'); const turn = queue.interrupt(); queue.acceptTurn(turn); queue.resume();
  const control = api.createVoiceReportControl({ queue, turn, signal: new AbortController().signal });
  const result = JSON.parse(await control.tool.run({ action: 'resume', id: 'done' }, {}));
  assert.equal(result.available, false); assert.equal(control.handled(), false); await queue.close();
});

for (const mixed of [false, true]) test(`real voice planner receives speech context and private controls; mixed work still reports (mixed=${mixed})`, async t => {
  const h = await speech(t), root = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-report-worker-'));
  const requests = [];
  const server = http.createServer(async (request, response) => {
    let raw = ''; for await (const chunk of request) raw += chunk;
    const body = JSON.parse(raw); requests.push(body); const results = body.messages.filter(message => message.role === 'tool');
    const tool = (id, name, args) => ({ role: 'assistant', tool_calls: [{ id, type: 'function', function: { name, arguments: JSON.stringify(args) } }] });
    const message = !results.length ? tool('next', 'voice_reports', { action: 'next', answerRequired: false }) : mixed && results.length === 1
      ? tool('save', 'write_file', { path: 'new.txt', content: 'New work complete' }) : { content: mixed ? 'New work is saved.' : 'Selected the next result.' };
    response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify({ choices: [{ message, finish_reason: message.tool_calls ? 'tool_calls' : 'stop' }] }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); fs.rmSync(root, { recursive: true, force: true }); });
  const parent = new Agent({ client: { baseUrl: `http://127.0.0.1:${server.address().port}`, headers: () => ({}) },
    config: { tools: true, autoApprove: true, memoryConsolidation: false, contextWindow: 131072 }, workspacePath: root, memoryEnabled: false, skillsEnabled: false });
  const context = { ...captureVoiceContext(parent), speech: { queue: h.queue, turn: h.turn, signal: h.audio.signal } };
  const result = await runVoiceWorker({ id: 'new', ownerId: 'owner', transcript: mixed ? 'Move along and save another note' : 'Okay, then what?', context },
    { observer: {}, signal: new AbortController().signal, controlTool: { name: 'voice_jobs', parameters: { type: 'object' }, run: () => '[]' } });
  assert.ok(requests[0].tools.some(spec => spec.function.name === 'voice_reports'));
  assert.match(requests[0].messages[0].content, /poem/); assert.match(requests[0].messages[0].content, /news/);
  assert.equal(result.speechHandled, !mixed); assert.deepEqual(h.heard, ['poem', 'news']);
  if (mixed) assert.equal(fs.readFileSync(path.join(root, 'new.txt'), 'utf8'), 'New work complete');
  assert.ok(!parent.currentSpecs().some(spec => spec.function.name === 'voice_reports'));
});

test('the reserved voice control worker can select reports without gaining file tools', async t => {
  const h = await speech(t), root = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-report-capacity-')); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const parent = new Agent({ client: {}, config: { tools: true }, workspacePath: root, memoryEnabled: false, skillsEnabled: false });
  let offered;
  class Observe extends Agent { async send() { offered = this.currentSpecs().map(spec => spec.function.name); return 'Ready.'; } }
  await runVoiceWorker({ id: 'control', ownerId: 'owner', transcript: 'Next', controlOnly: true,
    context: { ...captureVoiceContext(parent), speech: { queue: h.queue, turn: h.turn, signal: h.audio.signal } } },
  { observer: {}, signal: new AbortController().signal, controlTool: { name: 'voice_jobs', parameters: { type: 'object' }, run: () => '[]' } }, { AgentClass: Observe });
  assert.deepEqual(offered.sort(), ['voice_jobs', 'voice_reports']);
});

test('cancelling a planner speech control during player shutdown cannot select the next report', async () => {
  let release, started;
  const stopped = new Promise(resolve => { release = resolve; }), began = new Promise(resolve => { started = resolve; });
  const heard = [], request = new AbortController(), audio = new AbortController();
  const queue = new VoiceSpeechQueue({ gapMs: 0, play: async bytes => {
    heard.push(bytes); if (bytes === 'poem') { started(); await stopped; }
  } });
  void offer(queue, 'poem'); await began; const news = offer(queue, 'news');
  const turn = queue.interrupt(); queue.acceptTurn(turn); queue.resume();
  const control = api.createVoiceReportControl({ queue, turn, signal: audio.signal });
  const selecting = control.tool.run({ action: 'next', answerRequired: false }, { signal: request.signal });
  const rejected = assert.rejects(selecting, { name: 'AbortError' });
  request.abort(); release(); await rejected; await tick();
  const after = [...heard], stillHeld = queue.gatedTurn;
  await queue.close(); await news;
  assert.deepEqual(after, ['poem']); assert.equal(stillHeld, turn); assert.equal(control.handled(), false);
});

for (const [name, args, speechOnly] of [['voice_jobs', { action: 'list' }, true], ['find_tools', { query: 'files' }, true],
  ['voice_jobs', { action: 'cancel', id: 'other' }, false]]) test(`speech selection after ${name} ${JSON.stringify(args)} keeps correct final speech`, async t => {
  const h = await speech(t), root = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-report-routing-'));
  const server = http.createServer(async (request, response) => {
    let raw = ''; for await (const chunk of request) raw += chunk;
    const body = JSON.parse(raw), count = body.messages.filter(message => message.role === 'tool').length;
    const message = count < 2 ? { role: 'assistant', tool_calls: [{ id: `route-${count}`, type: 'function',
      function: { name: count ? 'voice_reports' : name, arguments: JSON.stringify(count ? { action: 'next', answerRequired: false } : args) } }] }
      : { role: 'assistant', content: 'Selected the next result.' };
    response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify({ choices: [{ message, finish_reason: count < 2 ? 'tool_calls' : 'stop' }] }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); fs.rmSync(root, { recursive: true, force: true }); });
  const parent = new Agent({ client: { baseUrl: `http://127.0.0.1:${server.address().port}`, headers: () => ({}) },
    config: { tools: true, autoApprove: true, contextWindow: 131072 }, workspacePath: root, memoryEnabled: false, skillsEnabled: false });
  const result = await runVoiceWorker({ id: 'new', ownerId: 'owner', transcript: 'Next result',
    context: { ...captureVoiceContext(parent), speech: { queue: h.queue, turn: h.turn, signal: h.audio.signal } } },
    { observer: {}, signal: new AbortController().signal, controlTool: { name: 'voice_jobs', alwaysAvailable: true,
      parameters: { type: 'object', properties: { action: { type: 'string' }, id: { type: 'string' } } },
      readOnly: args => args.action === 'list', run: () => '[]' } });
  await h.queue.drain();
  assert.deepEqual(h.heard, ['poem', 'news']); assert.equal(result.speechHandled, speechOnly);
});

test('a successful speech dismissal can still owe a direct conversational answer', async t => {
  const h = await speech(t), root = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-report-conversation-'));
  const server = http.createServer(async (request, response) => {
    let raw = ''; for await (const chunk of request) raw += chunk;
    const body = JSON.parse(raw), done = body.messages.some(message => message.role === 'tool');
    const message = done ? { role: 'assistant', content: 'Two plus two is four.' } : { role: 'assistant', tool_calls: [{ id: 'dismiss', type: 'function',
      function: { name: 'voice_reports', arguments: JSON.stringify({ action: 'dismiss', answerRequired: true }) } }] };
    response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify({ choices: [{ message, finish_reason: done ? 'stop' : 'tool_calls' }] }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); fs.rmSync(root, { recursive: true, force: true }); });
  const parent = new Agent({ client: { baseUrl: `http://127.0.0.1:${server.address().port}`, headers: () => ({}) },
    config: { tools: true, autoApprove: true, contextWindow: 131072 }, workspacePath: root, memoryEnabled: false, skillsEnabled: false });
  const result = await runVoiceWorker({ id: 'new', ownerId: 'owner', transcript: 'Skip that report and tell me what two plus two is',
    context: { ...captureVoiceContext(parent), speech: { queue: h.queue, turn: h.turn, signal: h.audio.signal } } },
    { observer: {}, signal: new AbortController().signal, controlTool: { name: 'voice_jobs', parameters: { type: 'object' }, run: () => '[]' } });
  assert.equal(h.queue.reportState().find(row => row.id === 'poem').state, 'dismissed');
  assert.equal(result.text, 'Two plus two is four.'); assert.equal(result.speechHandled, false);
  await tick(); assert.deepEqual(h.heard, ['poem'], 'other reports wait for the answer still owed');
  const reply = h.queue.offer({ jobId: 'answer', kind: 'report', text: result.text, turn: h.turn, prepare: async () => 'answer' });
  h.queue.finishTurn(h.turn); await reply; await h.queue.drain();
  assert.deepEqual(h.heard, ['poem', 'answer', 'news']);
});

test('speech controls without an explicit whole-turn decision preserve the final answer', async t => {
  const h = await speech(t), control = api.createVoiceReportControl({ queue: h.queue, turn: h.turn, signal: h.audio.signal });
  await control.tool.run({ action: 'dismiss' }, {});
  assert.equal(control.handled(), false);
  await assert.rejects(control.tool.run({ action: 'resume', answerRequired: 'no' }, {}), /invalid/i);
});

test('cancelling explicit repeat during a newly active player shutdown cannot restart that report', async () => {
  let release, started, stopping;
  const stopped = new Promise(resolve => { release = resolve; }), began = new Promise(resolve => { started = resolve; });
  const stoppingPlayer = new Promise(resolve => { stopping = resolve; }), request = new AbortController(), heard = [];
  const queue = new VoiceSpeechQueue({ gapMs: 0, stop: () => stopping(), play: async bytes => { heard.push(bytes); started(); await stopped; } });
  void offer(queue, 'poem'); await began;
  const control = api.createVoiceReportControl({ queue, turn: queue.turn, signal: new AbortController().signal });
  const selecting = control.tool.run({ action: 'repeat', id: 'poem', answerRequired: false }, { signal: request.signal });
  const rejected = assert.rejects(selecting, { name: 'AbortError' });
  await stoppingPlayer; request.abort(); release(); await rejected; await queue.close();
  assert.deepEqual(heard, ['poem']); assert.equal(control.handled(), false);
});
