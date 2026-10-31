import test from 'node:test';
import assert from 'node:assert/strict';
import { Agent, COMPACTION_SUMMARY_PREFIX } from '../../src/core/agent.mjs';

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
