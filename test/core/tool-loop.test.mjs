import test from 'node:test';
import assert from 'node:assert/strict';

const { Agent, buildSystemPrompt } = await import('../../src/core/agent.mjs');
const findTools = await import('../../tools/find-tools.mjs');
const { CATEGORIES } = await import('../../tools/catalog.mjs');

const config = { tools: true, autoApprove: true, historyMessages: 40, historyLines: 40, maxTokens: 1000 };
const makeAgent = (extra = {}) => new Agent({ client: {}, config: { ...config }, ...extra });
const call = (id, name, args = {}) => ({
  id,
  type: 'function',
  function: { name, arguments: JSON.stringify(args) },
});

test('browser snapshots separated by successful interactions do not prematurely stop a workflow', async () => {
  const agent = makeAgent();
  let round = 0;
  agent.runToolCall = async c => JSON.parse(c.function.arguments).action === 'act' ? 'click complete.' : '[ref=1-0-0] button Next';
  agent.streamTurn = async () => {
    round++;
    if (round > 8) return { content: 'Workflow complete', toolCalls: [] };
    return { content: '', toolCalls: [call(`browser-${round}`, 'browser', round % 2 ? { action: 'snapshot' } : { action: 'act', op: 'click', ref: `${round}-0-0` })] };
  };
  const output = await agent.send('Complete this multi-step form');
  console.log(`browser workflow trace: rounds=${round}; result=${output}`);
  assert.equal(output, 'Workflow complete');
  assert.equal(round, 9);
});

test('an active checklist stays in the model context after its tool calls are trimmed', async () => {
  const agent = makeAgent();
  agent.state.todos = [
    { id: 's1', content: 'Review files', activeForm: 'Reviewing files', status: 'completed' },
    { id: 's2', content: 'Run tests', activeForm: 'Running tests', status: 'in_progress' },
  ];
  agent.streamTurn = async () => {
    const prompt = agent.messages[0].content;
    assert.match(prompt, /s1.*Review files.*completed/);
    assert.match(prompt, /s2.*Run tests.*in_progress/);
    assert.match(prompt, /write_todos.*completed/i);
    return { content: 'Tests passed', toolCalls: [] };
  };
  assert.equal(await agent.send('Finish the task'), 'Tests passed');
});

/* ---------------------- the tool execution loop ------------------------- */

/** Every tool_call the assistant declared must have exactly one tool reply. */
function assertPaired(agent, declaredIds) {
  const declared = new Set(declaredIds);
  const replies = agent.messages.filter((m) => m.role === 'tool');
  for (const id of declared) {
    const mine = replies.filter((r) => r.tool_call_id === id);
    assert.equal(mine.length, 1, `tool_call ${id} must have exactly one reply, got ${mine.length}`);
  }
  assert.equal(replies.length, declared.size, 'no replies for calls that were never declared');
}

test('a tool that throws still gets a reply, so the next request stays valid', async () => {
  // Without this the API rejects the whole next turn: "an assistant message
  // with tool_calls must be followed by tool messages responding to each
  // tool_call_id". One bad tool would end the session, not the step.
  const agent = makeAgent();
  let turn = 0;
  agent.runToolCall = async (c) => {
    if (c.function.name === 'explodes') throw new Error('kaboom');
    return 'fine';
  };
  agent.streamTurn = async () => {
    turn++;
    return turn === 1
      ? { content: '', toolCalls: [call('a', 'explodes'), call('b', 'explodes')] }
      : { content: 'recovered', toolCalls: [] };
  };

  assert.equal(await agent.send('go'), 'recovered');
  assertPaired(agent, ['a', 'b']);
  const reply = agent.messages.find((m) => m.role === 'tool' && m.tool_call_id === 'a');
  assert.match(reply.content, /kaboom/);
});

test('a throwing UI callback cannot break the protocol either', async () => {
  const agent = makeAgent();
  let turn = 0;
  agent.runToolCall = async () => 'ok';
  agent.streamTurn = async () => {
    turn++;
    return turn === 1 ? { content: '', toolCalls: [call('a', 'read_file')] } : { content: 'done', toolCalls: [] };
  };

  await agent.send('go', {
    onToolResult() { throw new Error('the renderer broke'); },
    onToolCall() { throw new Error('the renderer broke'); },
  });
  assertPaired(agent, ['a']);
});

test('cancelling mid-batch stops the work but still answers every call', async () => {
  const agent = makeAgent();
  const ran = [];
  let turn = 0;
  agent.runToolCall = async (c) => {
    ran.push(c.id);
    // The user hits escape while the first (mutating) tool runs.
    agent.abort.abort();
    return 'ran';
  };
  agent.streamTurn = async () => {
    turn++;
    return turn === 1
      ? { content: '', toolCalls: [call('a', 'write_file'), call('b', 'write_file'), call('c', 'write_file')] }
      : { content: 'never reached', toolCalls: [] };
  };

  assert.equal(await agent.send('go'), null, 'a cancelled turn returns null');
  assert.deepEqual(ran, ['a'], 'the remaining tools did not run');
  assertPaired(agent, ['a', 'b', 'c']);
  const skipped = agent.messages.find((m) => m.role === 'tool' && m.tool_call_id === 'b');
  assert.match(skipped.content, /cancel/i);
});

test('parallel read-only calls still get one reply each, in declaration order', async () => {
  const agent = makeAgent();
  let turn = 0;
  agent.runToolCall = async (c) => `out-${c.id}`;
  agent.streamTurn = async () => {
    turn++;
    return turn === 1
      ? { content: '', toolCalls: [call('a', 'read_file'), call('b', 'read_file'), call('c', 'read_file')] }
      : { content: 'done', toolCalls: [] };
  };
  await agent.send('go');
  assertPaired(agent, ['a', 'b', 'c']);
  const ids = agent.messages.filter((m) => m.role === 'tool').map((m) => m.tool_call_id);
  assert.deepEqual(ids, ['a', 'b', 'c']);
});

/* ---------------------- chat / tool model split ------------------------- */

test('once a turn uses a tool, the tool model runs the loop and writes the reply', async () => {
  const calls = [];
  const agent = makeAgent({ tool: { client: { tag: 'kilo' }, model: 'tool-model' } });
  agent.runToolCall = async () => 'file list';
  agent.streamTurn = async (opts = {}) => {
    calls.push({ tag: opts.client?.tag || 'chat', model: opts.model, useTools: opts.useTools });
    if (opts.client?.tag === 'kilo') {
      if (opts.useTools === false) {
        opts.onDelta?.('kilo reply');
        return { content: 'kilo reply', toolCalls: [], model: 'tool-model' };
      }
      return { content: 'tool draft', toolCalls: [], model: 'tool-model' };
    }
    return { content: '', toolCalls: [call('a', 'read_file')], model: 'chat-model' };
  };

  const deltas = [];
  const out = await agent.send('go', { onDelta: (d) => deltas.push(d) });

  assert.equal(out, 'kilo reply');
  assert.equal(agent.toolLoopUsed, true);
  assert.equal(agent.replyModel, 'tool-model');
  assert.equal(calls[0].tag, 'chat', 'the chat model makes the first tool decision');
  const kilo = calls.filter((c) => c.tag === 'kilo');
  assert.equal(kilo.length, 2, 'the tool model runs the loop then writes the reply');
  assert.notEqual(kilo[0].useTools, false, 'the loop step keeps tools');
  assert.equal(kilo[1].useTools, false, 'the reply step has no tools');
  assert.equal(agent.messages.at(-1).content, 'kilo reply');
  assert.ok(!agent.messages.some((m) => m.content === 'tool draft'), 'the tool draft is discarded');
  assert.ok(!deltas.includes('tool draft'), 'the intermediate tool text is not shown');
});

test('a turn with no tools is answered by the primary alone', async () => {
  const calls = [];
  const agent = makeAgent({ tool: { client: { tag: 'kilo' }, model: 'tool' } });
  agent.streamTurn = async (opts = {}) => {
    calls.push(opts.client?.tag || 'chat');
    return { content: 'hi', toolCalls: [] };
  };
  const out = await agent.send('hi');
  assert.equal(out, 'hi');
  assert.deepEqual(calls, ['chat'], 'the tool model is never woken for plain chat');
  assert.equal(agent.toolLoopUsed, false);
});

test('a failed reply falls back to the tool model draft instead of losing the turn', async () => {
  const agent = makeAgent({ tool: { client: { tag: 'kilo' }, model: 'tool' } });
  agent.runToolCall = async () => 'ok';
  agent.streamTurn = async (opts = {}) => {
    if (opts.client?.tag === 'kilo') {
      if (opts.useTools === false) throw new Error('reply model down');
      return { content: 'tool draft', toolCalls: [] };
    }
    return { content: '', toolCalls: [call('a', 'read_file')] };
  };
  const out = await agent.send('go');
  assert.equal(out, 'tool draft');
  assert.equal(agent.messages.at(-1).content, 'tool draft');
  assert.equal(agent.toolLoopUsed, true);
});

test('a rate-limited chat model falls back to the tool model instead of waiting out the backoff', async () => {
  const calls = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, opts) => {
    const model = JSON.parse(opts.body).model;
    calls.push(model);
    if (model === 'chat') return new Response('rate limited', { status: 429, headers: { 'retry-after': '30' } });
    return new Response(JSON.stringify({ choices: [{ message: { content: 'from tool model' } }] }),
      { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    const agent = new Agent({
      client: { baseUrl: 'http://chat', headers: () => ({}) },
      config: { tools: false, autoApprove: true, model: 'chat', historyMessages: 40, historyLines: 40, maxTokens: 1000 },
      tool: { client: { baseUrl: 'http://tool', headers: () => ({}) }, model: 'tool' },
      print: () => {},
    });
    const start = performance.now();
    const out = await agent.send('hi');
    assert.equal(out, 'from tool model');
    assert.deepEqual(calls, ['chat', 'tool'], 'the chat model was tried once, then the tool model');
    assert.ok(performance.now() - start < 1000, 'it did not sit out the 30s Retry-After');
  } finally {
    globalThis.fetch = realFetch;
  }
});

test('a too-large request (413) also falls back instead of ending the turn', async () => {
  const calls = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, opts) => {
    const model = JSON.parse(opts.body).model;
    calls.push(model);
    if (model === 'chat') {
      return new Response(JSON.stringify({ error: { message: 'Request too large for model', code: 'rate_limit_exceeded' } }),
        { status: 413, headers: { 'content-type': 'application/json' } });
    }
    return new Response(JSON.stringify({ choices: [{ message: { content: 'kilo answered' } }] }),
      { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    const agent = new Agent({
      client: { baseUrl: 'http://chat', headers: () => ({}) },
      config: { tools: false, autoApprove: true, model: 'chat', historyMessages: 40, historyLines: 40, maxTokens: 1000 },
      tool: { client: { baseUrl: 'http://tool', headers: () => ({}) }, model: 'tool' },
      print: () => {},
    });
    const out = await agent.send('continue');
    assert.equal(out, 'kilo answered');
    assert.deepEqual(calls, ['chat', 'tool']);
    assert.equal(agent.replyModel, 'tool', 'the status line reports who actually replied');
  } finally {
    globalThis.fetch = realFetch;
  }
});

/* ------------------------- capability discovery -------------------------- */

test('browser requests load the first-party tool; other missing capabilities reach MCP', () => {
  for (const q of ['playwright', 'open a browser', 'drive a headless browser']) {
    assert.ok(findTools.matchCategories(q).includes('browser'), `"${q}" must reach the browser group`);
  }
  for (const q of ['mcp marketplace', 'install a tool from the registry', 'add a database integration']) {
    assert.ok(findTools.matchCategories(q).includes('mcp'), `"${q}" must reach the mcp group`);
  }
  assert.deepEqual(findTools.matchCategories('playwright'), ['browser']);
});

test('unrelated queries still do not match everything', () => {
  assert.deepEqual(findTools.matchCategories('nothing relevant at all'), []);
  assert.deepEqual(findTools.matchCategories(''), []);
});

test('booking and playback intent reaches the browser instead of dead-ending', () => {
  for (const q of ['book a flight from Mumbai to Delhi', 'book flight tickets', 'play some music', 'play a song on youtube']) {
    assert.ok(findTools.matchCategories(q).includes('browser'), `"${q}" must reach the browser group`);
  }
  // Whole-word matching only: display/settings/sing-along must not route to browser.
  for (const q of ['change the display settings', 'sing along']) {
    assert.ok(!findTools.matchCategories(q).includes('browser'), `"${q}" must not reach the browser group`);
  }
});

test('every mcp keyword is lowercase, since matching lowercases the query', () => {
  const mcp = CATEGORIES.find((c) => c.id === 'mcp');
  for (const k of mcp.keywords) assert.equal(k, k.toLowerCase(), `"${k}" would never match`);
});

test('a find_tools miss points at the registry instead of dead-ending', async () => {
  const out = findTools.run({ query: 'quuxbar' }, {});
  assert.match(out, /Nothing matched/);
  assert.match(out, /mcp`? group/, 'names the group to load');
  assert.match(out, /action="search"/, 'and the exact call to make');
  assert.match(out, /[Aa]sk the user before installing/, 'installing still needs consent');
});

test('a hit does not mention the registry - only a miss does', async () => {
  const out = findTools.run({ query: 'playwright' }, {});
  assert.doesNotMatch(out, /Nothing matched/);
  assert.match(out, /Loaded browser/);
});

/* --------------------------- the prompt rules ---------------------------- */

test('the prompt says a silent exit zero is not proof of success', () => {
  const prompt = buildSystemPrompt({}, process.cwd(), null, []);
  assert.match(prompt, /zero exit code is not proof/);
  assert.match(prompt, /unverified/, 'must say to report it as unverified');
  assert.match(prompt, /prefer a tool whose result you can read/i);
  // It has to be about evidence, not about which commands exist: "playwright
  // open" is a real command, so a rule against "inventing" it would be wrong.
  assert.doesNotMatch(prompt, /(?:do not invent|never invent) (?:commands|shell)|made-up command/i);
  assert.match(prompt, /opaque \[ref=\.\.\.\] IDs verbatim/);
  assert.match(prompt, /fresh snapshot in the error/);
  assert.doesNotMatch(prompt, /Re-snapshot before every action/);
});

test('the prompt routes an absent capability to the registry, with consent', () => {
  const prompt = buildSystemPrompt({}, process.cwd(), null, []);
  assert.match(prompt, /search the MCP registry/);
  assert.match(prompt, /ask the user\s+before installing/);
});
