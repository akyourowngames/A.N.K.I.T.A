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
  await control.tool.run({ action: 'next' }, {}); await h.queue.drain();
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
    const message = !results.length ? tool('next', 'voice_reports', { action: 'next' }) : mixed && results.length === 1
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
