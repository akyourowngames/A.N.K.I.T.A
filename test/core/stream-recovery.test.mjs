import test from 'node:test';
import assert from 'node:assert/strict';
import { Agent } from '../../src/core/agent.mjs';

const sse = chunks => new Response(chunks.map(chunk => `data: ${typeof chunk === 'string' ? chunk : JSON.stringify(chunk)}\n\n`).join(''), { headers: { 'content-type': 'text/event-stream' } });
const delta = content => ({ choices: [{ delta: { content } }] });
function mockFetch(t, replies) {
  const original = globalThis.fetch; let calls = 0;
  globalThis.fetch = async () => { calls++; return replies.shift(); };
  t.after(() => { globalThis.fetch = original; });
  return () => calls;
}
const makeAgent = () => new Agent({ client: { baseUrl: 'https://test.invalid', headers: () => ({}) }, config: { tools: false, historyMessages: 40, historyLines: 40, maxTokens: 1000, memoryConsolidation: false } });

test('a truncated model stream retries the same model step without duplicated visible text', async t => {
  const calls = mockFetch(t, [sse([delta('I have opened')]), sse([delta('I have opened the page.'), '[DONE]'])]);
  const agent = makeAgent(); let visible = '';
  assert.equal(await agent.send('Open the page', { onDelta: d => { visible += d; } }), 'I have opened the page.');
  assert.equal(visible, 'I have opened the page.'); assert.equal(calls(), 2);
});

test('EOF in the middle of a JSON frame retries without consuming its partial tool or text', async t => {
  const broken = new Response(`data: ${JSON.stringify(delta('Opened'))}\n\ndata: {"choices":[{"delta":{"content":" the pa`, { headers: { 'content-type': 'text/event-stream' } });
  const calls = mockFetch(t, [broken, sse([delta('Opened the page.'), '[DONE]'])]);
  const agent = makeAgent(); let visible = '';
  assert.equal(await agent.send('Go', { onDelta: d => { visible += d; } }), 'Opened the page.');
  assert.equal(visible, 'Opened the page.'); assert.equal(calls(), 2);
});

test('a network failure during response body streaming recovers the same step', async t => {
  let pulls = 0;
  const broken = new Response(new ReadableStream({ pull(controller) {
    if (++pulls === 1) controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(delta('Opened'))}\n\n`));
    else controller.error(new Error('Connection reset'));
  } }), { headers: { 'content-type': 'text/event-stream' } });
  const calls = mockFetch(t, [broken, sse([delta('Opened the page.'), '[DONE]'])]);
  assert.equal(await makeAgent().send('Go'), 'Opened the page.'); assert.equal(calls(), 2);
});

test('a truncated tool request never executes until its replacement stream is complete', async t => {
  const tc = { choices: [{ delta: { tool_calls: [{ index: 0, id: 'a', function: { name: 'browser', arguments: '{"action":"open"}' } }] } }] };
  const calls = mockFetch(t, [sse([tc]), sse([tc, '[DONE]']), sse([delta('Finished.'), '[DONE]'])]);
  const agent = makeAgent(); let executions = 0;
  agent.runToolCall = async () => { executions++; return 'Opened'; };
  assert.equal(await agent.send('Go'), 'Finished.'); assert.equal(executions, 1); assert.equal(calls(), 3);
});

test('recovery is bounded when the provider repeatedly cuts off', async t => {
  const calls = mockFetch(t, [sse([delta('partial')]), sse([delta('partial')]), sse([delta('partial')])]);
  await assert.rejects(makeAgent().send('Go'), /cut off/);
  assert.equal(calls(), 3);
});

test('recovery after a completed browser step retains its receipt and does not repeat the step', async t => {
  const tc = { choices: [{ delta: { tool_calls: [{ index: 0, id: 'open', function: { name: 'browser', arguments: '{"action":"open"}' } }] } }] };
  mockFetch(t, [sse([tc, '[DONE]']), sse([delta('The page')]), sse([delta('The page is open.'), '[DONE]'])]);
  const agent = makeAgent(); let executions = 0;
  agent.runToolCall = async () => { executions++; return 'Opened tab 1: example.com'; };
  assert.equal(await agent.send('Go'), 'The page is open.'); assert.equal(executions, 1);
  assert.ok(agent.messages.some(message => message.role === 'tool' && message.content.includes('Opened tab 1')));
});

test('a replacement response with different wording resets the unfinished message', async t => {
  mockFetch(t, [sse([delta('Old answer')]), sse([delta('Recovered answer.'), '[DONE]'])]);
  const agent = makeAgent(); let visible = '', resets = 0;
  await agent.send('Go', { onDelta: d => { visible += d; }, onMessageReset: () => { visible = ''; resets++; } });
  assert.equal(visible, 'Recovered answer.'); assert.equal(resets, 1);
  assert.equal(agent.messages.at(-1).content, 'Recovered answer.');
});

test('Stop during a broken response never triggers a recovery request', async t => {
  const original = globalThis.fetch; t.after(() => { globalThis.fetch = original; });
  const agent = makeAgent(); let calls = 0;
  globalThis.fetch = async () => {
    calls++; return new Response(new ReadableStream({ pull(controller) { agent.cancel(); controller.error(new Error('Connection closed')); } }), { headers: { 'content-type': 'text/event-stream' } });
  };
  await assert.rejects(agent.send('Go'), /closed/); assert.equal(calls, 1);
});
