import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { Agent, COMPACTION_SUMMARY_PREFIX } from '../../src/core/agent.mjs';
import { conversationCost, trimMessages } from '../../src/core/history.mjs';
import { SUBAGENT_INBOX_PREFIX } from '../../src/core/subagents/registry.mjs';

const config = { tools: false, historyMessages: 40, historyLines: 40, maxTokens: 1000, contextWindow: 128000 };

/** An agent with a client shape summarizeMessages() accepts. */
function makeAgent({ compaction, summarize } = {}) {
  const agent = new Agent({
    client: { baseUrl: 'https://provider.example/v1', requestDefaults: { model: 'alpha' }, headers: () => ({}) },
    config: { ...config, contextCompaction: compaction },
  });
  if (summarize) agent.summarizeMessages = summarize;
  return agent;
}

/** A realistic long history: alternating user/assistant turns with tool pairs. */
function fill(agent, turns) {
  for (let i = 0; i < turns; i++) {
    agent.messages.push({ role: 'user', content: `request ${i}` });
    agent.messages.push({
      role: 'assistant', content: null,
      tool_calls: [{ id: `call-${i}`, type: 'function', function: { name: 'read_file', arguments: '{}' } }],
    });
    agent.messages.push({ role: 'tool', tool_call_id: `call-${i}`, content: `result ${i}` });
    agent.messages.push({ role: 'assistant', content: `answer ${i}` });
  }
}

test('compaction is off by default and never costs a model call', async () => {
  const agent = makeAgent({ compaction: undefined, summarize: async () => { throw new Error('must not be called'); } });
  fill(agent, 30);
  await agent.trimHistory(40);
  assert.equal(agent.messages.some(message => String(message.content).startsWith(COMPACTION_SUMMARY_PREFIX)), false);
  assert.ok(agent.messages.length <= 41, 'disabled compaction keeps the plain message budget');
});

test('compaction folds older turns into one recap and keeps the most recent window', async () => {
  let seen = '';
  const agent = makeAgent({
    compaction: true,
    summarize: async messages => { seen = messages.map(message => message.content).join('\n'); return 'Recap: built the login form and ran tests.'; },
  });
  fill(agent, 20); // 1 system + 80 turns = long enough to compact.
  const recentBefore = agent.messages.slice(-10).map(message => JSON.stringify(message));
  await agent.trimHistory(40);

  const summaryIndex = agent.messages.findIndex(message => String(message.content).startsWith(COMPACTION_SUMMARY_PREFIX));
  assert.ok(summaryIndex >= 0, 'the recap is present');
  assert.match(agent.messages[summaryIndex].content, /built the login form/);
  assert.equal(agent.messages[0].role, 'system', 'the system prompt stays first');
  assert.equal(summaryIndex, 1, 'the recap sits directly after the system prompt');
  assert.equal(agent.messages[summaryIndex].role, 'user', 'providers that require a leading user turn still accept the history');
  assert.notEqual(agent.messages[summaryIndex + 1]?.role, 'tool', 'the recap never strands a tool reply');
  assert.deepEqual(agent.messages.slice(-10).map(message => JSON.stringify(message)), recentBefore, 'the newest turns are untouched');
  assert.match(seen, /request 0/, 'the model received the old transcript, not just the recent window');
  assert.ok(agent.messages.length < 82, `history shrank from 81 to ${agent.messages.length}`);
  for (const message of agent.messages.filter(item => item.role === 'tool')) {
    assert.ok(agent.messages.some(item => item.tool_calls?.some(call => call.id === message.tool_call_id)),
      'no orphan tool reply survives compaction');
  }
});

test('a failing recap falls back to plain trimming instead of losing the turn', async () => {
  const agent = makeAgent({ compaction: true, summarize: async () => { throw new Error('provider down'); } });
  fill(agent, 20);
  const logs = [];
  agent.print = message => logs.push(message);
  await agent.trimHistory(8);
  assert.ok(agent.messages.length <= 9, 'the old trim budget still applies');
  assert.equal(agent.messages.some(message => String(message.content).startsWith(COMPACTION_SUMMARY_PREFIX)), false);
  assert.ok(logs.some(message => /context compaction skipped/.test(message)), 'the skip is reported, not silent');
});

test('an empty recap result also falls back without rewriting history', async () => {
  const agent = makeAgent({ compaction: true, summarize: async () => null });
  fill(agent, 20);
  await agent.trimHistory(40);
  assert.equal(agent.messages.some(message => String(message.content).startsWith(COMPACTION_SUMMARY_PREFIX)), false);
  assert.ok(agent.messages.length <= 81);
});

test('short conversations are never compacted', async () => {
  let calls = 0;
  const agent = makeAgent({ compaction: true, summarize: async () => { calls++; return 'unused'; } });
  fill(agent, 2); // 1 system + 8 messages.
  await agent.trimHistory(40);
  assert.equal(calls, 0, 'a short chat stays exactly as it was');
  assert.equal(agent.messages.length, 9);
});

test('summarizeMessages sends a bounded transcript and reads the reply text', async () => {
  const agent = makeAgent({ compaction: true });
  const originalFetch = globalThis.fetch;
  let request;
  try {
    globalThis.fetch = async (url, options) => {
      request = { url, body: JSON.parse(options.body) };
      return { ok: true, status: 200, json: async () => ({ choices: [{ message: { content: '  short recap  ' } }] }) };
    };
    const recap = await agent.summarizeMessages([
      { role: 'user', content: 'goal: ship the settings panel' },
      { role: 'assistant', content: null, tool_calls: [{ type: 'function', function: { name: 'write_file', arguments: '{}' } }] },
      { role: 'tool', tool_call_id: '1', content: 'wrote SettingsDialog.tsx' },
    ]);
    assert.equal(recap, 'short recap', 'the reply is trimmed');
    assert.equal(request.url, 'https://provider.example/v1/chat/completions');
    assert.equal(request.body.stream, false, 'summaries are one-shot requests');
    assert.equal(request.body.max_tokens, 400, 'the recap has a bounded output');
    const prompt = request.body.messages[0].content;
    assert.match(prompt, /ship the settings panel/, 'the user goal reaches the summarizer');
    assert.match(prompt, /write_file/, 'tool names are retained');
    assert.match(prompt, /SettingsDialog\.tsx/, 'tool results are retained');
    assert.match(prompt, /Do not invent facts/i, 'the summarizer is told not to fabricate');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('a failed summarize request surfaces as an error the caller can fall back from', async () => {
  const agent = makeAgent({ compaction: true });
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => ({ ok: false, status: 500, headers: { get: () => null } });
    await assert.rejects(() => agent.summarizeMessages([{ role: 'user', content: 'x' }]), /compaction request failed \(500\)/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('compaction does not run twice in a row without new turns', async () => {
  let calls = 0;
  const agent = makeAgent({ compaction: true, summarize: async () => { calls++; return 'recap'; } });
  fill(agent, 20);
  await agent.trimHistory(40);
  assert.equal(calls, 1);
  await agent.trimHistory(40);
  assert.equal(calls, 1, 'the cooldown stops a second recap for the same history');
  agent.messages.push({ role: 'user', content: 'new request after the recap' });
  for (let i = 0; i < 30; i++) agent.messages.push({ role: 'assistant', content: `later ${i}` });
  await agent.trimHistory(40);
  assert.equal(calls, 2, 'new work eventually earns another recap');
});

test('byte pressure compacts a short chat before trimming away its goal', async () => {
  let seen;
  const agent = makeAgent({ compaction: true, summarize: async messages => {
    seen = messages;
    return 'Keep the original goal and decisions.';
  } });
  agent.contextWindow = 12000;
  agent.messages = [{ role: 'system', content: 'system' },
    { role: 'user', content: 'Original goal. ' + 'x'.repeat(7000) },
    { role: 'assistant', content: 'Decision. ' + 'y'.repeat(7000) },
    { role: 'user', content: 'Continue with the current task.' }];
  await agent.trimHistory(40);
  assert.ok(seen?.some(message => message.content.includes('Original goal')));
  assert.ok(agent.messages.some(message => message.content.startsWith(COMPACTION_SUMMARY_PREFIX)));
  assert.equal(agent.messages.at(-1).content, 'Continue with the current task.');
});

test('compaction keeps the current user task intact through a long tool loop', async () => {
  const agent = makeAgent({ compaction: true, summarize: async () => 'Earlier tool progress.' });
  agent.messages.push({ role: 'user', content: 'CURRENT TASK must stay complete' });
  for (let i = 0; i < 40; i++) agent.messages.push({ role: 'assistant', content: `progress ${i}` });
  await agent.trimHistory(40);
  assert.ok(agent.messages.some(message => message.content === 'CURRENT TASK must stay complete'));
});

test('new byte pressure overrides the message-count cooldown', async () => {
  let calls = 0;
  const agent = makeAgent({ compaction: true, summarize: async () => { calls++; return 'Recap of prior work.'; } });
  agent.messages[0] = { role: 'system', content: 'system' };
  fill(agent, 20);
  await agent.trimHistory(40);
  agent.contextWindow = 12000;
  agent.messages.push({ role: 'assistant', content: 'A new large result ' + 'x'.repeat(14000) });
  agent.messages.push({ role: 'user', content: 'Continue.' });
  await agent.trimHistory(40);
  assert.equal(calls, 2);
});

test('a successful recap reports completion immediately and observer errors are isolated', async () => {
  const events = [];
  const agent = makeAgent({ compaction: true, summarize: async () => 'Visible recap.' });
  agent.onCompaction = event => { events.push(event); throw new Error('renderer unavailable'); };
  fill(agent, 20);
  await agent.trimHistory(40);
  assert.equal(events.at(-1)?.phase, 'completed');
  assert.equal(events.at(-1)?.summary, 'Visible recap.');
  assert.ok(events.at(-1).beforeMessages > events.at(-1).afterMessages);
});

test('a recap cancelled during generation leaves the original history intact', async () => {
  const agent = makeAgent({ compaction: true, summarize: async () => {
    agent.abort.abort();
    return 'Cancelled recap must not replace history';
  } });
  agent.abort = new AbortController();
  fill(agent, 20);
  const before = structuredClone(agent.messages);
  await assert.rejects(() => agent.trimHistory(40), { name: 'AbortError' });
  assert.deepEqual(agent.messages, before);
});

test('a configured short history compacts before count trimming starts', async () => {
  let calls = 0;
  const agent = makeAgent({ compaction: true, summarize: async () => { calls++; return 'Goal retained.'; } });
  fill(agent, 2);
  agent.messages.push({ role: 'user', content: 'latest task' });
  await agent.trimHistory(8);
  assert.equal(calls, 1);
  assert.ok(agent.messages.some(message => message.content.startsWith(COMPACTION_SUMMARY_PREFIX)));
});

test('normal send compacts through HTTP using the active model window and emits completion', async t => {
  const requests = [];
  const server = http.createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks));
    requests.push(body);
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ choices: [{ finish_reason: 'stop', message: {
      content: body.stream ? 'Continuing the original goal.' : 'Original goal preserved, decisions retained.',
    } }] }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); return new Promise(resolve => server.close(resolve)); });
  const limit = 20000;
  const events = [];
  const client = { baseUrl: `http://127.0.0.1:${server.address().port}`, headers: () => ({}),
    modelCapabilities: new Map([['small', { context: limit }]]) };
  const agent = new Agent({ client, config: { ...config, model: 'small', contextCompaction: true },
    print: () => {}, write: () => {}, onCompaction: event => events.push(event), memoryEnabled: false, autoProject: false });
  agent.messages.push({ role: 'user', content: 'Original goal ' + 'क'.repeat(3000) },
    { role: 'assistant', content: 'Decisions ' + 'क'.repeat(3000) });
  const result = await agent.send('Continue the current task.');
  assert.equal(result, 'Continuing the original goal.');
  assert.ok(requests.some(request => request.stream === false));
  for (const request of requests) {
    assert.equal(request.model, 'small');
    assert.ok(conversationCost(request.messages) + (request.max_tokens || agent.outputReserve()) + 1024 <= limit,
      'both the recap request and the actual response fit the advertised model');
  }
  assert.ok(events.some(event => event.phase === 'completed'));
  assert.ok(agent.messages.some(message => message.content.startsWith(COMPACTION_SUMMARY_PREFIX)));
  console.log('COMPACTION_HTTP_ROUNDTRIP_OK', JSON.stringify({ requests: requests.length, context: limit, phases: events.map(event => event.phase) }));
});

test('subagent inbox updates never replace the current task anchor during compaction', async () => {
  const agent = makeAgent({ compaction: true, summarize: async () => 'Child progress retained.' });
  agent.messages.push({ role: 'user', content: 'Finish the real user task.' });
  for (let i = 0; i < 40; i++) agent.messages.push({ role: 'assistant', content: `progress ${i}` });
  agent.messages.push({ role: 'user', content: `${SUBAGENT_INBOX_PREFIX}\nChild update` });
  await agent.trimHistory(40);
  assert.ok(agent.messages.some(message => message.content === 'Finish the real user task.'));
});

test('normal send leaves room for the provider output default on the actual HTTP request', async t => {
  const requests = [];
  const server = http.createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    requests.push(JSON.parse(Buffer.concat(chunks)));
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ choices: [{ finish_reason: 'stop', message: { content: 'Ready.' } }] }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); return new Promise(resolve => server.close(resolve)); });
  // Bytes in this fixture exercise a provider whose reply cap exceeds the app default.
  const limit = 32768;
  const outputTokens = 12000;
  const oldTurnBytes = 9000;
  const requestOverheadBytes = 1024;
  const client = { baseUrl: `http://127.0.0.1:${server.address().port}`, headers: () => ({}),
    requestDefaults: { max_tokens: outputTokens } };
  const agent = new Agent({ client, config: { ...config, contextWindow: limit },
    print: () => {}, write: () => {}, memoryEnabled: false, autoProject: false });
  agent.messages.push({ role: 'user', content: 'Earlier request ' + 'x'.repeat(oldTurnBytes) },
    { role: 'assistant', content: 'Earlier reply ' + 'y'.repeat(oldTurnBytes) });
  assert.equal(await agent.send('Continue.'), 'Ready.');
  assert.equal(requests.length, 1);
  assert.equal(requests[0].max_tokens, outputTokens);
  assert.ok(conversationCost(requests[0].messages) + outputTokens + requestOverheadBytes <= limit,
    'the history and the output cap sent to the provider fit the same window');
  console.log('PROVIDER_OUTPUT_BUDGET_HTTP_OK', JSON.stringify({ context: limit,
    output: outputTokens, history: conversationCost(requests[0].messages) }));
});

test('plain trimming anchors the real task across multiple subagent inbox updates', () => {
  const messages = [{ role: 'system', content: 'system' }, { role: 'user', content: 'Real task' }];
  for (let i = 0; i < 20; i++) {
    messages.push({ role: 'assistant', content: `progress ${i}` },
      { role: 'user', content: `${SUBAGENT_INBOX_PREFIX}\nupdate ${i}` });
  }
  assert.ok(trimMessages(messages, 8).some(message => message.content === 'Real task'));
});

test('repeated compaction carries the complete bounded prior recap into the next summary', async () => {
  const agent = makeAgent({ compaction: true });
  const originalFetch = globalThis.fetch;
  let prompt;
  try {
    globalThis.fetch = async (_url, options) => {
      prompt = JSON.parse(options.body).messages[0].content;
      return { ok: true, json: async () => ({ choices: [{ message: { content: 'Updated recap' } }] }) };
    };
    await agent.summarizeMessages([{ role: 'user', content: `${COMPACTION_SUMMARY_PREFIX}\n${'x'.repeat(1100)}\nKeep the final unresolved constraint.` }]);
    assert.match(prompt, /Keep the final unresolved constraint\./);
  } finally { globalThis.fetch = originalFetch; }
});
