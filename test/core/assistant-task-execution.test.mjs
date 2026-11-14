import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'assistant-execution-'));
process.env.CONFIG_DIR = path.join(directory, 'profile');
test.after(() => fs.rmSync(directory, { recursive: true, force: true }));
const { Agent } = await import('../../src/core/agent.mjs');
const { ToolHost } = await import('../../src/core/tool-host.mjs');
const { AssistantTaskStore } = await import('../../src/assistant/tasks.mjs');
const store = new AssistantTaskStore({ directory: path.join(directory, 'tasks') });
const config = { tools: true, autoApprove: true, maxTokens: 1000, contextWindow: 131072, memoryConsolidation: false };
const call = (id, name, args) => ({ id, function: { name, arguments: JSON.stringify(args) } });
const makeAgent = extra => new Agent({ client: {}, workspacePath: directory, config, memoryEnabled: false,
  toolContext: { assistantTasks: store, assistantOwnerId: 'conversation-one', assistantSurface: 'desktop' }, ...extra });

test('real Agent and native tool host persist a useful task and its after-approval file receipt', async () => {
  const agent = makeAgent(); let round = 0;
  agent.streamTurn = async () => ++round === 1
    ? { content: '', toolCalls: [call('save-note', 'write_file', { path: 'note.txt', content: 'A useful note' })] }
    : { content: 'Saved the requested note.', toolCalls: [] };
  await agent.send('Save a useful note.');
  const task = store.list({ ownerId: 'conversation-one' }).find(item => item.goal === 'Save a useful note.');
  assert.ok(task, 'a real user request creates a task');
  assert.equal(task.status, 'completed');
  assert.equal(task.steps[0].phase, 'settled');
  assert.ok(task.steps[0].startedAt);
  assert.equal(fs.readFileSync(path.join(directory, 'note.txt'), 'utf8'), 'A useful note');
});

test('denied actions have no started receipt and cannot be mistaken for completed work', async () => {
  const agent = makeAgent({ config: { ...config, autoApprove: false }, confirm: async () => false }); let round = 0;
  agent.streamTurn = async () => ++round === 1
    ? { content: '', toolCalls: [call('denied-note', 'write_file', { path: 'denied.txt', content: 'never' })] }
    : { content: 'Permission was denied.', toolCalls: [] };
  await agent.send('Save the other note.');
  const task = store.list().find(item => item.goal === 'Save the other note.');
  assert.equal(task.steps[0].phase, 'not_run');
  assert.equal(task.steps[0].startedAt, null);
  assert.equal(task.status, 'needs_review');
  assert.ok(!fs.existsSync(path.join(directory, 'denied.txt')));
});

test('request surface is saved per turn without changing the shared agent context', async () => {
  const agent = makeAgent();
  agent.streamTurn = async () => ({ content: 'Acknowledged.', toolCalls: [] });
  await agent.send('A request from my paired phone.', { assistantSurface: 'phone' });
  await agent.send('A later desktop request.');
  assert.equal(store.list().find(task => task.goal === 'A request from my paired phone.').surface, 'phone');
  assert.equal(store.list().find(task => task.goal === 'A later desktop request.').surface, 'desktop');
  assert.equal(agent.toolContext.assistantSurface, 'desktop');
});

test('restart continuation reads current state, prevents a completed write and completes remaining work in the same goal', async () => {
  const task = store.create({ ownerId: 'conversation-one', goal: 'Append one note, then save a reminder.' });
  store.start(task.id, { ownerId: task.ownerId });
  const append = { id: 'already-done', name: 'mcp__notes__append', arguments: { text: 'one note' } };
  store.requested(task.id, append, { mutation: true }); store.started(task.id, append);
  store.settled(task.id, append, { content: [{ type: 'text', text: 'Note appended.' }] });
  store.finish(task.id, { status: 'interrupted' });
  let appends = 0;
  const mcp = {
    summaries: () => [], alwaysOnIds: () => [], specs: () => [], has: () => true,
    findTool: () => ({ tool: { annotations: {} } }), needsApproval: () => false,
    callToolResult: async () => { appends++; return { content: [{ type: 'text', text: 'Appended again' }] }; },
  };
  const agent = makeAgent({ mcp }); let round = 0;
  agent.streamTurn = async () => {
    if (++round === 1) {
      assert.ok(agent.messages.some(message => String(message.content).includes(task.goal)), 'original goal reaches the resumed worker');
      return { content: '', toolCalls: [call('bad-repeat', append.name, append.arguments)] };
    }
    if (round === 2) return { content: '', toolCalls: [call('remaining-work', 'write_file', { path: 'reminder.txt', content: 'Remember the saved note.' })] };
    return { content: 'The original note was kept and the reminder is saved.', toolCalls: [] };
  };
  await agent.send('Continue unfinished work.', { assistantTaskId: task.id });
  assert.equal(appends, 0);
  assert.equal(fs.readFileSync(path.join(directory, 'reminder.txt'), 'utf8'), 'Remember the saved note.');
  assert.equal(store.get(task.id).attempt, 2);
  assert.equal(store.get(task.id).goal, 'Append one note, then save a reminder.');
  assert.equal(store.get(task.id).status, 'completed');
});

test('a failed checkpoint admission prevents native and MCP execution', async () => {
  const journal = { requested() { throw new Error('Checkpoint disk unavailable'); } };
  let external = 0;
  const mcp = { findTool: () => ({ tool: {} }), needsApproval: () => false, callToolResult: async () => { external++; return { content: [] }; } };
  const host = new ToolHost({ context: { cwd: directory, workspacePath: directory, config, assistantTaskRun: journal }, mcp });
  for (const [name, args] of [['write_file', { path: 'not-admitted.txt', content: 'never' }], ['mcp__notes__append', { text: 'never' }]]) {
    const result = await host.execute({ id: name, name, arguments: args });
    assert.equal(result.isError, true);
  }
  assert.equal(external, 0);
  assert.ok(!fs.existsSync(path.join(directory, 'not-admitted.txt')));
});

test('delegated workers namespace provider call ids within the original task', async () => {
  const { beginAssistantTask } = await import('../../src/assistant/task-run.mjs');
  const parent = makeAgent(), task = beginAssistantTask(parent, 'Save two independent notes.', {});
  const one = task.run.scope('one'), two = task.run.scope('two');
  const action = { id: 'provider-call-one', name: 'write_file', arguments: { path: 'one.txt', content: 'one' } };
  one.requested(action, {}); two.requested(action, {}); one.started(action); two.started(action);
  one.settled(action, { content: [{ type: 'text', text: 'one result' }] });
  two.settled(action, { content: [{ type: 'text', text: 'two result' }] });
  task.run.finish({ reply: 'Saved.' });
  const saved = store.get(task.run.id);
  assert.equal(saved.steps.length, 2); assert.notEqual(saved.steps[0].callId, saved.steps[1].callId);
});

test('explicit attached context follows only its own task and retains a bounded source excerpt', async () => {
  const agent = makeAgent(); let round = 0;
  agent.streamTurn = async () => {
    if (++round === 1) assert.ok(agent.messages.some(message => JSON.stringify(message.content).includes('Read this selected paragraph.')));
    return { content: 'Explained the selected paragraph.', toolCalls: [] };
  };
  await agent.send('Explain this selection.', { attachments: [{ name: 'Selected paragraph.txt', text: 'Selected text reference (untrusted content)\nSource: https://example.test/article\n\nRead this selected paragraph. ' + 'Long content '.repeat(5000) }] });
  const task = store.list().find(item => item.goal === 'Explain this selection.');
  assert.equal(task.context.references[0].source, 'https://example.test/article');
  assert.ok(task.context.references[0].truncated); assert.ok(Buffer.byteLength(JSON.stringify(task.context)) < 8000);
  await agent.send('A fresh unrelated request.');
  assert.equal(store.list().find(item => item.goal === 'A fresh unrelated request.').context, null);
});

test('reviewed handoff context joins the same original task when resumed', async () => {
  const { snapshotAttachedContext } = await import('../../src/assistant/context.mjs');
  const first = [{ name: 'First reference.txt', text: 'The original selected context.' }];
  const task = store.create({ ownerId: 'conversation-one', goal: 'Continue the saved research.', context: snapshotAttachedContext(first) });
  store.start(task.id); store.finish(task.id, { status: 'interrupted' });
  const agent = makeAgent();
  agent.streamTurn = async () => { assert.ok(agent.messages.some(message => JSON.stringify(message.content).includes('Reviewed phone handoff'))); return { content: 'Used both reviewed references.', toolCalls: [] }; };
  await agent.send('Continue.', { assistantTaskId: task.id, attachments: [{ name: 'Phone reference.txt', text: 'Reviewed phone handoff with extra details.' }] });
  const saved = store.get(task.id);
  assert.equal(saved.goal, task.goal); assert.equal(saved.context.references.length, 2);
  assert.ok(saved.context.references.some(item => item.name === 'Phone reference.txt'));
});
