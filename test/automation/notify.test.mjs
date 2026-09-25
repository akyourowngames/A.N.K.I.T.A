import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { NotificationDelivery, desktopNotify, inQuietHours, sendWebhook } from '../../src/automation/notify.mjs';

test('quiet hours cross midnight using the configured timezone', () => {
  assert.equal(inQuietHours('22:00-08:00', new Date('2026-09-20T18:00:00Z'), 'Asia/Kolkata'), true);
  assert.equal(inQuietHours('22:00-08:00', new Date('2026-09-21T02:30:00Z'), 'Asia/Kolkata'), false);
  assert.equal(inQuietHours('09:00-12:00', new Date('2026-09-21T05:00:00Z'), 'Asia/Kolkata'), true);
  assert.throws(() => inQuietHours('25:00-08:00'), /QUIET_HOURS/);
});

test('delivery uses Telegram then webhook then desktop then terminal on failure', async () => {
  const calls = [];
  const n = new NotificationDelivery({ config: {}, telegram: async () => { calls.push('telegram'); throw Error('offline'); }, webhook: async () => { calls.push('webhook'); throw Error('offline'); }, desktop: async () => { calls.push('desktop'); throw Error('missing'); }, print: text => calls.push(text) });
  assert.equal(await n.send('hello'), 'terminal');
  assert.deepEqual(calls, ['telegram', 'webhook', 'desktop', 'hello']);
  calls.length = 0;
  n.telegram = async () => { calls.push('telegram'); };
  assert.equal(await n.send('hello'), 'telegram');
  assert.deepEqual(calls, ['telegram']);
});

test('quiet digests survive restart, combine messages and empty only after delivery', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-notify-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'outbox.json');
  const config = { quietHours: '22:00-08:00', timeZone: 'UTC', desktopNotifications: false };
  let now = new Date('2026-09-20T23:00:00Z');
  const sent = [];
  const opts = { config, file, now: () => now, print: text => sent.push(text) };
  const first = new NotificationDelivery(opts);
  assert.equal(await first.send('first'), 'queued');
  first.enqueue('second');
  await first.flush();
  assert.equal(sent.length, 0);
  now = new Date('2026-09-21T08:00:00Z');
  const second = new NotificationDelivery(opts);
  await second.flush();
  assert.equal(sent.length, 1);
  assert.match(sent[0], /first[\s\S]*second/);
  assert.equal(JSON.parse(fs.readFileSync(file)).length, 0);
});

test('webhook payloads match service protocols and reject non-success responses', async () => {
  const calls = [];
  const fetch = async (url, opts) => { calls.push({ url, ...opts }); return { ok: true, json: async () => ({ status: 1 }) }; };
  await sendWebhook('hello', { ntfyUrl: 'https://ntfy.sh/topic' }, { fetch });
  assert.equal(calls[0].body, 'hello');
  await sendWebhook('@everyone hi', { discordWebhookUrl: 'https://discord.com/api/webhooks/test' }, { fetch });
  assert.deepEqual(JSON.parse(calls[1].body).allowed_mentions, { parse: [] });
  await sendWebhook('hello', { pushoverToken: 'token', pushoverUser: 'user' }, { fetch });
  assert.equal(calls[2].body.get('user'), 'user');
  await assert.rejects(sendWebhook('hello', { ntfyUrl: 'https://ntfy.sh/topic' }, { fetch: async () => ({ ok: false, status: 503 }) }), /503/);
});

test('desktop text is passed as data, never interpolated into shell code', async () => {
  const calls = [];
  const exec = async (...args) => { calls.push(args); };
  const text = '$(Remove-Item *) ` " ; & @everyone';
  await desktopNotify(text, { platform: 'win32', exec });
  assert.equal(calls[0][2].env.ANKITA_NOTIFY_BODY, text);
  assert.equal(calls[0][2].windowsHide, true);
  await desktopNotify(text, { platform: 'darwin', exec });
  assert.equal(calls[1][1].at(-1), text);
  await desktopNotify(text, { platform: 'linux', exec });
  assert.deepEqual(calls[2][1].slice(-2), ['ankita', text]);
});

test('multiple notification writers preserve queued items and do not double-send an in-flight digest', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-outbox-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'outbox.json');
  const sent = [];
  let release;
  const gate = new Promise(r => { release = r; });
  const opts = { file, telegram: async text => { sent.push(text); await gate; } };
  const a = new NotificationDelivery(opts), b = new NotificationDelivery(opts);
  a.enqueue('one'); b.enqueue('two');
  assert.equal(JSON.parse(fs.readFileSync(file)).length, 2);
  const flushing = a.flush();
  await b.flush();
  b.enqueue('three');
  release(); await flushing;
  await b.flush();
  assert.equal(sent.filter(s => s.includes('one')).length, 1);
  assert.equal(sent.filter(s => s.includes('two')).length, 1);
  assert.equal(sent.filter(s => s.includes('three')).length, 1);
  assert.equal(JSON.parse(fs.readFileSync(file)).length, 0);
});

test('real HTTP transport publishes UTF-8 to a configured ntfy endpoint', async t => {
  let received = '';
  const server = http.createServer(async (req, res) => {
    for await (const part of req) received += part.toString('utf8');
    res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{}');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  assert.equal(await sendWebhook('Test reminder: café ✓', { ntfyUrl: `http://127.0.0.1:${server.address().port}/topic` }), true);
  assert.equal(received, 'Test reminder: café ✓');
});

test('failed terminal fallback keeps the digest available for retry', async () => {
  let fail = true;
  const n = new NotificationDelivery({ config: { desktopNotifications: false }, print: () => { if (fail) throw Error('broken output'); } });
  n.enqueue('keep this reminder');
  await assert.rejects(n.flush(), /broken output/);
  assert.equal(n.queue.length, 1);
  fail = false;
  await n.flush();
  assert.equal(n.queue.length, 0);
});

test('transient cross-process queue locks are retried without losing a notification', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-notify-lock-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'queue.json');
  const lock = `${file}.lock`;
  fs.writeFileSync(lock, '');
  const n = new NotificationDelivery({ file, config: { desktopNotifications: false }, print: () => {} });
  const pending = n.queueMessage('must survive contention');
  setTimeout(() => fs.unlinkSync(lock), 40);
  await pending;
  assert.equal(JSON.parse(fs.readFileSync(file))[0].text, 'must survive contention');
});
