import test from 'node:test';
import assert from 'node:assert/strict';

const { Agent, buildSystemPrompt } = await import('../src/agent.mjs');
const findTools = await import('../tools/find-tools.mjs');
const { CATEGORIES } = await import('../tools/catalog.mjs');

const config = { tools: true, autoApprove: true, historyMessages: 40, historyLines: 40, maxTokens: 1000 };
const makeAgent = (extra = {}) => new Agent({ client: {}, config: { ...config }, ...extra });
const call = (id, name, args = {}) => ({
  id,
  type: 'function',
  function: { name, arguments: JSON.stringify(args) },
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

/* ------------------------- capability discovery -------------------------- */

test('a capability you do not have routes to the mcp group', () => {
  // The gap this closes: asked to drive a browser with no browser server
  // connected, find_tools used to match nothing and the model shelled out.
  // Inclusion, not exclusivity - a browser request also legitimately matches
  // `web` ("browser" contains the web keyword "browse"), and loading both is
  // the right answer.
  for (const q of [
    'playwright',
    'open a browser',
    'drive a headless browser',
    'mcp marketplace',
    'install a tool from the registry',
    'add a database integration',
  ]) {
    assert.ok(findTools.matchCategories(q).includes('mcp'), `"${q}" must reach the mcp group`);
  }
  assert.deepEqual(findTools.matchCategories('playwright'), ['mcp'], 'and nothing spurious for this one');
});

test('unrelated queries still do not match everything', () => {
  assert.deepEqual(findTools.matchCategories('nothing relevant at all'), []);
  assert.deepEqual(findTools.matchCategories(''), []);
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
  assert.match(out, /Loaded mcp/);
});

/* --------------------------- the prompt rules ---------------------------- */

test('the prompt says a silent exit zero is not proof of success', () => {
  const prompt = buildSystemPrompt({}, process.cwd(), null, []);
  assert.match(prompt, /zero exit code is not proof/);
  assert.match(prompt, /unverified/, 'must say to report it as unverified');
  assert.match(prompt, /prefer a tool whose result you can read/i);
  // It has to be about evidence, not about which commands exist: "playwright
  // open" is a real command, so a rule against "inventing" it would be wrong.
  assert.doesNotMatch(prompt, /do not invent|never invent|made-up command/i);
});

test('the prompt routes an absent capability to the registry, with consent', () => {
  const prompt = buildSystemPrompt({}, process.cwd(), null, []);
  assert.match(prompt, /search the MCP registry/);
  assert.match(prompt, /ask the user\s+before installing/);
});
