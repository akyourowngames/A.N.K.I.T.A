import test from 'node:test';
import assert from 'node:assert/strict';
import { ChannelInbox } from '../../src/channels/core/inbox.mjs';

const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
test('one conversation remains FIFO while another channel keeps working', async () => {
  const inbox = new ChannelInbox(), gate = deferred(), order = [];
  const first = inbox.enqueue('telegram:42', async () => { order.push('first'); await gate.promise; order.push('first done'); });
  const next = inbox.enqueue('telegram:42', () => { order.push('next'); });
  await inbox.enqueue('discord:42', () => { order.push('discord'); });
  assert.deepEqual(order, ['first', 'discord']);
  gate.resolve(); await Promise.all([first, next]);
  assert.deepEqual(order, ['first', 'discord', 'first done', 'next']);
  assert.equal(inbox.chains.size, 0);
});
test('a shared agent target has one active turn even across different chats', async () => {
  const inbox = new ChannelInbox(), gate = deferred(); let active = 0, peak = 0;
  const work = async () => { peak = Math.max(peak, ++active); await gate.promise; active--; };
  const first = inbox.enqueue('telegram:1', work, { target: 'same-agent' });
  const second = inbox.enqueue('discord:2', work, { target: 'same-agent' });
  await new Promise(resolve => setImmediate(resolve)); assert.equal(peak, 1);
  gate.resolve(); await Promise.all([first, second]); assert.equal(peak, 1);
});
test('cancel bypasses the queue and prevents already-queued work from starting', async () => {
  const inbox = new ChannelInbox(), began = deferred(); let queued = false;
  const first = inbox.enqueue('telegram:42', ({ signal }) => new Promise(resolve => { signal.addEventListener('abort', resolve, { once: true }); began.resolve(); }));
  const second = inbox.enqueue('telegram:42', () => { queued = true; });
  await began.promise; inbox.cancel('telegram:42'); await Promise.all([first, second]);
  assert.equal(queued, false);
});
test('stop cancels active work and rejects new work without leaking queue entries', async () => {
  const inbox = new ChannelInbox(), began = deferred();
  const work = inbox.enqueue('slack:1', ({ signal }) => new Promise(resolve => { signal.addEventListener('abort', resolve, { once: true }); began.resolve(); }));
  await began.promise; await inbox.stop(); await work;
  assert.equal(inbox.chains.size, 0);
  await assert.rejects(inbox.enqueue('slack:2', () => {}), /stopped/);
});
