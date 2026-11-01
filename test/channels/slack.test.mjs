import test from 'node:test';
import assert from 'node:assert/strict';
import { SlackAdapter } from '../../src/channels/slack.mjs';
import { ChannelRuntime } from '../../src/channels/core/runtime.mjs';
import { ChannelSurface } from '../../src/channels/core/surface.mjs';
import { socketFixture, eventually, jsonResponse } from './socket-fixture.mjs';

const settings = { botToken: 'private-bot-token', appToken: 'private-app-token', enabled: true, teammateId: 'chief', allowedChatIds: 'C1, D1', ownerChatId: 'D1', ownerUserId: 'U1' };
const event = (envelopeId = 'e1', overrides = {}) => ({ type: 'events_api', envelope_id: envelopeId, payload: { team_id: 'T1', event_id: 'event1', event: { type: 'app_mention', user: 'U1', channel: 'C1', ts: '123.001', text: '<@BOT> research', ...overrides } } });
function fixture(options = {}) {
  const sockets = socketFixture(), requests = [], received = [];
  const adapter = new SlackAdapter({ WebSocketImpl: sockets.WebSocket, delay: async () => {}, fetchImpl: async (url, init) => {
    requests.push({ url: String(url), init });
    return jsonResponse(String(url).endsWith('auth.test') ? { ok: true, user_id: 'BOT', user: 'ankita' } : String(url).endsWith('apps.connections.open') ? { ok: true, url: 'wss://socket.test' } : { ok: true, ts: 'reply1' });
  }, ...options });
  const controller = new AbortController(); const loop = adapter.start({ settings, signal: controller.signal, receive: async ref => { received.push(ref); return 1; }, status() {} });
  loop.catch(() => {}); adapter.ready.catch(() => {}); return { ...sockets, adapter, requests, received, loop };
}
async function ready(f) { await eventually(() => f.instances.length === 1); const ws = f.instances[0]; ws.open(); ws.packet({ type: 'hello' }); await f.adapter.ready; return ws; }

test('Slack opens with the app token, acknowledges accepted envelopes and reconnects using a fresh socket URL', async t => {
  const f = fixture(); t.after(async () => { await f.adapter.stop(); await f.loop; }); const ws = await ready(f);
  assert.equal(f.requests.find(x => x.url.endsWith('apps.connections.open')).init.headers.Authorization, `Bearer ${settings.appToken}`);
  assert.equal(f.requests.find(x => x.url.endsWith('auth.test')).init.headers.Authorization, `Bearer ${settings.botToken}`);
  ws.packet(event()); await eventually(() => ws.sent.length === 1); assert.deepEqual(ws.sent[0], { envelope_id: 'e1' });
  assert.equal(f.received[0].raw.mentioned, true); assert.equal(f.received[0].raw.serverId, 'T1'); assert.equal(f.received[0].raw.isGroup, true);
  ws.packet({ type: 'disconnect', reason: 'refresh_requested' }); await eventually(() => f.instances.length === 2);
  assert.equal(f.requests.filter(x => x.url.endsWith('apps.connections.open')).length, 2);
  console.log('SLACK_SOCKET_OK: app/bot token separation; envelope ACK; refresh; clean stop.');
});

test('Slack replay is acknowledged twice but runs one turn, and bot/subtype messages do not execute', async t => {
  const f = fixture(); t.after(async () => { await f.adapter.stop(); await f.loop; }); const ws = await ready(f); let turns = 0;
  const runtime = new ChannelRuntime({ adapter: f.adapter, getSettings: () => settings, surface: new ChannelSurface({ engine: { send: async () => { turns++; }, waitForTurn: async () => 'done' } }) }); runtime.running = true;
  f.adapter.ctx.receive = ref => runtime.receive(ref);
  ws.packet(event()); ws.packet(event('retry')); ws.packet(event('bot', { ts: '123.002', bot_id: 'BOT', subtype: 'bot_message' }));
  await eventually(() => ws.sent.length === 3); await runtime.drain(); assert.equal(turns, 1);
  assert.equal(f.requests.some(x => x.url.includes('typing')), false); assert.equal(f.adapter.manifest.capabilities.includes('typing'), false);
});

test('Slack never acknowledges an inbound event that failed durable acceptance', async t => {
  const f = fixture(); t.after(async () => { await f.adapter.stop(); await f.loop; }); const ws = await ready(f);
  f.adapter.ctx.receive = async () => { throw new Error('ledger busy'); }; ws.packet(event());
  await eventually(() => f.instances.length === 2); assert.equal(ws.sent.length, 0);
});

test('Slack button envelopes carry owner identity and request binding without leaking response URLs or tokens', async t => {
  const f = fixture(); t.after(async () => { await f.adapter.stop(); await f.loop; }); const ws = await ready(f);
  await f.adapter.buttons({ chatId: 'D1', parts: ['Permit?'] }, [{ requestId: 'r1', label: 'Allow once', value: 'yes' }]);
  const payload = JSON.parse(f.requests.at(-1).init.body), action = payload.blocks.at(-1).elements[0];
  ws.packet({ type: 'interactive', envelope_id: 'button', payload: { type: 'block_actions', token: 'private-interaction', response_url: 'https://private.test', user: { id: 'U1' }, channel: { id: 'D1' }, message: { ts: 'permit1' }, actions: [action] } });
  await eventually(() => f.received.length === 1); assert.equal(f.received[0].raw.approvalId, 'r1'); assert.equal(f.received[0].raw.isGroup, false); assert.equal(f.received[0].senderId, 'U1');
  assert.equal(JSON.stringify(f.received).includes('private-interaction'), false); assert.equal(JSON.stringify(f.received).includes('private.test'), false);
});

test('Slack uses thread timestamps, safe mention encoding and the official external upload flow without forwarding credentials', async () => {
  const requests = [];
  const adapter = new SlackAdapter({ uploadOrigin: 'https://files.slack.test', fetchImpl: async (url, init) => { requests.push({ url: String(url), init });
    if (String(url) === 'https://files.slack.test/upload') return new Response('OK');
    return jsonResponse(String(url).endsWith('files.getUploadURLExternal') ? { ok: true, file_id: 'F1', upload_url: 'https://files.slack.test/upload' } : String(url).endsWith('files.completeUploadExternal') ? { ok: true, files: [{ id: 'F1' }] } : { ok: true, ts: 'sent' });
  } }); adapter.settings = settings;
  const ref = { chatId: 'C1', messageId: 'm1', replyTo: '123.001', threadId: '123.000', parts: ['hello <!channel> <@U1> & all'] };
  await adapter.send(ref); const payload = JSON.parse(requests[0].init.body); assert.equal(payload.thread_ts, '123.000'); assert.equal(payload.link_names, false); assert.equal(payload.parse, 'none'); assert.ok(payload.text.includes('&lt;!channel&gt;'));
  const receipt = await adapter.upload(ref, { filename: 'poem.txt', mime: 'text/plain', base64: Buffer.from('poem').toString('base64') }); assert.equal(receipt.messageId, 'F1');
  const upload = requests.find(x => x.url === 'https://files.slack.test/upload'); assert.equal(upload.init.headers?.Authorization, undefined);
  assert.equal(Buffer.from(upload.init.body).toString(), 'poem');
  const complete = JSON.parse(requests.at(-1).init.body); assert.equal(complete.thread_ts, '123.000'); assert.equal(complete.channel_id, 'C1');
});

test('Slack classifies rate limits and ambiguous semantic errors, and stopping during authentication settles startup', async () => {
  const adapter = new SlackAdapter({ fetchImpl: async () => jsonResponse({ ok: false, error: 'ratelimited' }, 429, { 'retry-after': '2' }) }); adapter.settings = settings;
  await assert.rejects(adapter.send({ chatId: 'C1', parts: ['hello'] }), error => error.kind === 'rate_limited' && error.retryAfterMs === 2000);
  adapter.fetchImpl = async () => jsonResponse({ ok: false, error: 'internal_error', leaked: settings.botToken });
  await assert.rejects(adapter.send({ chatId: 'C1', parts: ['hello'] }), error => error.kind === 'unknown' && !error.message.includes(settings.botToken));
  const f = fixture(); await eventually(() => f.instances.length === 1); await f.adapter.stop(); await assert.rejects(f.adapter.ready, /stopped/i); await f.loop;
});
