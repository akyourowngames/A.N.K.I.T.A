import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// Sandbox the config directory before anything imports src/core/config.mjs, so the
// config assertions here never read (or write) the real ~/.copilot-chat-cli.
const SANDBOX = fs.mkdtempSync(path.join(os.tmpdir(), 'tool-budget-'));
process.env.CONFIG_DIR = SANDBOX;
test.after(() => {
  fs.rmSync(SANDBOX, { recursive: true, force: true });
  delete process.env.MAX_TOOL_STEPS;
});

const { Agent, MAX_TOOL_STEPS, MAX_REPEAT_CALLS, buildSystemPrompt } = await import('../../src/core/agent.mjs');
const { loadConfig } = await import('../../src/core/config.mjs');

const baseConfig = { tools: true, autoApprove: true, historyMessages: 40, historyLines: 40, maxTokens: 1000 };
const makeAgent = ({ config = {}, ...extra } = {}) =>
  new Agent({ client: {}, config: { ...baseConfig, ...config }, ...extra });
const call = (id, name, args = {}) => ({
  id,
  type: 'function',
  function: { name, arguments: JSON.stringify(args) },
});
const forcedNotes = (agent) =>
  agent.messages.filter((m) => m.role === 'user' && /runtime stopped the tool loop/.test(m.content || ''));

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


/* --------------------------- the round budget ---------------------------- */

test('the loop stops at the configured budget and answers, instead of looping', async () => {
  // The bug this replaces: the only bound was 100 rounds, and running out of it
  // pushed the literal string "(stopped: too many tool calls in a row)" into the
  // transcript as if the assistant had said it.
  const agent = makeAgent({ config: { maxToolSteps: 3 } });
  let round = 0;
  agent.runToolCall = async (c) => `out-${c.id}`;
  agent.streamTurn = async (opts = {}) => {
    if (opts.useTools === false) return { content: 'here is what I did', toolCalls: [] };
    round++;
    return { content: '', toolCalls: [call(`c${round}`, 'read_file', { path: `f${round}.txt` })] };
  };

  const out = await agent.send('go');

  assert.equal(round, 3, 'it ran exactly the configured number of tool rounds');
  assert.equal(out, 'here is what I did', 'the request ends with a real answer');
  assert.ok(!agent.messages.some((m) => /too many tool calls in a row/.test(m.content || '')),
    'the canned failure string is never written to history');
  assert.equal(agent.messages.at(-1).role, 'assistant');
  assert.match(forcedNotes(agent)[0].content, /the tool budget for this request is spent \(3 rounds\)/);
});

test('the forced final turn has no tools, so the model writes instead of investigating', async () => {
  const agent = makeAgent({ config: { maxToolSteps: 1 } });
  const toolFlags = [];
  agent.runToolCall = async () => 'ok';
  agent.streamTurn = async (opts = {}) => {
    toolFlags.push(opts.useTools);
    return opts.useTools === false
      ? { content: 'summary', toolCalls: [] }
      : { content: '', toolCalls: [call('a', 'read_file', { path: 'x.txt' })] };
  };

  assert.equal(await agent.send('go'), 'summary');
  assert.deepEqual(toolFlags, [undefined, false], 'only the hand-off turn withholds tools');
});

test('a turn stopped by the budget still answers every tool call it declared', async () => {
  const agent = makeAgent({ config: { maxToolSteps: 2 } });
  let round = 0;
  agent.runToolCall = async (c) => `out-${c.id}`;
  agent.streamTurn = async (opts = {}) => {
    if (opts.useTools === false) return { content: 'done', toolCalls: [] };
    round++;
    return {
      content: '',
      toolCalls: [
        call(`a${round}`, 'read_file', { path: `a${round}.txt` }),
        call(`b${round}`, 'list_files', { path: `b${round}` }),
      ],
    };
  };

  await agent.send('go');
  assertPaired(agent, ['a1', 'b1', 'a2', 'b2']);
});

test('one model round cannot exceed the total call budget, including a continue request', async () => {
  const agent = makeAgent({ config: { maxToolSteps: 10, maxToolCalls: 2 } });
  let executed = 0;
  let decisions = 0;
  agent.runToolCall = async () => { executed++; return 'ok'; };
  agent.streamTurn = async ({ useTools } = {}) => {
    if (useTools === false) return { content: 'limited summary', toolCalls: [] };
    decisions++;
    return { content: 'continue', toolCalls: [
      call('one', 'read_file', { path: 'a' }),
      call('two', 'read_file', { path: 'b' }),
      call('three', 'read_file', { path: 'c' }),
    ] };
  };
  assert.equal(await agent.send('inspect'), 'limited summary');
  assert.equal(decisions, 1);
  assert.equal(executed, 2);
  assertPaired(agent, ['one', 'two', 'three']);
  assert.match(agent.messages.find(m => m.tool_call_id === 'three').content, /Not run:.*budget/);
});

test('a stopped turn returns honest text even when the summarising call fails', async () => {
  const agent = makeAgent({ config: { maxToolSteps: 1 } });
  agent.runToolCall = async () => 'ok';
  agent.streamTurn = async (opts = {}) => {
    if (opts.useTools === false) throw new Error('the model is down');
    return { content: '', toolCalls: [call('a', 'read_file', { path: 'x.txt' })] };
  };

  const out = await agent.send('go');

  assert.match(out, /stopped there/i);
  assert.match(out, /tool budget for this request is spent/);
  assert.match(out, /read_file/, 'it names what it actually ran');
  assert.equal(out, agent.messages.at(-1).content, 'the returned answer is the one in history');
});

/* --------------------------- the no-progress guard ----------------------- */

test('repeating one identical call stops the loop on the third round', async () => {
  const agent = makeAgent();
  let round = 0;
  agent.runToolCall = async () => 'same listing';
  agent.streamTurn = async (opts = {}) => {
    if (opts.useTools === false) return { content: 'stopped summary', toolCalls: [] };
    round++;
    return { content: '', toolCalls: [call(`r${round}`, 'read_file', { path: '.' })] };
  };

  const out = await agent.send('go');

  assert.equal(out, 'stopped summary');
  assert.equal(round, MAX_REPEAT_CALLS, 'it stops on the round that repeats too often, not at the budget');
  const notes = agent.messages.filter((m) => m.role === 'tool' && /Repeated call/.test(m.content || ''));
  assert.equal(notes.length, MAX_REPEAT_CALLS - 1, 'the repeating rounds are told, in the tool result');
  assert.match(forcedNotes(agent)[0].content,
    /kept repeating read_file with identical arguments \(3 times this request\)/);
});

test('the same call with reordered arguments still counts as a repeat', async () => {
  const agent = makeAgent();
  let round = 0;
  agent.runToolCall = async () => 'same';
  agent.streamTurn = async (opts = {}) => {
    if (opts.useTools === false) return { content: 'stopped summary', toolCalls: [] };
    round++;
    // Round two asks the identical question with the keys in another order.
    const args = round === 2 ? { encoding: 'utf8', path: '.' } : { path: '.', encoding: 'utf8' };
    return { content: '', toolCalls: [call(`r${round}`, 'read_file', args)] };
  };

  assert.equal(await agent.send('go'), 'stopped summary');
  assert.match(forcedNotes(agent)[0].content, /kept repeating/);
});

test('nested argument key order does not disguise repeated requests', async () => {
  const agent = makeAgent();
  let round = 0;
  agent.runToolCall = async () => 'same result';
  agent.streamTurn = async ({ useTools } = {}) => {
    if (useTools === false) return { content: 'summary', toolCalls: [] };
    round++;
    const filters = round === 2 ? { exclude: 'build', include: 'src' } : { include: 'src', exclude: 'build' };
    return { content: '', toolCalls: [call(`n${round}`, 'search_files', { filters })] };
  };
  assert.equal(await agent.send('look'), 'summary');
  assert.equal(round, MAX_REPEAT_CALLS);
});

test('equivalent relative paths cannot bypass the repeat guard', async () => {
  const agent = makeAgent();
  let round = 0;
  agent.runToolCall = async () => 'same file';
  agent.streamTurn = async ({ useTools } = {}) => {
    if (useTools === false) return { content: 'summary', toolCalls: [] };
    round++;
    return { content: '', toolCalls: [call(`p${round}`, 'read_file', { path: round === 2 ? './notes.txt' : 'notes.txt' })] };
  };
  assert.equal(await agent.send('look'), 'summary');
  assert.equal(round, MAX_REPEAT_CALLS);
});

test('identical parallel calls in one round are a batch, not a loop', async () => {
  // Three reads of the same path declared together is a batching choice by the
  // model. Counting them as a cycle would stop legitimate parallel work.
  const agent = makeAgent();
  let turn = 0;
  agent.runToolCall = async () => 'listing';
  agent.streamTurn = async () => {
    turn++;
    return turn === 1
      ? {
        content: '',
        toolCalls: [
          call('a', 'read_file', { path: '.' }),
          call('b', 'read_file', { path: '.' }),
          call('c', 'read_file', { path: '.' }),
        ],
      }
      : { content: 'done', toolCalls: [] };
  };

  assert.equal(await agent.send('go'), 'done');
  assert.equal(turn, 2, 'the loop continued to the next round');
  assert.deepEqual(forcedNotes(agent), [], 'nothing was stopped');
});

test('the counters start over for the next request', async () => {
  const agent = makeAgent({ config: { maxToolSteps: 1 } });
  agent.runToolCall = async () => 'ok';
  agent.streamTurn = async (opts = {}) => (opts.useTools === false
    ? { content: 'summary', toolCalls: [] }
    : { content: '', toolCalls: [call('a', 'read_file', { path: 'same.txt' })] });

  assert.equal(await agent.send('first'), 'summary');
  assert.equal(await agent.send('second'), 'summary');

  assert.equal(agent.repeatsThisTurn.size, 1, 'one signature for this request');
  assert.equal([...agent.repeatsThisTurn.values()][0].count, 1,
    'the same call in a new request is not a repeat of the old one');
  const notes = forcedNotes(agent);
  assert.equal(notes.length, 2, 'both requests were stopped');
  for (const note of notes) assert.doesNotMatch(note.content, /kept repeating/, 'neither stop was the repeat guard');
});

/* ------------------------------ the prompt ------------------------------ */

test('the prompt states the termination policy and the bound it enforces', () => {
  const prompt = buildSystemPrompt({ maxToolSteps: 5 }, process.cwd(), null, []);

  assert.match(prompt, /TOOL EXECUTION POLICY/);
  assert.match(prompt, /not an autonomous researcher/);
  assert.match(prompt, /stop calling tools and answer now/);
  assert.match(prompt, /do not investigate your own investigation/);
  assert.match(prompt, /5 consecutive tool rounds/, 'it quotes the configured bound, not the default');
  assert.match(prompt, /report what you completed and what is still unknown/);
  // It must not undo the existing rule that one failed attempt is not an answer:
  // this policy is about a finished task, not about giving up on a failure.
  assert.match(prompt, /One failed attempt is not an answer/);
  assert.doesNotMatch(prompt, /(?:do not invent|never invent) (?:commands|shell)|made-up command/i);
});

/* ---------------------------- the settings ------------------------------ */

test('MAX_TOOL_STEPS is configurable and clamped, with no unlimited setting', () => {
  const write = (name, body) => {
    const file = path.join(SANDBOX, name);
    fs.writeFileSync(file, body);
    return file;
  };

  process.env.MAX_TOOL_STEPS = '7';
  assert.equal(loadConfig(write('set.env', '')).maxToolSteps, 7, 'the env var is honoured');
  assert.equal(loadConfig(write('high.env', 'MAX_TOOL_STEPS=99999')).maxToolSteps, 200, 'clamped to the ceiling');
  assert.equal(loadConfig(write('zero.env', 'MAX_TOOL_STEPS=0')).maxToolSteps, 1, 'zero means one round, never unlimited');
  assert.equal(loadConfig(write('negative.env', 'MAX_TOOL_STEPS=-5')).maxToolSteps, 1);
  assert.equal(loadConfig(write('garbage.env', 'MAX_TOOL_STEPS=soon')).maxToolSteps, MAX_TOOL_STEPS, 'garbage falls back');

  delete process.env.MAX_TOOL_STEPS;
  assert.equal(loadConfig(write('unset.env', '')).maxToolSteps, MAX_TOOL_STEPS, 'the default matches the constant');
});

test('total tool call budget and agent diagnostics load from config', () => {
  const file = path.join(SANDBOX, 'diagnostics.env');
  fs.writeFileSync(file, 'MAX_TOOL_CALLS=2\nANKITA_AGENT_DEBUG=1\n');
  const config = loadConfig(file);
  assert.equal(config.maxToolCalls, 2);
  assert.equal(config.agentDebug, true);
});

test('debug trace links request and tool events without exposing arguments', async () => {
  const agent = makeAgent({ config: { agentDebug: true, maxToolSteps: 1 } });
  const logs = [];
  const original = console.error;
  console.error = line => logs.push(JSON.parse(line));
  try {
    agent.runToolCall = async () => 'ok';
    agent.streamTurn = async ({ useTools } = {}) => useTools === false
      ? { content: 'done', toolCalls: [] }
      : { content: '', toolCalls: [call('secret', 'read_file', { path: 'x', token: 'sensitive-value' })] };
    await agent.send('go');
  } finally {
    console.error = original;
  }
  assert.ok(logs.find(event => event.event === 'request')?.request_id);
  assert.equal(logs.find(event => event.event === 'tool_call').tool_name, 'read_file');
  assert.equal(logs.find(event => event.event === 'tool_result').success, true);
  assert.match(logs.find(event => event.event === 'final').termination_reason, /budget/);
  assert.doesNotMatch(JSON.stringify(logs), /sensitive-value/);
});

test('the default budget is a sane bound, not the old hundred rounds', () => {
  assert.ok(MAX_TOOL_STEPS > 1 && MAX_TOOL_STEPS <= 50,
    `MAX_TOOL_STEPS must stay a real bound, got ${MAX_TOOL_STEPS}`);
  assert.ok(MAX_REPEAT_CALLS >= 2 && MAX_REPEAT_CALLS < MAX_TOOL_STEPS,
    'the repeat guard must be able to fire before the budget runs out');
});


