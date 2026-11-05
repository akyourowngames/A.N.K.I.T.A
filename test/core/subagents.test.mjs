import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// Sandbox config and sessions so a live child transcript never touches the
// user's real ~/.copilot-chat-cli store.
const SANDBOX = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-subagents-'));
process.env.CONFIG_DIR = SANDBOX;
test.after(() => fs.rmSync(SANDBOX, { recursive: true, force: true }));

const registry = await import('../../src/core/subagents/registry.mjs');
const runtimeModule = await import('../../src/core/subagents/runtime.mjs');
const { createSubagentRuntime, pruneSubagentTranscripts } = runtimeModule;
const { SESSIONS_DIR } = await import('../../src/core/config.mjs');
const index = await import('../../tools/index.mjs');
const delegate = await import('../../tools/delegate-task.mjs');
const { Agent } = await import('../../src/core/agent.mjs');
const { ProfileStore } = await import('../../src/memory/profile.mjs');

// Start from the shipped defaults so the suite cannot drift from the registry.
const CONFIG = (patch = {}) => ({
  subagentsEnabled: registry.SUBAGENT_DEFAULTS.enabled,
  maxSubagentDepth: registry.SUBAGENT_DEFAULTS.maxDepth,
  maxConcurrentSubagents: registry.SUBAGENT_DEFAULTS.concurrency,
  maxSubagentsPerTurn: registry.SUBAGENT_DEFAULTS.perTurn,
  subagentMaxToolSteps: registry.SUBAGENT_DEFAULTS.toolSteps,
  subagentMaxToolCalls: registry.SUBAGENT_DEFAULTS.toolCalls,
  subagentTimeoutMs: registry.SUBAGENT_DEFAULTS.timeoutMs,
  subagentMaxTokens: registry.SUBAGENT_DEFAULTS.tokens,
  subagentMaxResultBytes: registry.SUBAGENT_DEFAULTS.resultBytes,
  ...patch,
});

function makeParent(patch = {}) {
  return {
    client: {},
    config: CONFIG(),
    depth: 0,
    cwd: SANDBOX,
    workspacePath: SANDBOX,
    project: '',
    projectId: null,
    toolContext: {},
    sessionId: 'parent-session',
    emitSubagentEvent: () => {},
    confirm: async () => true,
    abort: null,
    ...patch,
  };
}

function childFactory(run) {
  const seen = [];
  const createAgent = options => {
    seen.push(options);
    const child = {
      messages: [{ role: 'user', content: 'seeded from send' }],
      ranThisTurn: [],
      sessionUsage: { prompt_tokens: 12, completion_tokens: 8, total_tokens: 20 },
      async send(prompt, callbacks = {}) {
        return run({ options, child, prompt, callbacks });
      },
      async cancel() { child.cancelled = true; },
      executionHost: () => ({ cancel: async () => {} }),
    };
    return child;
  };
  return { createAgent, seen };
}

async function defaultRun({ child, callbacks }) {
  const call = { id: 'tool-1', function: { name: 'read_file', arguments: JSON.stringify({ path: 'src/core/agent.mjs' }) } };
  callbacks.onToolCall?.(call);
  child.ranThisTurn.push('read_file');
  callbacks.onToolResult?.(call, 'export const loop = true;');
  callbacks.onDelta?.('The loop is in src/core/agent.mjs:1.');
  callbacks.onUsage?.({ total_tokens: 20 });
  child.messages.push({ role: 'assistant', content: 'The loop is in src/core/agent.mjs:1.' });
  return 'The loop is in src/core/agent.mjs:1.';
}

function waitFor(check, timeoutMs = 3000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const tick = () => {
      if (check()) return resolve();
      if (Date.now() > deadline) return reject(new Error('timed out waiting for the expected sub-agent state'));
      setTimeout(tick, 5);
    };
    tick();
  });
}

test('the delegate_task tool is one typed entry and classifies its presets', () => {
  assert.equal(delegate.name, registry.SUBAGENT_TOOL);
  assert.equal(index.get('delegate_task'), delegate);
  assert.ok(!index.coreNames().includes(delegate.name), 'delegation is discovered on demand, not paid for on every turn');
  assert.ok(index.deferredSpecByName.has(delegate.name));
  assert.ok(index.CATEGORIES.find(category => category.id === 'subagents')?.tools.includes(delegate));
  assert.deepEqual([...registry.SUBAGENT_TYPES], ['explore', 'reviewer', 'worker']);
  assert.equal(delegate.readOnly({ subagent_type: 'explore' }), true);
  assert.equal(delegate.readOnly({ subagent_type: 'reviewer' }), true);
  assert.equal(delegate.readOnly({ subagent_type: 'worker' }), false);
  assert.match(delegate.run({ subagent_type: 'nope', description: 'x', prompt: 'x' }, {}), /must be one of/);
  assert.match(delegate.run({ subagent_type: 'explore', description: 'x', prompt: ' ' }, {}), /nonempty/);
  assert.match(delegate.run({ subagent_type: 'explore', description: 'x', prompt: 'x' }, {}), /unavailable/);
  assert.deepEqual(Object.keys(delegate.parameters.properties).sort(),
    ['background', 'description', 'max_steps', 'prompt', 'subagent_type', 'timeout_ms']);
  assert.equal(delegate.parameters.properties.max_steps.maximum, registry.SUBAGENT_LIMITS.maxToolSteps);
  assert.equal(delegate.parameters.properties.timeout_ms.maximum, registry.SUBAGENT_LIMITS.maxTimeoutMs);
});

test('per-call budgets can tighten the configured cap but never raise it', async () => {
  assert.equal(runtimeModule.resolveTimeout({ timeout_ms: 999_999_999 }, { subagentTimeoutMs: 300_000 }), 300_000);
  assert.equal(runtimeModule.resolveTimeout({ timeout_ms: 15_000 }, { subagentTimeoutMs: 300_000 }), 15_000);
  assert.equal(runtimeModule.resolveTimeout({}, {}), registry.SUBAGENT_DEFAULTS.timeoutMs);
  assert.equal(runtimeModule.resolveStepLimit({ max_steps: 5_000 }, { subagentMaxToolSteps: 100 }), 100);
  assert.equal(runtimeModule.resolveStepLimit({ max_steps: 12 }, { subagentMaxToolSteps: 100 }), 12);
  assert.equal(runtimeModule.resolveStepLimit({}, {}), registry.SUBAGENT_DEFAULTS.toolSteps);

  const { createAgent, seen } = childFactory(defaultRun);
  const runtime = createSubagentRuntime({
    parent: makeParent({ config: CONFIG({ subagentMaxToolSteps: 7 }) }),
    createAgent,
    toolNames: index.names(),
  });
  await runtime.run({ subagent_type: 'explore', description: 'caps', prompt: 'caps', max_steps: 999 }, { callId: 'cap' });
  assert.equal(seen[0].config.maxToolSteps, 7, 'the request cannot exceed the configured step cap');
});

test('transcript retention keeps the newest child runs and never touches teammates', () => {
  const dir = path.join(SANDBOX, 'retention');
  fs.mkdirSync(dir, { recursive: true });
  const write = (name, ageSeconds) => {
    const file = path.join(dir, name);
    fs.writeFileSync(file, '{}');
    const at = new Date(Date.now() - ageSeconds * 1000);
    fs.utimesSync(file, at, at);
    return file;
  };
  const old = [1, 2, 3, 4].map((i) => write(`subagent-old-${i}.json`, 4000 + i));
  const recent = [1, 2].map((i) => write(`subagent-new-${i}.json`, 100 + i));
  const teammate = write('teammate-keep.json', 9999);
  const unrelated = write('dm-1.json', 9999);

  pruneSubagentTranscripts(dir, 3);

  assert.ok(recent.every((file) => fs.existsSync(file)), 'the newest runs survive');
  assert.deepEqual(old.filter((file) => fs.existsSync(file)), [old[0]], 'oldest transcripts are pruned first');
  assert.ok(fs.existsSync(teammate), 'teammate sessions are never pruned');
  assert.ok(fs.existsSync(unrelated), 'unrelated session files are never pruned');
});

test('delegate_task is discovered only for eligible foreground parents', async () => {
  const agent = new Agent({ client: {}, config: CONFIG({ tools: true, memoryConsolidation: false }), skillsEnabled: false,
    workspacePath: SANDBOX, print: () => {}, write: () => {} });
  assert.ok(!agent.currentSpecs().some(spec => spec.function.name === registry.SUBAGENT_TOOL));
  assert.match(agent.messages[0].content, /subagents: delegate_task/);
  await agent.runToolCall({ id: 'discover', type: 'function', function: { name: 'find_tools', arguments: JSON.stringify({ query: 'delegate' }) } });
  assert.ok(agent.currentSpecs().some(spec => spec.function.name === registry.SUBAGENT_TOOL));

  const job = new Agent({ client: {}, config: CONFIG({ tools: true, backgroundJob: true, memoryConsolidation: false }), skillsEnabled: false,
    workspacePath: SANDBOX, print: () => {}, write: () => {} });
  assert.doesNotMatch(job.messages[0].content, /subagents: delegate_task/);
  const backgroundDiscovery = await job.runToolCall({ id: 'discover', type: 'function', function: { name: 'find_tools', arguments: JSON.stringify({ query: 'delegate' }) } });
  assert.ok(!job.currentSpecs().some(spec => spec.function.name === registry.SUBAGENT_TOOL));
  assert.doesNotMatch(backgroundDiscovery, /Now callable: delegate_task/);
  assert.doesNotMatch(backgroundDiscovery, /subagents/);
});

test('explore runs read-only with a scoped toolset and reports a scoped envelope', async () => {
  const events = [];
  const { createAgent, seen } = childFactory(defaultRun);
  const runtime = createSubagentRuntime({
    parent: makeParent({ emitSubagentEvent: event => events.push(event) }),
    createAgent,
    toolNames: index.names(),
  });

  const output = JSON.parse(await runtime.run(
    { subagent_type: 'explore', description: 'Find the loop', prompt: 'Find the agent loop and cite it.' },
    { callId: 'parent-call-1' },
  ));

  assert.equal(output.status, registry.SUBAGENT_STATUS.completed);
  assert.equal(output.subagentType, 'explore');
  assert.equal(output.parentCallId, 'parent-call-1');
  assert.equal(output.description, 'Find the loop');
  assert.equal(output.summary, 'The loop is in src/core/agent.mjs:1.');
  assert.deepEqual(output.toolsUsed, ['read_file']);

  const options = seen[0];
  assert.equal(options.readOnly, true);
  assert.equal(options.depth, 1);
  assert.equal(options.deferTools, false);
  assert.equal(options.skillsEnabled, false);
  assert.equal(options.memoryEnabled, false);
  assert.equal(options.mcp, null);
  assert.equal(options.config.subagentsEnabled, false);
  assert.ok(options.allowedTools.has('read_file'));
  assert.ok(options.allowedTools.has('git'));
  assert.ok(!options.allowedTools.has('write_file'));
  assert.ok(!options.allowedTools.has('run_command'));
  assert.ok(!options.allowedTools.has('delegate_task'));
  assert.ok(!options.allowedTools.has('browser'));
  assert.match(options.systemSuffix, /isolated context/);

  assert.deepEqual(events.map(event => event.type), [
    registry.SUBAGENT_EVENT.start,
    registry.SUBAGENT_EVENT.toolCall,
    registry.SUBAGENT_EVENT.toolResult,
    registry.SUBAGENT_EVENT.delta,
    registry.SUBAGENT_EVENT.end,
  ]);
  assert.equal(events.at(-1).status, 'completed');

  assert.ok(output.transcript.startsWith(path.join(SESSIONS_DIR, registry.SUBAGENT_TRANSCRIPT_PREFIX)));
  const transcript = JSON.parse(fs.readFileSync(output.transcript, 'utf8'));
  assert.equal(transcript.kind, 'subagent');
  assert.equal(transcript.subagentType, 'explore');
  assert.equal(transcript.parentCallId, 'parent-call-1');
  assert.equal(transcript.status, 'completed');
  assert.equal(transcript.workspacePath, SANDBOX);
  assert.equal(transcript.messages.length, 2);
});

test('children never inject pinned personal memory into their prompts', async () => {
  const profileFile = path.join(SANDBOX, 'child-profile.json');
  const pinnedFact = 'Pinned private preference for the parent only';
  new ProfileStore(profileFile).add({ text: pinnedFact, always: true });
  const factory = childFactory(defaultRun);
  const runtime = createSubagentRuntime({
    parent: makeParent({ toolContext: { profileFile } }),
    createAgent: factory.createAgent,
    toolNames: index.names(),
  });
  await runtime.run({ subagent_type: 'explore', description: 'Research', prompt: 'Research without personal memory.' });

  const child = new Agent(factory.seen[0]);
  assert.doesNotMatch(child.messages[0].content, new RegExp(pinnedFact));
  assert.doesNotMatch(child.messages[0].content, /Personal memory store:/);
  const parent = new Agent({ ...factory.seen[0], memoryEnabled: true });
  assert.match(parent.messages[0].content, new RegExp(pinnedFact));
});

test('worker keeps the write toolset, requires approval context, and never delegates again', async () => {
  let approval = null;
  const { createAgent, seen } = childFactory(async ({ child, callbacks }) => {
    callbacks.onDelta?.('Edited one file.');
    child.messages.push({ role: 'assistant', content: 'Edited one file.' });
    return 'Edited one file.';
  });
  const runtime = createSubagentRuntime({
    parent: makeParent({ confirm: async (name, detail, metadata) => { approval = { name, detail, metadata }; return true; } }),
    createAgent,
    toolNames: index.names(),
  });

  const output = JSON.parse(await runtime.run(
    { subagent_type: 'worker', description: 'Apply the fix', prompt: 'Edit src/core/agent.mjs.' },
    { callId: 'parent-call-2' },
  ));

  assert.equal(output.status, 'completed');
  const options = seen[0];
  assert.equal(options.readOnly, false);
  assert.ok(options.allowedTools.has('write_file'));
  assert.ok(options.allowedTools.has('run_command'));
  assert.ok(!options.allowedTools.has('delegate_task'));
  assert.ok(!options.allowedTools.has('browser'));
  assert.ok(!options.allowedTools.has('schedule'));
  assert.ok(!options.allowedTools.has('mcp_manage'));

  await options.confirm('write_file', 'src/core/agent.mjs');
  assert.deepEqual(approval, {
    name: 'write_file',
    detail: 'src/core/agent.mjs',
    metadata: { subagentId: output.subagentId, subagentType: 'worker', subagentDescription: 'Apply the fix' },
  });
});

test('guards depth, disabled config, and the per-request budget before spawning a child', async () => {
  let spawned = 0;
  const createAgent = () => { spawned++; throw new Error('must not spawn'); };
  const run = (parent, args = { subagent_type: 'explore', description: 'x', prompt: 'x' }) => {
    const runtime = createSubagentRuntime({ parent, createAgent, toolNames: index.names() });
    return runtime.run(args, { callId: 'call' }).then(JSON.parse);
  };

  const tooDeep = await run(makeParent({ depth: 1 }));
  assert.equal(tooDeep.status, registry.SUBAGENT_STATUS.rejected);
  assert.match(tooDeep.error, /depth limit/);

  const disabled = await run(makeParent({ config: CONFIG({ subagentsEnabled: false }) }));
  assert.equal(disabled.status, registry.SUBAGENT_STATUS.rejected);
  assert.match(disabled.error, /disabled/);

  const runtime = createSubagentRuntime({
    parent: makeParent({ config: CONFIG({ maxSubagentsPerTurn: 1 }) }),
    createAgent: childFactory(defaultRun).createAgent,
    toolNames: index.names(),
  });
  assert.equal(JSON.parse(await runtime.run({ subagent_type: 'explore', description: 'one', prompt: 'one' }, { callId: 'a' })).status, 'completed');
  const second = JSON.parse(await runtime.run({ subagent_type: 'explore', description: 'two', prompt: 'two' }, { callId: 'b' }));
  assert.equal(second.status, registry.SUBAGENT_STATUS.rejected);
  assert.match(second.error, /budget/);
  runtime.beginTurn();
  assert.equal(JSON.parse(await runtime.run({ subagent_type: 'explore', description: 'three', prompt: 'three' }, { callId: 'c' })).status, 'completed');
  assert.equal(spawned, 0);

  const missing = await run(makeParent(), { subagent_type: 'missing', description: 'x', prompt: 'x' });
  assert.equal(missing.status, registry.SUBAGENT_STATUS.rejected);
});

function gatedFactory() {
  let active = 0;
  let peak = 0;
  const gates = [];
  let started = 0;
  const createAgent = () => {
    const child = {
      messages: [],
      ranThisTurn: [],
      sessionUsage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
      async send() {
        started++;
        active++;
        peak = Math.max(peak, active);
        await new Promise(resolve => gates.push(resolve));
        active--;
        child.messages.push({ role: 'assistant', content: 'done' });
        return 'done';
      },
      async cancel() {},
      executionHost: () => ({ cancel: async () => {} }),
    };
    return child;
  };
  return { createAgent, gates, peak: () => peak, started: () => started };
}

test('read-only children overlap across runtimes; workers sharing a workspace do not', async () => {
  const readOnly = gatedFactory();
  const one = createSubagentRuntime({ parent: makeParent(), createAgent: readOnly.createAgent, toolNames: index.names() });
  const two = createSubagentRuntime({ parent: makeParent(), createAgent: readOnly.createAgent, toolNames: index.names() });
  const parallel = Promise.all([
    one.run({ subagent_type: 'explore', description: 'a', prompt: 'a' }, { callId: 'a' }),
    two.run({ subagent_type: 'reviewer', description: 'b', prompt: 'b' }, { callId: 'b' }),
  ]);
  await waitFor(() => readOnly.gates.length === 2);
  assert.equal(readOnly.peak(), 2);
  for (const gate of readOnly.gates) gate();
  assert.equal((await parallel).map(value => JSON.parse(value).status).join(','), 'completed,completed');

  const workers = gatedFactory();
  const three = createSubagentRuntime({ parent: makeParent(), createAgent: workers.createAgent, toolNames: index.names() });
  const four = createSubagentRuntime({ parent: makeParent(), createAgent: workers.createAgent, toolNames: index.names() });
  const serial = Promise.all([
    three.run({ subagent_type: 'worker', description: 'a', prompt: 'a' }, { callId: 'a' }),
    four.run({ subagent_type: 'worker', description: 'b', prompt: 'b' }, { callId: 'b' }),
  ]);
  await waitFor(() => workers.gates.length === 1);
  assert.equal(workers.peak(), 1);
  assert.equal(workers.started(), 1);
  workers.gates[0]();
  await waitFor(() => workers.gates.length === 2);
  workers.gates[1]();
  assert.equal((await serial).map(value => JSON.parse(value).status).join(','), 'completed,completed');
  assert.equal(workers.peak(), 1);
});

test('cancelling a queued worker preserves the lock for later workers', async () => {
  const workers = gatedFactory();
  const controller = new AbortController();
  const runtime = createSubagentRuntime({ parent: makeParent(), createAgent: workers.createAgent, toolNames: index.names() });
  const args = description => ({ subagent_type: 'worker', description, prompt: description });
  const first = runtime.run(args('first'), { callId: 'first' });
  await waitFor(() => workers.gates.length === 1);
  const second = runtime.run(args('second'), { callId: 'second', signal: controller.signal });
  await new Promise(resolve => setImmediate(resolve));
  controller.abort();
  assert.equal(JSON.parse(await second).status, registry.SUBAGENT_STATUS.cancelled);

  const third = runtime.run(args('third'), { callId: 'third' });
  await new Promise(resolve => setImmediate(resolve));
  const startedBeforeFirstFinished = workers.started();
  workers.gates[0]();
  await waitFor(() => workers.gates.length === 2);
  workers.gates[1]();
  assert.equal((await Promise.all([first, third])).map(value => JSON.parse(value).status).join(','), 'completed,completed');
  assert.equal(startedBeforeFirstFinished, 1, 'the third worker cannot overtake the running first worker');
  assert.equal(workers.peak(), 1);
});

test('workspace aliases and Windows case variants share one worker lock', async () => {
  const workspace = path.join(SANDBOX, 'canonical-workspace');
  const alias = path.join(SANDBOX, 'workspace-alias');
  fs.mkdirSync(workspace);
  fs.symlinkSync(workspace, alias, process.platform === 'win32' ? 'junction' : 'dir');

  const exercise = async (firstPath, secondPath) => {
    const workers = gatedFactory();
    const one = createSubagentRuntime({ parent: makeParent({ workspacePath: firstPath }), createAgent: workers.createAgent, toolNames: index.names() });
    const two = createSubagentRuntime({ parent: makeParent({ workspacePath: secondPath }), createAgent: workers.createAgent, toolNames: index.names() });
    const args = description => ({ subagent_type: 'worker', description, prompt: description });
    const pending = [one.run(args('one'), { callId: 'one' }), two.run(args('two'), { callId: 'two' })];
    await waitFor(() => workers.gates.length >= 1);
    await new Promise(resolve => setImmediate(resolve));
    const earlyPeak = workers.peak();
    for (const gate of [...workers.gates]) gate();
    await waitFor(() => workers.gates.length === 2);
    for (const gate of [...workers.gates]) gate();
    assert.equal((await Promise.all(pending)).map(value => JSON.parse(value).status).join(','), 'completed,completed');
    assert.equal(earlyPeak, 1);
  };

  await exercise(workspace, alias);
  if (process.platform === 'win32') await exercise(workspace, workspace.toUpperCase());
});

test('aborting the parent stops the child and reports a cancellation', async () => {
  const controller = new AbortController();
  let stopping = null;
  let started = false;
  const createAgent = () => ({
    messages: [],
    ranThisTurn: [],
    sessionUsage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
    async send() {
      started = true;
      await new Promise((resolve, reject) => { stopping = () => reject(new Error('stopped')); });
      return 'late answer';
    },
    async cancel() { stopping?.(); },
    executionHost: () => ({ cancel: async () => {} }),
  });
  const runtime = createSubagentRuntime({ parent: makeParent(), createAgent, toolNames: index.names() });
  const pending = runtime.run({ subagent_type: 'worker', description: 'slow', prompt: 'slow' }, { callId: 'slow', signal: controller.signal });
  await waitFor(() => started);
  controller.abort();
  const output = JSON.parse(await pending);
  assert.equal(output.status, registry.SUBAGENT_STATUS.cancelled);
  assert.match(output.summary, /Cancelled/);
});

test('the parent loop overlaps read-only delegations and barriers write-capable ones', async () => {
  const call = (id, type) => ({
    id, type: 'function',
    function: { name: 'delegate_task', arguments: JSON.stringify({ subagent_type: type, description: id, prompt: id }) },
  });
  const makeAgent = () => new Agent({
    client: {}, memoryEnabled: false,
    config: { tools: true, autoApprove: true, historyMessages: 20, historyLines: 20, maxTokens: 1000 },
  });

  const overlap = async types => {
    const agent = makeAgent();
    let active = 0;
    let peak = 0;
    agent.runToolCall = async () => {
      active++;
      peak = Math.max(peak, active);
      await new Promise(resolve => setTimeout(resolve, 15));
      active--;
      return '{"status":"completed"}';
    };
    let round = 0;
    agent.streamTurn = async () => {
      round++;
      if (round === 1) return { content: '', toolCalls: types.map((type, position) => call(`call-${position}`, type)) };
      return { content: 'Finished', toolCalls: [] };
    };
    assert.equal(await agent.send('delegate'), 'Finished');
    return peak;
  };

  assert.equal(await overlap(['explore', 'reviewer']), 2);
  assert.equal(await overlap(['worker', 'worker']), 1);
  assert.equal(await overlap(['explore', 'worker', 'explore']), 1);
});
