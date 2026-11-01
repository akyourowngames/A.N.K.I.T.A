import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { ChannelTelegramBot, TelegramAdapter } from '../../src/channels/telegram-adapter.mjs';
import { ChannelRuntime } from '../../src/channels/core/runtime.mjs';
import { ChannelSurface } from '../../src/channels/core/surface.mjs';

async function server(t, handler) {
  const api = http.createServer(async (request, response) => { const chunks = []; for await (const chunk of request) chunks.push(chunk); await handler(request, response, Buffer.concat(chunks)); });
  await new Promise(resolve => api.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => { api.closeAllConnections(); api.close(resolve); }));
  return `http://127.0.0.1:${api.address().port}`;
}

test('Telegram HTTP errors preserve retry-after and uncertain sends are typed without leaking the token', async t => {
  let status = 429;
  const apiBase = await server(t, async (_request, response) => { response.writeHead(status, { 'content-type': 'application/json' }); response.end(JSON.stringify({ ok: false, parameters: { retry_after: 2 }, description: 'fixture-secret-must-not-leak' })); });
  const bot = new ChannelTelegramBot({ token: 'fixture-token', apiBase });
  await assert.rejects(bot.call('sendMessage', { chat_id: 42, text: 'test' }), error => error.kind === 'rate_limited' && error.retryAfterMs === 2000 && !error.message.includes('fixture-secret'));
  status = 500;
  await assert.rejects(bot.call('sendMessage', {}), error => error.kind === 'unknown');
});

test('real local HTTP channel round trip preserves bot/sender metadata and sends one final reply', async t => {
  const requests = [], received = []; let round = 0;
  const apiBase = await server(t, async (request, response, bytes) => {
    const method = request.url.split('/').at(-1), params = JSON.parse(bytes.toString() || '{}'); requests.push({ method, params });
    let result = { message_id: requests.length };
    if (method === 'getMe') result = { id: 9, username: 'fixture_bot' };
    if (method === 'getUpdates') result = round++ ? [] : [
      { update_id: 1, message: { message_id: 7, from: { id: 42 }, chat: { id: 42, type: 'private' }, text: 'hello' } },
      { update_id: 2, message: { message_id: 8, from: { id: 43, is_bot: true }, chat: { id: 42, type: 'private' }, text: 'bot loop' } },
    ];
    response.writeHead(200, { 'content-type': 'application/json' }); response.end(JSON.stringify({ ok: true, result }));
  });
  const adapter = new TelegramAdapter({ botFactory: options => new ChannelTelegramBot({ ...options, apiBase }) }); adapter.offsetReady = true;
  const runtime = new ChannelRuntime({ adapter,
    getSettings: () => ({ enabled: true, token: 'fixture-token', allowedChatIds: '42', teammateId: 'chief' }),
    surface: new ChannelSurface({ engine: { send: async (_id, text) => received.push(text), waitForTurn: async () => 'Hello back' } }),
  });
  t.after(() => runtime.stop()); await runtime.start();
  const deadline = Date.now() + 3000;
  while (!requests.some(x => x.method === 'sendMessage' && x.params.text === 'Hello back') && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 10));
  await runtime.drain(); await runtime.stop();
  assert.deepEqual(received, ['hello']);
  assert.equal(requests.filter(x => x.method === 'sendMessage' && x.params.text === 'Hello back').length, 1);
  assert.equal(requests.filter(x => x.method === 'setMessageReaction').length, 2);
  assert.equal(requests.some(x => x.method === 'sendChatAction'), true);
  console.log('TELEGRAM_CHANNEL_HTTP_OK: real HTTP; sender/bot policy; typing; 2 reactions; 1 final reply; clean stop.');
});

test('Telegram keeps the replay cursor until every input in a poll is durably accepted', async () => {
  let persisted = 1;
  const adapter = new TelegramAdapter({ cursor: { get: () => persisted, set: offset => { persisted = offset; } }, bot: { poll: async () => ({ jobs: [{ chatId: 42, messageId: 1, text: 'work' }], offset: 2 }) } });
  await assert.rejects(adapter.tick({ receive: async () => { throw new Error('ledger busy'); } }), /busy/);
  assert.equal(persisted, 1); assert.equal(adapter.offset, 1);
  await adapter.tick({ receive: async () => 1 }); assert.equal(persisted, 2);
});

test('Telegram shutdown aborts an HTTP authentication request instead of waiting for its timeout', async t => {
  let arrived; const started = new Promise(resolve => { arrived = resolve; });
  const apiBase = await server(t, async () => { arrived(); });
  const adapter = new TelegramAdapter({ botFactory: options => new ChannelTelegramBot({ ...options, apiBase }) });
  const loop = adapter.start({ settings: { token: 'fixture-token' }, signal: new AbortController().signal, receive() {} });
  adapter.ready.catch(() => {}); await started;
  await adapter.stop();
  await Promise.race([loop, new Promise((_resolve, reject) => { const timer = setTimeout(() => reject(new Error('authentication did not stop promptly')), 1000); timer.unref(); })]);
  await assert.rejects(adapter.ready);
});
