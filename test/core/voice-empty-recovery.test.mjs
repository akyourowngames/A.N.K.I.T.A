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

async function fixture(t, transport, reply) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-empty-'));
  const writes = [], bodies = [];
  const server = http.createServer(async (request, response) => {
    let raw = ''; for await (const chunk of request) raw += chunk;
    const body = JSON.parse(raw);
    if (isVoiceCheck(body)) { response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify({ choices: [{ message: checkMessage() }] })); return; }
    bodies.push(body);
    const message = await reply(body);
    if (transport === 'JSON') {
      response.setHeader('Content-Type', 'application/json');
      response.end(JSON.stringify({ choices: [{ message, finish_reason: message.tool_calls?.length ? 'tool_calls' : 'stop' }] }));
    } else {
      response.setHeader('Content-Type', 'text/event-stream');
      response.end(`data: ${JSON.stringify({ choices: [{ delta: { ...message,
        tool_calls: message.tool_calls?.map((call, index) => ({ ...call, index })) }, finish_reason: message.tool_calls?.length ? 'tool_calls' : 'stop' }] })}\n\ndata: [DONE]\n\n`);
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); fs.rmSync(root, { recursive: true, force: true }); });
  const client = { baseUrl: `http://127.0.0.1:${server.address().port}`, headers: () => ({}) };
  const parent = new Agent({ client, config: { tools: true, autoApprove: true, memoryConsolidation: false },
    memoryEnabled: false, skillsEnabled: false, workspacePath: root });
  const jobs = new VoiceJobs({ store: new VoiceTaskStore({ directory: path.join(root, 'tasks') }),
    run: (entry, options) => runVoiceWorker(entry, options, { acquire: (...args) => jobs.acquire(...args),
      toolContext: { onToolStart: call => { if (call.name === 'write_file') writes.push(call.arguments.path); } } }),
  });
  t.after(() => jobs.close());
  return { root, writes, bodies, parent, jobs,
    submit: transcript => jobs.submit({ ownerId: parent.sessionId, transcript, context: captureVoiceContext(parent) }) };
}
const write = (id, name, content) => ({ role: 'assistant', content: '', tool_calls: [{ id, type: 'function',
  function: { name: 'write_file', arguments: JSON.stringify({ path: name, content }) } }] });
const toolResults = body => body.messages.filter(message => message.role === 'tool');

// Break caught: restarting Agent.send after an empty intermediate decision disables tools,
// so a second job reports its draft while silently skipping the rest of the user's work.
for (const transport of ['JSON', 'SSE']) test(`${transport}: second concurrent voice job recovers an empty intermediate decision and finishes remaining files once`, async t => {
  let empty = false;
  const f = await fixture(t, transport, async body => {
    const user = body.messages.findLast(message => message.role === 'user')?.content;
    if (user === 'First poem') return toolResults(body).length ? { content: 'Poem saved.' } : write('poem', 'poem.txt', 'Poem');
    const results = toolResults(body);
    if (!results.length) return write('draft', 'draft.md', 'Research draft');
    if (!empty) { empty = true; return { content: '', reasoning_content: 'Need to save the finished findings.' }; }
    if (!body.tools?.length) return { content: 'Only the research draft was saved; the final file is unfinished.' };
    return results.length === 1 ? write('final', 'findings.md', 'Verified findings') : { content: 'Findings saved.' };
  });
  const first = await f.submit('First poem'), second = await f.submit('Research and save the draft and final findings');
  const [a, b] = await Promise.all([first, second].map(job => f.jobs.waitFor(job.id, { ownerId: f.parent.sessionId })));
  assert.equal(a.task.status, 'done'); assert.equal(b.task.status, 'done', b.task.error);
  assert.equal(fs.existsSync(path.join(f.root, 'findings.md')), true, 'an empty model decision must not strand the unfinished save');
  assert.equal(fs.readFileSync(path.join(f.root, 'findings.md'), 'utf8'), 'Verified findings');
  assert.equal(f.writes.filter(name => name === 'draft.md').length, 1, 'completed writes must not replay');
  assert.equal(f.writes.filter(name => name === 'findings.md').length, 1);
  assert.equal(f.bodies.some(body => body.messages.at(-1)?.role === 'assistant' && !body.messages.at(-1)?.content), false,
    'do not append an empty assistant turn before retrying the unexecuted decision');
});

test('two empty voice decisions fail with a provider-specific error and one retry, without any file action', async t => {
  const f = await fixture(t, 'SSE', () => ({ content: '', reasoning_content: 'Thinking' }));
  const request = await f.submit('Save findings');
  const result = await f.jobs.waitFor(request.id, { ownerId: f.parent.sessionId });
  assert.equal(result.task.status, 'failed');
  assert.match(result.task.error, /provider.*no answer or action/i);
  assert.equal(f.bodies.length, 2); assert.equal(f.writes.length, 0);
  assert.ok(f.bodies.every(body => body.tools?.length && body.messages.at(-1).role === 'user'));
});

test('ordinary typed requests do not gain the voice-only empty-decision retry', async t => {
  const f = await fixture(t, 'JSON', () => ({ content: '' }));
  assert.equal(await f.parent.send('Hello'), '');
  assert.equal(f.bodies.length, 1);
});
