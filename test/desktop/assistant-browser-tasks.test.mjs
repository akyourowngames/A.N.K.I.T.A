import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DesktopEngine } from '../../desktop/electron/engine.mjs';
import { CHATGPT_BROWSER_PROVIDER } from '../../desktop/shared/chatgpt-browser.mjs';
import { ChatGptRuntime } from '../../src/integrations/chatgpt-browser/runtime.mjs';
import { BrowserOperationStore } from '../../src/integrations/chatgpt-browser/operation-store.mjs';
import { BrowserDelivery } from '../../src/integrations/chatgpt-browser/delivery.mjs';
import { AssistantTaskStore } from '../../src/assistant/tasks.mjs';
import { randomUUID } from 'node:crypto';

function fixture(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-browser-task-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const events = [], browser = { kind: CHATGPT_BROWSER_PROVIDER, init: async () => {}, listModels: () => [],
    view: () => ({ status: 'ready' }), close: async () => {}, cancel: async () => true, consume: async () => {} };
  const file = name => path.join(directory, name);
  const engine = new DesktopEngine({ teammateFile: file('teammates.json'), settingsFile: file('settings.json'), channelsFile: file('channels.json'),
    sessionsDir: file('sessions'), projectsFile: file('projects.json'), composioFile: file('composio.json'), composioGrantsFile: file('grants.json'),
    credentialFile: file('vault.json'), browserFile: file('browser.json'), config: { provider: CHATGPT_BROWSER_PROVIDER, tools: true },
    chatgptFactory: () => browser, mcp: { connectedIds: [], reconcile: async () => {}, closeAll: async () => {} },
    bootstrap: async () => { throw new Error('Browser task must not bootstrap an API.'); },
    AgentClass: class { constructor() { throw new Error('Browser task must not construct an Agent.'); } }, emit: event => events.push(event) });
  t.after(() => engine.close());
  return { engine, browser, events, directory };
}
const nextTurn = () => new Promise(resolve => setImmediate(resolve));

test('browser Send checkpoints original goal/context and native queue identity before waiting for completion', async t => {
  const { engine, browser } = fixture(t); await engine.init();
  const teammate = engine.createTeammate({ name: 'Browser task owner' }), context = engine.browserContext(teammate.id);
  let queued, release;
  const admitted = new Promise(resolve => { queued = resolve; });
  browser.send = async input => {
    await input.onQueued({ id: 'native-queued-operation' }); queued();
    return new Promise(resolve => { release = resolve; });
  };
  await engine.send(teammate.id, 'Explain the selected reference', [{ name: 'Reference.txt', text: 'A reviewed request reference.' }], { surface: 'phone' });
  await admitted;
  const task = engine.assistant().tasks.list({ ownerId: teammate.id })[0];
  try {
    assert.ok(task, 'browser requests need a durable task before native completion');
    assert.equal(task.status, 'running'); assert.equal(task.goal, 'Explain the selected reference');
    assert.equal(task.surface, 'phone'); assert.equal(task.workspacePath, context.workspacePath);
    assert.equal(task.context.references[0].excerpt, 'A reviewed request reference.');
    assert.equal(task.browserOperationId, 'native-queued-operation'); assert.equal(task.provider, CHATGPT_BROWSER_PROVIDER);
  } finally { release({ outcome: 'completed', operationId: 'native-queued-operation', text: 'Observed explanation.' }); await engine.waitForTurn(teammate.id); }
  assert.equal(engine.assistant().tasks.get(task.id).status, 'completed');
});

test('browser native actions save requested approval separately from actual execution and settled evidence', async t => {
  const { engine, browser } = fixture(t); await engine.init();
  const teammate = engine.createTeammate({ name: 'Approval task owner' }), context = engine.browserContext(teammate.id);
  let reached, release;
  const admitted = new Promise(resolve => { reached = resolve; });
  browser.send = async input => { await input.onQueued({ id: 'approval-native-operation' }); reached(); return new Promise(resolve => { release = resolve; }); };
  await engine.send(teammate.id, 'Write the approved note'); await admitted;
  const host = engine.toolHostForBrowser({ ...context, leaseId: 'task-lease' });
  const writing = host.execute({ id: 'write-approved-note', name: 'write_file', arguments: { path: 'note.txt', content: 'Approved note bytes.' } }, { surface: 'core' });
  for (let attempt = 0; attempt < 30 && !engine.listApprovals().length; attempt++) await nextTurn();
  try {
    const task = engine.assistant().tasks.list({ ownerId: teammate.id })[0];
    assert.equal(task.steps[0].phase, 'requested'); assert.equal(task.steps[0].startedAt, null);
    assert.equal(fs.existsSync(path.join(context.workspacePath, 'note.txt')), false);
    engine.respondApproval(engine.listApprovals()[0].requestId, 'yes');
    assert.equal((await writing).isError, false);
    const settled = engine.assistant().tasks.get(task.id).steps[0];
    assert.equal(settled.phase, 'settled'); assert.ok(settled.startedAt); assert.ok(settled.result);
    assert.equal(fs.readFileSync(path.join(context.workspacePath, 'note.txt'), 'utf8'), 'Approved note bytes.');
  } finally {
    for (const approval of engine.listApprovals()) engine.respondApproval(approval.requestId, 'no');
    await writing; release({ outcome: 'completed', operationId: 'approval-native-operation', text: 'The approved note was saved.' }); await engine.waitForTurn(teammate.id);
  }
});

test('browser recovery continues only its saved native operation and preserves original task and receipts', async t => {
  const { engine, browser } = fixture(t); await engine.init();
  const teammate = engine.createTeammate({ name: 'Recovery task owner' }), context = engine.browserContext(teammate.id);
  let sends = 0, resumes = 0;
  engine.config.autoApprove = true;
  const write = { id: 'first-write', name: 'write_file', arguments: { path: 'receipt.txt', content: 'Exactly one write.' } };
  browser.send = async input => {
    sends++; await input.onQueued({ id: 'interrupted-native-operation' });
    assert.equal((await engine.toolHostForBrowser({ ...context, leaseId: 'original-task-lease' }).execute(write, { surface: 'core' })).isError, false);
    throw new Error('Fixture browser disconnected.');
  };
  await engine.send(teammate.id, 'Finish the original request'); await assert.rejects(engine.waitForTurn(teammate.id), /disconnected/);
  const task = engine.assistant().tasks.list({ ownerId: teammate.id })[0];
  assert.ok(task, 'failed browser turns retain their original task');
  assert.equal(task.status, 'interrupted');
  browser.operation = async () => ({ id: task.browserOperationId, text: 'Native prompt with app mentions', binding: context });
  browser.resume = async input => {
    resumes++; assert.equal(input.operationId, task.browserOperationId);
    const repeated = await engine.toolHostForBrowser({ ...context, leaseId: 'restored-task-lease' }).execute({ ...write, id: 'repeated-write' }, { surface: 'core' });
    assert.equal(repeated.isError, true); assert.match(repeated.content[0].text, /already completed/);
    return { outcome: 'completed', operationId: task.browserOperationId, text: 'Saved native final receipt.' };
  };
  await engine.resumeBrowser(teammate.id, task.browserOperationId, { assistantTaskId: task.id }); await engine.waitForTurn(teammate.id);
  const finished = engine.assistant().tasks.get(task.id);
  assert.equal(sends, 1); assert.equal(resumes, 1); assert.equal(finished.attempt, 2);
  assert.equal(finished.goal, 'Finish the original request'); assert.equal(finished.status, 'completed');
  assert.equal(finished.steps.filter(step => step.phase === 'settled' && step.mutation).length, 1);
  assert.equal(fs.readFileSync(path.join(context.workspacePath, 'receipt.txt'), 'utf8'), 'Exactly one write.');
  await engine.resumeBrowser(teammate.id, task.browserOperationId, { assistantTaskId: task.id });
  assert.equal(resumes, 1); assert.equal(engine.assistant().tasks.list({ ownerId: teammate.id }).length, 1);
});

test('resuming native work restores its checkpointed checklist to a fresh tool lease', async t => {
  const { engine, browser } = fixture(t); await engine.init();
  const owner = engine.createTeammate({ name: 'Checklist owner' }), context = engine.browserContext(owner.id);
  browser.send = async input => {
    await input.onQueued({ id: 'checklist-native-operation' });
    const planned = await engine.toolHostForBrowser({ ...context, leaseId: 'prior-checklist-lease' }).execute({ id: 'plan', name: 'write_todos',
      arguments: { todos: [{ content: 'Review the original source', status: 'pending' }] } }, { surface: 'core' });
    assert.equal(planned.isError, false); throw new Error('Fixture interrupted.');
  };
  await engine.send(owner.id, 'Review the original source'); await assert.rejects(engine.waitForTurn(owner.id), /interrupted/);
  const task = engine.assistant().tasks.list({ ownerId: owner.id })[0]; assert.equal(task.checklist.length, 1);
  engine.browserToolStates.clear();
  browser.operation = async () => ({ id: task.browserOperationId, text: task.goal, binding: context });
  browser.resume = async () => {
    const updated = await engine.toolHostForBrowser({ ...context, leaseId: 'fresh-checklist-lease' }).execute({ id: 'complete-plan', name: 'write_todos',
      arguments: { updates: [{ id: task.checklist[0].id, status: 'completed' }] } }, { surface: 'core' });
    assert.equal(updated.isError, false, updated.content[0].text);
    return { outcome: 'completed', operationId: task.browserOperationId, text: 'Original source reviewed.' };
  };
  await engine.resumeBrowser(owner.id, task.browserOperationId); await engine.waitForTurn(owner.id);
  assert.equal(engine.assistant().tasks.get(task.id).status, 'completed');
});

test('browser task recovery refuses operation substitution and conversation substitution before native resume', async t => {
  const { engine, browser } = fixture(t); await engine.init();
  const owner = engine.createTeammate({ name: 'Original owner' }), other = engine.createTeammate({ name: 'Other owner' });
  const context = engine.browserContext(owner.id);
  browser.send = async input => { await input.onQueued({ id: 'owned-native-operation' }); throw new Error('Fixture interrupted.'); };
  await engine.send(owner.id, 'Original goal'); await assert.rejects(engine.waitForTurn(owner.id), /interrupted/);
  const task = engine.assistant().tasks.list({ ownerId: owner.id })[0];
  assert.ok(task);
  browser.operation = async id => ({ id, text: 'Original goal', binding: context });
  browser.resume = async () => { throw new Error('Must not reach native resume.'); };
  await assert.rejects(engine.resumeBrowser(owner.id, 'substituted-operation', { assistantTaskId: task.id }), /operation|saved/i);
  await assert.rejects(engine.resumeBrowser(other.id, task.browserOperationId, { assistantTaskId: task.id }), /owner|another|conversation/i);
  assert.equal(engine.assistant().tasks.get(task.id).attempt, 1);
});

test('a saved task cannot be sent through browser Send as a replacement native request', async t => {
  const { engine, browser } = fixture(t); await engine.init();
  const owner = engine.createTeammate({ name: 'Saved work owner' });
  const task = engine.assistant().tasks.create({ ownerId: owner.id, goal: 'Existing saved request' });
  engine.assistant().tasks.finish(task.id, { status: 'interrupted' });
  browser.send = async () => { throw new Error('Must not send replacement native request.'); };
  await assert.rejects(engine.sendBrowser(owner.id, 'Continue saved work', null, { assistantTaskId: task.id }), /native|operation|resume/i);
  assert.equal(engine.assistant().tasks.get(task.id).status, 'interrupted');
});

test('Today continuation reloads durable native state and observes its final receipt without a second native Send', async t => {
  const { engine, browser, directory } = fixture(t); await engine.init();
  const owner = engine.createTeammate({ name: 'Durable runtime owner' }), context = engine.browserContext(owner.id);
  const binding = { ...context, browserId: 'durable-browser', tabId: 1, leaseId: 'durable-lease', epoch: 'durable-epoch', conversationId: randomUUID() };
  const operationDirectory = path.join(directory, 'native-operations');
  const bridge = { view: () => ({ status: 'ready', binding, models: [], selectedModel: null }) };
  let runtime, delivery, store, queued, nativeSends = 0;
  const ready = new Promise(resolve => { queued = resolve; });
  const restoreRuntime = () => {
    store = new BrowserOperationStore({ directory: operationDirectory });
    delivery = new BrowserDelivery({ store, onEvent: event => runtime.deliveryEvent(event) });
    runtime = new ChatGptRuntime({ store, delivery, bridge });
    browser.operation = id => store.get(id); browser.resume = input => runtime.resume(input);
    browser.consume = id => store.consume(id, binding);
  };
  restoreRuntime();
  browser.send = input => { nativeSends++; return runtime.send({ ...input, onQueued: async operation => { await input.onQueued(operation); queued(operation); } }); };
  await engine.send(owner.id, 'Observe the original native result');
  const firstTurn = engine.waitForTurn(owner.id); void firstTurn.catch(() => {});
  const operation = await ready;
  await delivery.poll(binding); await delivery.authorize(operation.id, binding, { baselineUserIds: [] });
  await delivery.fail(operation.id, binding, 'fixture transport lost');
  await assert.rejects(firstTurn, /may have been sent/);
  const original = engine.assistant().tasks.list({ ownerId: owner.id })[0]; assert.equal(original.status, 'interrupted');
  engine.assistant().tasks = new AssistantTaskStore({ directory: engine.assistant().tasks.directory });
  restoreRuntime(); await runtime.restore();
  await engine.assistant().resume({ id: owner.id, taskId: original.id }); await nextTurn();
  const receipt = { conversationId: binding.conversationId, userMessageId: randomUUID(), turnId: randomUUID() };
  await delivery.receipt(operation.id, binding, receipt);
  await delivery.observe(operation.id, binding, { ...receipt, assistantMessageId: randomUUID(), role: 'assistant', channel: 'final',
    end_turn: true, status: 'finished_successfully', text: 'Observed original native final.' });
  await engine.waitForTurn(owner.id);
  assert.equal(nativeSends, 1); assert.equal((await store.list(binding)).length, 1);
  assert.equal(engine.assistant().tasks.get(original.id).status, 'completed');
  assert.equal(engine.loadThread(owner.id).at(-1).content, 'Observed original native final.');
  console.log('BROWSER_TASK_RECOVERY_PROOF', JSON.stringify({ durableReload: true, todayResume: true, nativeSends, nativeOperations: 1, hostedChatGpt: false }));
});
