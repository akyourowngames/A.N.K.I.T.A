import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { TeammateStore } from '../desktop/electron/teammates.mjs';
import { ApprovalRegistry } from '../desktop/electron/approvals.mjs';
import { createSession } from '../src/bootstrap.mjs';
import { DesktopEngine } from '../desktop/electron/engine.mjs';

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
    teammateFile: file, sessionsDir: directory, AgentClass: FakeAgent,
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
    teammateFile: file, sessionsDir: directory, AgentClass: FakeAgent,
    bootstrap: async () => ({ client: {}, tool: null, models: [{ id: 'fast', tools: true }], model: 'fast', provider: { name: 'test' } }),
    config: { provider: 'test', tools: true, model: '', memoryConsolidation: false },
    mcp: { reconcile: async () => {}, ensureComposio: async () => {}, summaries: () => [], closeAll: async () => {} },
  });
  await restored.init();
  assert.equal(restored.loadThread(threadId).at(-1).content, 'Hello there');
});
