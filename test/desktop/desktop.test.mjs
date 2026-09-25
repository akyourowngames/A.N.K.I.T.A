import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { TeammateStore } from '../../desktop/electron/teammates.mjs';
import { ApprovalRegistry } from '../../desktop/electron/approvals.mjs';
import { createSession } from '../../src/core/bootstrap.mjs';
import { DesktopEngine } from '../../desktop/electron/engine.mjs';
import { todoProgress } from '../../desktop/shared/todo-progress.mjs';
import { run as writeTodos } from '../../tools/project/write-todos.mjs';

function temporaryStore(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-desktop-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return path.join(dir, 'teammates.json');
}

test('first desktop launch seeds Chief and New agent, then persists teammate changes', t => {
  const file = temporaryStore(t);
  const one = new TeammateStore(file).load();
  assert.deepEqual(one.list().map(item => item.name), ['Chief', 'New agent']);
  const created = one.create({ name: 'Research', color: '#779bbb', persona: 'Find evidence.' });
  assert.equal(created.name, 'Research');
  const two = new TeammateStore(file).load();
  assert.equal(two.find(created.id).persona, 'Find evidence.');
  two.update(created.id, { name: 'Research desk' });
  two.touch(created.id, 'A useful answer from the model');
  assert.equal(new TeammateStore(file).load().find(created.id).lastMessage, 'A useful answer from the model');
  assert.equal(one.delete(created.id), true);
  assert.equal(new TeammateStore(file).load().find(created.id), null);
});

test('teammate writes re-read the file so separate processes do not lose additions', t => {
  const file = temporaryStore(t);
  const first = new TeammateStore(file).load();
  const second = new TeammateStore(file).load();
  first.create({ name: 'One' });
  second.create({ name: 'Two' });
  assert.deepEqual(new TeammateStore(file).load().list().slice(-2).map(item => item.name), ['One', 'Two']);
});

test('approvals settle once and cancellation denies a pending prompt', async () => {
  const requested = [];
  const approvals = new ApprovalRegistry(event => requested.push(event));
  const answer = approvals.request('chief', 'write_file', 'Create a file');
  assert.equal(requested[0].toolName, 'write_file');
  assert.equal(approvals.respond(requested[0].requestId, 'yes'), true);
  assert.equal(await answer, true);
  assert.equal(approvals.respond(requested[0].requestId, 'no'), false);
  const pending = approvals.request('chief', 'delete_file', 'Delete a file');
  approvals.cancelThread('chief');
  assert.equal(await pending, false);
});

test('desktop bootstrap resolves a configured compatible model without GitHub login', async () => {
  let constructed = null;
  class Client {
    constructor(options) { constructed = options; }
    async models() { return [{ id: 'fast', tools: true, context: 64000, default: true }]; }
  }
  const config = { provider: 'kilo', apiBase: '', apiKey: '', model: '', tools: true, contextWindow: 32768 };
  const session = await createSession({ config, CompatibleClientClass: Client });
  assert.equal(session.model, 'fast');
  assert.equal(config.apiBase, 'https://api.kilo.ai/api/gateway');
  assert.equal(constructed.contextWindow, 32768);
  assert.equal(config.contextWindow, 64000);
});

test('desktop skill toggles update live chats and survive restart', async t => {
  const file = temporaryStore(t);
  const directory = path.dirname(file);
  const options = {
    teammateFile: file, settingsFile: path.join(directory, 'settings.json'), sessionsDir: directory, channelsFile: path.join(directory, 'channels.json'),
    bootstrap: async () => ({ client: {}, tool: null, models: [{ id: 'fast', tools: true }], model: 'fast', provider: { name: 'test' } }),
    config: { provider: 'test', tools: true, model: '', memoryConsolidation: false },
    mcp: { reconcile: async () => {}, ensureComposio: async () => {}, summaries: () => [], alwaysOnIds: () => [], specs: () => [], has: () => false, closeAll: async () => {} },
  };
  const engine = new DesktopEngine(options);
  await engine.init();
  const agent = engine.agentFor(engine.listTeammates()[0].id);
  assert.match(agent.messages[0].content, /ankita-dev:.*Use when/);
  assert.ok(agent.currentSpecs().some(spec => spec.function.name === 'skill'));
  assert.match(await agent.runToolCall({ function: { name: 'skill', arguments: '{"name":"commit-review"}' } }), /# Skill: commit-review/);
  assert.deepEqual(engine.listSkills().map(skill => skill.name), ['ankita-dev', 'commit-review']);
  engine.setSkillEnabled('commit-review', false);
  assert.equal(engine.listSkills().find(skill => skill.name === 'commit-review').enabled, false);
  assert.doesNotMatch(agent.messages[0].content, /commit-review:/);
  assert.match(await agent.runToolCall({ function: { name: 'skill', arguments: '{"name":"commit-review"}' } }), /disabled in Plugins > Skills/);
  engine.setSkillEnabled('ankita-dev', false);
  assert.ok(!agent.currentSpecs().some(spec => spec.function.name === 'skill'));
  const restored = new DesktopEngine(options);
  await restored.init();
  assert.deepEqual(restored.listSkills().map(skill => skill.enabled), [false, false]);
  restored.setSkillEnabled('commit-review', true);
  assert.deepEqual(restored.listSkills().map(skill => skill.enabled), [false, true]);
  assert.match(restored.agentFor(restored.listTeammates()[0].id).messages[0].content, /commit-review:/);
});

test('desktop engine streams a turn, persists the thread, and restores it', async t => {
  const file = temporaryStore(t);
  const directory = path.dirname(file);
  const events = [];
  class FakeAgent {
    constructor() { this.messages = [{ role: 'system', content: 'system' }]; this.autoApprove = false; this.model = null; }
    async send(text, callbacks) {
      this.messages.push({ role: 'user', content: text });
      callbacks.onMessageStart();
      callbacks.onDelta('Hello ');
      callbacks.onDelta('there');
      callbacks.onMessageEnd();
      this.messages.push({ role: 'assistant', content: 'Hello there' });
      return 'Hello there';
    }
    cancel() { return true; }
  }
  const engine = new DesktopEngine({
    teammateFile: file, sessionsDir: directory, channelsFile: path.join(directory, 'channels.json'), AgentClass: FakeAgent,
    bootstrap: async () => ({ client: {}, tool: null, models: [{ id: 'fast', tools: true }], model: 'fast', provider: { name: 'test' } }),
    emit: event => events.push(event),
    config: { provider: 'test', tools: true, model: '', memoryConsolidation: false },
    mcp: { reconcile: async () => {}, ensureComposio: async () => {}, summaries: () => [], closeAll: async () => {} },
  });
  await engine.init();
  const threadId = engine.listTeammates()[0].id;
  const { turnId } = await engine.send(threadId, 'Hi');
  assert.ok(turnId);
  await engine.waitForTurn(threadId);
  assert.equal(events.filter(e => e.type === 'assistant-delta').map(e => e.text).join(''), 'Hello there');
  assert.deepEqual(engine.loadThread(threadId).map(m => m.role), ['user', 'assistant']);
  const restored = new DesktopEngine({
    teammateFile: file, sessionsDir: directory, channelsFile: path.join(directory, 'channels.json'), AgentClass: FakeAgent,
    bootstrap: async () => ({ client: {}, tool: null, models: [{ id: 'fast', tools: true }], model: 'fast', provider: { name: 'test' } }),
    config: { provider: 'test', tools: true, model: '', memoryConsolidation: false },
    mcp: { reconcile: async () => {}, ensureComposio: async () => {}, summaries: () => [], closeAll: async () => {} },
  });
  await restored.init();
  assert.equal(restored.loadThread(threadId).at(-1).content, 'Hello there');
});

test('desktop restores a trimmed checklist for display and later status updates', async t => {
  const file = temporaryStore(t);
  const directory = path.dirname(file);
  class TodoAgent {
    constructor() {
      this.messages = [{ role: 'system', content: 'system' }];
      this.state = { todos: [] };
      this.model = 'fast';
    }
    async send(text, callbacks) {
      const args = { todos: [{ content: 'Review files', activeForm: 'Reviewing files', status: 'in_progress' }] };
      const call = { id: 'plan-1', type: 'function', function: { name: 'write_todos', arguments: JSON.stringify(args) } };
      this.messages.push({ role: 'user', content: text });
      callbacks.onToolCall(call);
      const result = writeTodos(args, this);
      callbacks.onToolResult(call, result);
      this.messages.push({ role: 'assistant', content: null, tool_calls: [call] }, { role: 'tool', tool_call_id: call.id, content: result });
      // The agent's context window may trim the tool exchange before autosave.
      this.messages.splice(-2, 2);
      this.messages.push({ role: 'assistant', content: 'Review complete' });
      return 'Review complete';
    }
    clear() { this.messages = [{ role: 'system', content: 'system' }]; }
  }
  const options = {
    teammateFile: file, sessionsDir: directory, channelsFile: path.join(directory, 'channels.json'), AgentClass: TodoAgent,
    bootstrap: async () => ({ client: {}, tool: null, models: [{ id: 'fast', tools: true }], model: 'fast', provider: { name: 'test' } }),
    config: { provider: 'test', tools: true, model: '', memoryConsolidation: false },
    mcp: { reconcile: async () => {}, ensureComposio: async () => {}, summaries: () => [], closeAll: async () => {} },
  };
  const engine = new DesktopEngine(options);
  await engine.init();
  const id = engine.listTeammates()[0].id;
  await engine.send(id, 'Review the files');
  await engine.waitForTurn(id);
  const restored = new DesktopEngine(options);
  await restored.init();
  assert.deepEqual(todoProgress(restored.loadThread(id)), [
    { id: 's1', content: 'Review files', activeForm: 'Reviewing files', status: 'in_progress' },
  ]);
  const agent = restored.agentFor(id);
  assert.equal(writeTodos({ updates: [{ id: 's1', status: 'completed' }] }, agent), '[x] 1. Review files (s1)');
  restored.clearThread(id);
  assert.deepEqual(agent.state.todos, []);
  assert.deepEqual(todoProgress(restored.loadThread(id)), []);

  // Sessions saved before checklist snapshots can still recover the last tool result.
  const legacyCall = { id: 'legacy-plan', type: 'function', function: {
    name: 'write_todos', arguments: JSON.stringify({ todos: [{ content: 'Review files', status: 'in_progress' }] }),
  } };
  fs.writeFileSync(restored.sessionFile(id), JSON.stringify({ messages: [
    { role: 'user', content: 'Review the files' },
    { role: 'assistant', content: null, tool_calls: [legacyCall] },
    { role: 'tool', tool_call_id: 'legacy-plan', content: '[>] 1. Review files (s1)' },
  ] }));
  const legacy = new DesktopEngine(options);
  await legacy.init();
  assert.equal(legacy.agentFor(id).state.todos[0].id, 's1');
  assert.equal(todoProgress(legacy.loadThread(id))[0].status, 'in_progress');
});
