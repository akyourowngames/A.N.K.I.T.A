import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-subagent-messaging-'));
process.env.CONFIG_DIR = sandbox;
test.after(() => fs.rmSync(sandbox, { recursive: true, force: true }));
const { createSubagentRuntime } = await import('../../src/core/subagents/runtime.mjs');

function harness() {
  const events = [];
  const children = [];
  const parent = { config: { maxConcurrentSubagents: 1 }, workspacePath: sandbox,
    emitSubagentEvent: event => events.push(event) };
  const runtime = createSubagentRuntime({ parent, toolNames: ['subagent_control'], createAgent(options) {
    let finish;
    const child = { options, messages: [], sessionUsage: {}, ranThisTurn: [],
      send: () => new Promise(resolve => { finish = resolve; }),
      cancel: async () => finish?.('cancelled'),
      executionHost: () => ({ cancel: async () => {} }),
      finish: answer => finish(answer),
    };
    children.push(child);
    return child;
  } });
  return { runtime, events, children, parent };
}

const brief = description => ({ subagent_type: 'explore', description, prompt: description, background: true });
const tick = () => new Promise(resolve => setImmediate(resolve));

test('background children return IDs immediately and exchange queued messages in both directions', async () => {
  const { runtime, children, events } = harness();
  assert.equal(typeof runtime.control, 'function');
  const first = JSON.parse(await runtime.run(brief('first')));
  const second = JSON.parse(await runtime.run(brief('second')));
  assert.equal(first.status, 'running');
  assert.equal(second.status, 'queued');
  assert.equal(children.length, 1);
  assert.equal(JSON.parse(await runtime.control({ action: 'send', subagent_id: second.subagentId, message: 'Use the new brief' })).status, 'queued');
  const childSend = await children[0].options.toolContext.subagentControl({ action: 'send', subagent_id: 'parent', message: 'Found a clue' });
  assert.equal(JSON.parse(childSend).status, 'queued');
  assert.equal(runtime.takeMessages()[0].message, 'Found a clue');
  assert.deepEqual(runtime.takeMessages(), []);
  children[0].finish('first done');
  await runtime.control({ action: 'wait', subagent_id: first.subagentId });
  await tick();
  assert.equal(children.length, 2);
  assert.deepEqual(children[1].options.toolContext.takeSubagentMessages().map(item => item.message), ['Use the new brief']);
  children[1].finish('second done');
  const completed = JSON.parse(await runtime.control({ action: 'wait', subagent_id: second.subagentId }));
  assert.equal(completed.status, 'completed');
  assert.equal(completed.result, 'second done');
  assert.equal(runtime.takeMessages().filter(item => item.kind === 'result').length, 2);
  assert.equal(events.filter(event => event.type === 'subagent-message').length, 2);
});

test('controls reject foreign IDs and child attempts to control siblings, and cancellation settles queued work', async () => {
  const { runtime, children } = harness();
  assert.equal(typeof runtime.control, 'function');
  const first = JSON.parse(await runtime.run(brief('first')));
  const second = JSON.parse(await runtime.run(brief('second')));
  const foreign = harness();
  assert.match(await foreign.runtime.control({ action: 'send', subagent_id: first.subagentId, message: 'intrude' }), /not owned/);
  assert.match(await children[0].options.toolContext.subagentControl({ action: 'send', subagent_id: second.subagentId, message: 'intrude' }), /only send messages to their parent/);
  assert.match(await runtime.control({ action: 'send', subagent_id: first.subagentId, message: ' ' }), /nonempty/);
  const cancelled = JSON.parse(await runtime.control({ action: 'cancel', subagent_id: second.subagentId }));
  assert.equal(cancelled.status, 'cancelled');
  assert.match(await runtime.control({ action: 'send', subagent_id: second.subagentId, message: 'late' }), /finished/);
  children[0].finish('done');
  await runtime.control({ action: 'wait', subagent_id: first.subagentId });
  await tick();
  assert.equal(children.length, 1);
});

test('mailboxes enforce byte and queue limits without losing accepted messages; waits and cancellation stay scoped', async () => {
  const { SUBAGENT_INBOX_LIMIT, SUBAGENT_MESSAGE_BYTES } = await import('../../src/core/subagents/registry.mjs');
  const { runtime, children } = harness();
  const child = JSON.parse(await runtime.run(brief('bounded')));
  assert.equal(JSON.parse(await runtime.control({ action: 'list' }))[0].subagentId, child.subagentId);
  assert.equal(JSON.parse(await runtime.control({ action: 'wait', subagent_id: child.subagentId, wait_ms: 0 })).status, 'running');
  assert.match(await runtime.control({ action: 'send', subagent_id: child.subagentId, message: '😀'.repeat(SUBAGENT_MESSAGE_BYTES) }), /exceeds/);
  for (let index = 0; index < SUBAGENT_INBOX_LIMIT; index++) {
    assert.equal(JSON.parse(await runtime.control({ action: 'send', subagent_id: child.subagentId, message: `message-${index}` })).status, 'queued');
  }
  assert.match(await runtime.control({ action: 'send', subagent_id: child.subagentId, message: 'overflow' }), /full/);
  assert.equal(children[0].options.toolContext.takeSubagentMessages().length, SUBAGENT_INBOX_LIMIT);
  assert.match(await runtime.control({ action: 'unknown', subagent_id: child.subagentId }), /action must/);
  assert.equal(JSON.parse(await runtime.control({ action: 'cancel', subagent_id: child.subagentId })).status, 'cancelled');
  assert.equal(JSON.parse(await runtime.control({ action: 'list' }))[0].status, 'cancelled');
});

test('real HTTP streams run two children concurrently and deliver parent replies before their final decisions', { timeout: 15_000 }, async () => {
  const { Agent } = await import('../../src/core/agent.mjs');
  const events = [];
  const requests = [];
  let childSecondRequests = 0;
  let releaseParent;
  let releaseChildren;
  const childrenReady = new Promise(resolve => { releaseParent = resolve; });
  const directionsReady = new Promise(resolve => { releaseChildren = resolve; });
  const childRounds = new Map();
  const call = (id, name, args) => ({ index: 0, id, type: 'function', function: { name, arguments: JSON.stringify(args) } });
  const reply = (res, content, toolCalls = []) => {
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    res.end(`data: ${JSON.stringify({ choices: [{ index: 0, delta: { content, ...(toolCalls.length ? { tool_calls: toolCalls } : {}) }, finish_reason: toolCalls.length ? 'tool_calls' : 'stop' }] })}\n\ndata: [DONE]\n\n`);
  };
  const serverErrors = [];
  const server = http.createServer(async (req, res) => {
    try {
      let raw = '';
      for await (const chunk of req) raw += chunk;
      const body = JSON.parse(raw);
      requests.push(body);
      const seed = body.messages.find(message => message.role === 'user')?.content;
      if (seed === 'child-a' || seed === 'child-b') {
        const round = (childRounds.get(seed) || 0) + 1;
        childRounds.set(seed, round);
        assert.ok(body.tools.some(tool => tool.function.name === 'subagent_control'));
        assert.ok(!body.tools.some(tool => tool.function.name === 'delegate_task'));
        if (round === 1) return reply(res, '', [call(`${seed}-question`, 'subagent_control', { action: 'send', subagent_id: 'parent', message: `${seed} asks for direction` })]);
        if (round === 2) {
          if (++childSecondRequests === 2) releaseParent();
          await directionsReady;
          return reply(res, '', [call(`${seed}-check`, 'subagent_control', { action: 'send', subagent_id: 'parent', message: `${seed} checking inbox` })]);
        }
        assert.ok(body.messages.some(message => String(message.content).includes(`direction for ${seed}`)), `${seed} receives a message sent during its HTTP request`);
        return reply(res, `${seed} finished with direction`);
      }
      const receipts = body.messages.filter(message => message.role === 'tool').flatMap(message => {
        try { const item = JSON.parse(message.content); return item.subagentType ? [item] : []; } catch { return []; }
      });
      if (!receipts.length) return reply(res, '', ['child-a', 'child-b'].map((name, index) => ({
        ...call(`spawn-${name}`, 'delegate_task', brief(name)), index,
      })));
      const alreadySent = body.messages.some(message => message.role === 'assistant' && message.tool_calls?.some(tool => tool.function.name === 'subagent_control'));
      if (!alreadySent) {
        await childrenReady;
        return reply(res, '', receipts.map((receipt, index) => ({
          ...call(`direction-${index}`, 'subagent_control', { action: 'send', subagent_id: receipt.subagentId, message: `direction for ${receipt.description}` }), index,
        })));
      }
      return reply(res, receipts.every(receipt => receipt.status === 'completed') ? 'Both children finished.' : 'Premature draft');
    } catch (error) {
      serverErrors.push(error);
      res.writeHead(500);
      res.end(error.message);
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  const output = [];
  const agent = new Agent({
    client: { baseUrl: `http://127.0.0.1:${address.port}`, model: 'scripted-messaging', headers: () => ({ 'Content-Type': 'application/json' }) },
    config: { tools: true, autoApprove: true, memoryConsolidation: false, maxToolSteps: 20, historyMessages: 100,
      contextWindow: 256_000, contextWindowExplicit: true },
    memoryEnabled: false, skillsEnabled: false, workspacePath: sandbox, print: () => {}, write: () => {},
    onSubagentEvent(event) {
      events.push(event);
      if (events.filter(item => item.type === 'subagent-message' && item.from === 'parent').length === 2) releaseChildren();
    },
  });
  agent.state.activatedTools.add('delegate_task');
  agent.state.activatedTools.add('subagent_control');
  try {
    assert.equal(await agent.send('Coordinate both tasks', { onDelta: text => output.push(text) }), 'Both children finished.', JSON.stringify(events.filter(item => item.type === 'subagent-end')));
    assert.equal(childSecondRequests, 2, 'both HTTP child requests overlapped before parent guidance');
    assert.deepEqual(serverErrors, []);
    assert.equal(events.filter(item => item.type === 'subagent-message').length, 6);
    assert.equal(events.filter(item => item.type === 'subagent-end' && item.status === 'completed').length, 2);
    assert.equal(output.join(''), 'Both children finished.', 'unfinished parent drafts stay hidden');
    assert.ok(!agent.messages.some(message => message.role === 'assistant' && message.content === 'Premature draft'), 'unfinished drafts must stay out of saved chat history');
    assert.ok(requests.length >= 9);
    assert.ok(!agent._subagents.hasPending());
    console.log(`MESSAGING_HTTP_OK children=${childRounds.size} messages=6 requests=${requests.length} pending=0`);
  } finally {
    await agent.cancel();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
});

test('the real CLI prints both message directions and waits for its background child', { timeout: 15_000 }, async t => {
  const directory = fs.mkdtempSync(path.join(sandbox, 'cli-messaging-'));
  const serverErrors = [];
  const finalAnswer = 'CLI parent finished after child.';
  const childAnswer = 'CLI child finished after guidance.';
  const guidance = 'Use the CLI guidance.';
  const childPrompt = 'cli-child-task';
  const requests = [];
  let childFinished = false;
  let parentDrafts = 0;
  let releaseChild;
  const parentDraftReady = new Promise(resolve => { releaseChild = resolve; });
  const call = (id, name, args) => ({ id, type: 'function', function: { name, arguments: JSON.stringify(args) } });
  const server = http.createServer(async (req, res) => {
    res.setHeader('Content-Type', 'application/json');
    if (req.url.endsWith('/models')) {
      res.end(JSON.stringify({ data: [{ id: 'cli-messaging-model', context_length: 256_000, supported_parameters: ['tools'] }] }));
      return;
    }
    try {
      let raw = '';
      for await (const chunk of req) raw += chunk;
      const body = JSON.parse(raw);
      requests.push(body);
      const reply = (content, tool) => res.end(JSON.stringify({ choices: [{ message: { role: 'assistant', content,
        ...(tool ? { tool_calls: [tool] } : {}) }, finish_reason: tool ? 'tool_calls' : 'stop' }] }));
      const tools = body.messages.filter(message => message.role === 'tool');
      if (body.messages.find(message => message.role === 'user')?.content === childPrompt) {
        if (!tools.length) return reply('', call('cli-question', 'subagent_control', { action: 'send', subagent_id: 'parent', message: 'CLI child asks for guidance.' }));
        if (!body.messages.some(message => String(message.content).includes(guidance))) {
          return reply('', call('cli-progress', 'subagent_control', { action: 'send', subagent_id: 'parent', message: 'CLI child checking guidance.' }));
        }
        // The parent must hold its tool-free draft until this response finishes.
        await parentDraftReady;
        childFinished = true;
        return reply(childAnswer);
      }
      if (!tools.length) return reply('', call('cli-discovery', 'find_tools', { query: 'subagents' }));
      const receipt = tools.flatMap(message => {
        try { const item = JSON.parse(message.content); return item.subagentType ? [item] : []; } catch { return []; }
      })[0];
      if (!receipt) return reply('', call('cli-spawn', 'delegate_task', { ...brief('CLI child'), prompt: childPrompt }));
      const sent = body.messages.some(message => message.role === 'assistant' && message.tool_calls?.some(tool => tool.function.name === 'subagent_control'));
      if (!sent) return reply('', call('cli-guidance', 'subagent_control', { action: 'send', subagent_id: receipt.subagentId, message: guidance }));
      if (receipt.status !== 'completed') {
        parentDrafts++;
        reply('CLI unfinished draft');
        releaseChild();
        return;
      }
      assert.equal(childFinished, true);
      assert.equal(receipt.result, childAnswer);
      return reply(finalAnswer);
    } catch (error) {
      serverErrors.push(error.message);
      res.statusCode = 500;
      res.end(JSON.stringify({ error: { message: error.message } }));
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const child = spawn(process.execPath, [fileURLToPath(new URL('../../chat.mjs', import.meta.url)),
    '--prompt', 'Coordinate the CLI child', '--plain', '--no-banner', '--yes'], {
    cwd: directory,
    env: { ...process.env, CONFIG_DIR: path.join(directory, 'config'), PROVIDER: 'kilo', MODEL: 'cli-messaging-model',
      API_BASE: `http://127.0.0.1:${server.address().port}/v1`, API_KEY: 'fixture-only-key',
      TOOL_PROVIDER: '', TOOL_MODEL: '', TOOL_API_BASE: '', TOOL_API_KEY: '', CONTEXT_WINDOW: '256000',
      MEMORY_CONSOLIDATION: 'off', EMBEDDINGS: 'off', PROJECT_AUTO_DETECT: 'off', PROJECT_WORK_CAPTURE: 'off',
      PROJECT_AUTO_MAINTENANCE: 'off', SUBAGENTS_ENABLED: 'on', TOOLS: 'on', SPEAK: 'off',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  let stdout = '';
  let stderr = '';
  child.stdout.on('data', chunk => { stdout += chunk; });
  child.stderr.on('data', chunk => { stderr += chunk; });
  t.after(async () => {
    if (child.exitCode === null) child.kill();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  });
  const exitCode = await new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('close', resolve);
  });
  assert.equal(exitCode, 0, `${stdout}\n${stderr}`);
  assert.deepEqual(serverErrors, []);
  assert.match(stdout, /Parent to agent.*Use the CLI guidance/);
  assert.match(stdout, /Agent to parent.*CLI child asks for guidance/);
  assert.match(stdout, /CLI parent finished after child/);
  assert.ok(!stdout.includes('CLI unfinished draft'));
  assert.ok(parentDrafts > 0, 'the real CLI reached a final proposal while its child was still active');
  assert.equal(childFinished, true);
  console.log(`MESSAGING_CLI_OK directions=2 waited=1 requests=${requests.length} exit=${exitCode}`);
});
