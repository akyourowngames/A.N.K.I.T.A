import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ChannelOutbox, DeliveryError } from '../../src/channels/core/outbox.mjs';

const envelope = { channel: 'fixture', chatId: '42', messageId: 'incoming-7', parts: ['first', 'second'] };
function ledger(t) { const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-outbox-')); t.after(() => fs.rmSync(dir, { recursive: true, force: true })); return path.join(dir, 'receipts.json'); }

test('a resumed multipart reply does not resend an accepted part', async t => {
  const file = ledger(t), sent = [], adapter = { send: async e => { sent.push(e.parts[0]); if (e.parts[0] === 'second') throw new DeliveryError('transient', 'rejected before acceptance'); return { messageId: 'platform-first', parts: ['platform-first'] }; } };
  await assert.rejects(new ChannelOutbox({ file, retryLimit: 1 }).deliver(envelope, adapter), /rejected/);
  const second = new ChannelOutbox({ file });
  await second.deliver(envelope, { send: async e => { sent.push(e.parts[0]); return { messageId: 'platform-second', parts: ['platform-second'] }; } });
  assert.deepEqual(sent, ['first', 'second', 'second']);
  const receipts = second.inspect().records;
  assert.equal(Object.values(receipts).filter(r => r.state === 'sent').length, 2);
});

test('unknown send outcomes are never blindly retried, even after restart', async t => {
  const file = ledger(t); let sends = 0;
  const adapter = { send: async () => { sends++; throw new Error('connection dropped after write'); } };
  await assert.rejects(new ChannelOutbox({ file }).deliver(envelope, adapter), error => error.kind === 'unknown');
  await assert.rejects(new ChannelOutbox({ file }).deliver(envelope, adapter), error => error.kind === 'unknown');
  assert.equal(sends, 1);
});

test('a persisted in-flight claim is uncertain after a lost receipt and is not resent', async t => {
  const file = ledger(t); let finish;
  const first = new ChannelOutbox({ file }).deliver({ ...envelope, parts: ['only'] }, { send: () => new Promise(resolve => { finish = resolve; }) });
  await new Promise(resolve => setImmediate(resolve));
  let retried = false;
  await assert.rejects(new ChannelOutbox({ file }).deliver({ ...envelope, parts: ['only'] }, { send: async () => { retried = true; } }), error => error.kind === 'unknown');
  assert.equal(retried, false); finish({ messageId: 'one', parts: ['one'] }); await first;
});

test('known rate-limit rejections honor retry-after, while permanent targets stay paused', async t => {
  const file = ledger(t), waits = []; let sends = 0;
  const outbox = new ChannelOutbox({ file, delay: async ms => { waits.push(ms); } });
  await outbox.deliver({ ...envelope, parts: ['one'] }, { send: async () => { if (++sends === 1) throw new DeliveryError('rate_limited', 'slow down', { retryAfterMs: 7 }); return { messageId: 'ok', parts: ['ok'] }; } });
  assert.deepEqual(waits, [7]); assert.equal(sends, 2);
  const bad = { ...envelope, chatId: 'gone', parts: ['one'] };
  await assert.rejects(outbox.deliver(bad, { send: async () => { throw new DeliveryError('permanent', 'target gone', { deadTarget: true }); } }));
  let attempted = false;
  await assert.rejects(outbox.deliver({ ...bad, messageId: 'new' }, { send: async () => { attempted = true; } }), /re-verify/);
  assert.equal(attempted, false);
  outbox.revive('fixture', 'gone');
  await outbox.deliver({ ...bad, messageId: 'new' }, { send: async () => ({ messageId: 'restored', parts: ['restored'] }) });
});

test('delivery order is per conversation and a changed payload cannot reuse a receipt', async t => {
  const outbox = new ChannelOutbox({ file: ledger(t) }), sent = [];
  const adapter = { send: async e => { await new Promise(resolve => setImmediate(resolve)); sent.push(e.parts[0]); return { messageId: String(sent.length), parts: [String(sent.length)] }; } };
  await Promise.all([outbox.deliver(envelope, adapter), outbox.deliver({ ...envelope, messageId: 'incoming-8', parts: ['third'] }, adapter)]);
  assert.deepEqual(sent, ['first', 'second', 'third']);
  await assert.rejects(outbox.deliver({ ...envelope, parts: ['different'] }, adapter), /payload/i);
});

test('corrupt delivery receipts fail closed without replacing evidence', async t => {
  const file = ledger(t); fs.writeFileSync(file, '{broken');
  let attempted = false;
  await assert.rejects(new ChannelOutbox({ file }).deliver(envelope, { send: async () => { attempted = true; } }), /ledger/i);
  assert.equal(attempted, false); assert.equal(fs.readFileSync(file, 'utf8'), '{broken');
});

test('a platform retry-after is never shortened to the normal backoff cap', async t => {
  const waits = []; let attempts = 0;
  const outbox = new ChannelOutbox({ file: ledger(t), delay: async ms => waits.push(ms) });
  await outbox.deliver({ ...envelope, parts: ['one'] }, { send: async () => {
    if (!attempts++) throw new DeliveryError('rate_limited', 'wait', { retryAfterMs: 60_000 });
    return { messageId: 'one', parts: ['one'] };
  } });
  assert.deepEqual(waits, [60_000]);
});
