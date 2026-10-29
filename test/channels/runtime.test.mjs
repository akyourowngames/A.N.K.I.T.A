import test from 'node:test';
import assert from 'node:assert/strict';
import { ChannelRuntime } from '../../src/channels/core/runtime.mjs';
import { ChannelSurface } from '../../src/channels/core/surface.mjs';
import { ChannelOutbox } from '../../src/channels/core/outbox.mjs';

const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
function fixture({ channel = 'fixture', caps = [], surface, settings = {} } = {}) {
  const sent = [], reactions = [], typings = [];
  const adapter = { manifest: { id: channel, capabilities: caps },
    send: async envelope => { sent.push(structuredClone(envelope)); return { messageId: String(sent.length), parts: [String(sent.length)] }; },
    typing: async ref => { typings.push(ref.chatId); }, react: async (ref, state) => { reactions.push([ref.chatId, state]); },
    start() {}, stop() {}, buttons: async () => {},
  };
  const runtime = new ChannelRuntime({ adapter, surface: surface || new ChannelSurface({ engine: { send: async () => {}, waitForTurn: async () => 'done' } }), outbox: new ChannelOutbox(), getSettings: () => ({ enabled: true, allowedChatIds: '42, 43', teammateId: 'chief', ownerChatId: 'owner-dm', ownerUserId: 'owner', ...settings }) });
  runtime.running = true;
  return { runtime, adapter, sent, reactions, typings };
}
const inbound = (chatId = '42', text = 'hello', messageId = 'message-1') => ({ channel: 'fixture', chatId, messageId, senderId: chatId, text, raw: { isGroup: false } });

test('shared runtime denies unlisted senders and ignores replayed input before any agent call', async () => {
  const calls = [];
  const surface = new ChannelSurface({ engine: { send: async (...args) => calls.push(args), waitForTurn: async () => 'result' } });
  const { runtime } = fixture({ surface });
  await runtime.receive(inbound('stranger')); await runtime.receive(inbound()); await runtime.drain();
  await runtime.receive(inbound()); await runtime.drain();
  assert.equal(calls.length, 1);
  assert.equal(calls[0][3].surface, 'channel');
});

test('a non-typing platform never makes typing requests and progress never leaks arguments', async () => {
  const gate = deferred(); let runtime;
  const surface = new ChannelSurface({ engine: { send: async () => { runtime.handleEngineEvent({ type: 'tool-call', threadId: 'chief', callId: 'c', name: 'write_file', args: { password: 'do-not-send' } }); }, waitForTurn: () => gate.promise } });
  const f = fixture({ caps: ['react'], surface }); runtime = f.runtime;
  await runtime.receive(inbound()); await new Promise(resolve => setImmediate(resolve));
  gate.resolve('saved'); await runtime.drain();
  assert.equal(f.typings.length, 0);
  assert.equal(JSON.stringify(f.sent).includes('do-not-send'), false);
  assert.deepEqual(f.reactions.map(x => x[1]), ['received', 'complete']);
});

test('owner-only approvals reject a group response and a forged button, then accept the matching private owner', async () => {
  const gate = deferred(), answers = [];
  const surface = new ChannelSurface({ engine: { send: async () => {}, waitForTurn: () => gate.promise, respondApproval: (id, answer) => { answers.push([id, answer]); } } });
  const { runtime, sent } = fixture({ surface, settings: { allowedChatIds: '42, owner-dm' } });
  await runtime.receive(inbound()); await new Promise(resolve => setImmediate(resolve));
  runtime.handleEngineEvent({ type: 'approval-request', threadId: 'chief', requestId: 'request-1', toolName: 'write_file', detail: 'save poem' });
  assert.equal(sent.at(-1).chatId, 'owner-dm');
  await runtime.receive({ ...inbound('42', 'y', '2'), raw: { isGroup: true, mentioned: true } });
  await runtime.receive({ ...inbound('owner-dm', 'y', '3'), senderId: 'impostor', raw: { isGroup: false, approvalId: 'request-1' } });
  assert.equal(answers.length, 0);
  await runtime.receive({ ...inbound('owner-dm', 'y', '4'), senderId: 'owner', raw: { isGroup: false, approvalId: 'request-1' } });
  assert.deepEqual(answers, [['request-1', 'yes']]);
  gate.resolve('saved'); await runtime.drain();
});

test('two platforms sharing one target never steal the other platform approval', async () => {
  const gate = deferred(); const answers = [];
  const engine = { send: async () => {}, waitForTurn: () => gate.promise, respondApproval: (id, answer) => answers.push([id, answer]) };
  const surface = new ChannelSurface({ engine });
  const first = fixture({ channel: 'fixture', surface }), second = fixture({ channel: 'another', surface });
  await first.runtime.receive(inbound());
  await second.runtime.receive({ ...inbound('43'), channel: 'another' });
  await new Promise(resolve => setImmediate(resolve));
  const event = { type: 'approval-request', threadId: 'chief', requestId: 'only-first', toolName: 'run_command', detail: 'action' };
  first.runtime.handleEngineEvent(event); second.runtime.handleEngineEvent(event);
  assert.equal(first.sent.filter(e => e.intent === 'approval').length, 1);
  assert.equal(second.sent.filter(e => e.intent === 'approval').length, 0);
  await first.runtime.receive({ ...inbound('owner-dm', 'n', '5'), senderId: 'owner' });
  gate.resolve('done'); await Promise.all([first.runtime.drain(), second.runtime.drain()]);
  assert.deepEqual(answers, [['only-first', 'no']]);
});

test('cancel bypasses queued work and suppresses final success without cancelling another conversation', async () => {
  const gate = deferred(); let cancelled = 0;
  const surface = new ChannelSurface({ engine: { send: async () => {}, waitForTurn: () => gate.promise, cancel: () => { cancelled++; gate.resolve('do not send success'); } } });
  const { runtime, sent } = fixture({ surface });
  await runtime.receive(inbound()); await new Promise(resolve => setImmediate(resolve));
  await runtime.receive(inbound('42', '/cancel', 'cancel-message')); await runtime.drain();
  assert.equal(cancelled, 1);
  assert.equal(sent.some(e => e.parts?.includes('do not send success')), false);
  assert.equal(sent.some(e => /Stopped/.test(e.parts?.join(''))), true);
});

test('waiting for a desktop turn does not change its tool budget or claim its events', async () => {
  const gate = deferred(), agent = { config: { maxToolCalls: 60 } };
  let busy = true;
  const engine = { agents: new Map([['chief', agent]]), turns: new Map([['chief', gate.promise]]),
    send: async () => { if (busy) throw new Error('This teammate is already replying'); },
    waitForTurn: () => busy ? gate.promise : Promise.resolve('done') };
  const surface = new ChannelSurface({ engine }), owner = {}, ref = inbound();
  const work = surface.run(ref, 'chief', 'channel request', owner, { toolBudget: 3 });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(agent.config.maxToolCalls, 60);
  assert.equal(surface.owns('chief', owner), false);
  busy = false; engine.turns.delete('chief'); gate.resolve('desktop reply'); await work;
  assert.equal(agent.config.maxToolCalls, 60);
});

test('channel sessions share a bounded agent-turn pool on a low-memory host', async () => {
  const gate = deferred(); let starts = 0;
  const surface = new ChannelSurface({ engine: { send: async () => { starts++; }, waitForTurn: () => gate.promise } });
  const work = Array.from({ length: 6 }, (_, index) => surface.run(inbound(String(index)), `agent-${index}`, 'work', {}));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(starts, 4);
  gate.resolve('done'); await Promise.all(work);
  assert.equal(starts, 6);
});
