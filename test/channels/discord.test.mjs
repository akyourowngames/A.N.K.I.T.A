import test from 'node:test';
import assert from 'node:assert/strict';
import { DiscordAdapter } from '../../src/channels/discord.mjs';
import { ChannelOutbox } from '../../src/channels/core/outbox.mjs';
import { socketFixture, eventually, jsonResponse } from './socket-fixture.mjs';

const settings = { token: 'private-discord-token', applicationId: 'bot' };
const message = (id = 'm1') => ({ op: 0, s: 2, t: 'MESSAGE_CREATE', d: { id, channel_id: 'room', guild_id: 'server', author: { id: 'owner', username: 'Krish' }, content: '<@bot> hello', mentions: [{ id: 'bot' }], attachments: [] } });
function fixture(options = {}) {
  const sockets = socketFixture(), requests = [], received = [], statuses = [];
  const adapter = new DiscordAdapter({ WebSocketImpl: sockets.WebSocket, delay: async () => {}, random: () => 0.5,
    fetchImpl: async (url, init) => { requests.push({ url: String(url), init }); return jsonResponse(String(url).endsWith('/gateway/bot') ? { url: 'wss://gateway.test' } : String(url).endsWith('/users/@me') ? { id: 'bot', username: 'Ankita' } : { id: 'sent' }); }, ...options });
  const controller = new AbortController();
  const loop = adapter.start({ settings, signal: controller.signal, receive: async ref => { received.push(ref); return 1; }, status: state => statuses.push(state) });
  // Attach immediately; fatal startup is asserted by the tests without an unhandled rejection.
  loop.catch(() => {}); adapter.ready.catch(() => {});
  return { ...sockets, adapter, requests, received, statuses, controller, loop };
}
async function ready(f) {
  await eventually(() => f.instances.length === 1); const ws = f.instances[0]; ws.open();
  ws.packet({ op: 10, d: { heartbeat_interval: 10000 } });
  await eventually(() => ws.sent.some(packet => packet.op === 2));
  ws.packet({ op: 0, s: 1, t: 'READY', d: { session_id: 'session', resume_gateway_url: 'wss://resume.test', user: { id: 'bot', username: 'Ankita' } } });
  await f.adapter.ready; return ws;
}

test('Discord identifies, normalizes sender/group/thread metadata and resumes only accepted events', async t => {
  const f = fixture(); t.after(async () => { await f.adapter.stop(); await f.loop; }); const ws = await ready(f);
  const identify = ws.sent.find(packet => packet.op === 2); assert.equal(identify.d.token, settings.token); assert.ok(identify.d.intents & (1 << 15));
  ws.packet(message()); await eventually(() => f.received.length === 1);
  assert.equal(f.received[0].senderId, 'owner'); assert.equal(f.received[0].raw.serverId, 'server'); assert.equal(f.received[0].raw.mentioned, true);
  assert.equal(f.received[0].raw.isGroup, true); assert.equal(JSON.stringify(f.received).includes(settings.token), false);
  ws.packet({ op: 7 }); await eventually(() => f.instances.length === 2); const next = f.instances[1]; next.open(); next.packet({ op: 10, d: { heartbeat_interval: 10000 } });
  await eventually(() => next.sent.some(packet => packet.op === 6));
  assert.deepEqual(next.sent.find(packet => packet.op === 6).d, { token: settings.token, session_id: 'session', seq: 2 });
  console.log('DISCORD_GATEWAY_OK: identify; accepted sequence; resume; normalized sender and group; clean stop.');
});

test('Discord heartbeat ACK loss reconnects and fatal intent rejection stops without a reconnect loop', async t => {
  const f = fixture(); t.after(async () => { await f.adapter.stop(); await f.loop.catch(() => {}); }); const ws = await ready(f);
  f.adapter.heartbeat(); assert.equal(ws.sent.at(-1).op, 1); ws.packet({ op: 11 }); f.adapter.heartbeat();
  assert.equal(f.instances.length, 1); f.adapter.heartbeat(); await eventually(() => f.instances.length === 2);
  f.instances[1].closeFromServer(4014); await assert.rejects(f.loop, /Message Content|intent/i);
  assert.equal(f.instances.length, 2);
});

test('Discord failed inbound acceptance does not advance replay sequence', async t => {
  const f = fixture(); t.after(async () => { await f.adapter.stop(); await f.loop; }); const ws = await ready(f);
  f.adapter.ctx.receive = async () => { throw new Error('busy private-token'); };
  ws.packet(message()); await eventually(() => f.instances.length === 2);
  const next = f.instances[1]; next.open(); next.packet({ op: 10, d: { heartbeat_interval: 10000 } });
  await eventually(() => next.sent.some(packet => packet.op === 6)); assert.equal(next.sent.find(packet => packet.op === 6).d.seq, 1);
  assert.equal(JSON.stringify(f.statuses).includes('private-token'), false);
});

test('Discord buttons bind the original request and sender, acknowledge privately and never expose interaction tokens', async t => {
  const f = fixture(); t.after(async () => { await f.adapter.stop(); await f.loop; }); const ws = await ready(f);
  await f.adapter.buttons({ chatId: 'dm', parts: ['Permit?'] }, [{ label: 'Allow once', value: 'yes', requestId: 'request-1' }]);
  const body = JSON.parse(f.requests.at(-1).init.body); const customId = body.components[0].components[0].custom_id;
  ws.packet({ op: 0, s: 2, t: 'INTERACTION_CREATE', d: { type: 3, id: 'interaction', token: 'private-interaction', channel_id: 'dm', user: { id: 'owner' }, data: { custom_id: customId } } });
  await eventually(() => f.received.length === 1);
  assert.equal(f.received[0].raw.approvalId, 'request-1'); assert.equal(f.received[0].raw.approvalAnswer, 'yes'); assert.equal(f.received[0].raw.isGroup, false);
  assert.equal(JSON.stringify(f.received).includes('private-interaction'), false);
  await eventually(() => f.requests.some(request => request.url.endsWith('/callback')));
});

test('Discord REST enforces mention safety, splits replies, uploads files and classifies rejected versus uncertain sends', async () => {
  const requests = []; let status = 200;
  const adapter = new DiscordAdapter({ fetchImpl: async (url, init) => { requests.push({ url: String(url), init }); return jsonResponse(status === 429 ? { retry_after: 1.5 } : status === 500 ? { token: settings.token } : { id: 'sent' }, status); } });
  adapter.settings = settings;
  assert.equal(adapter.split('x'.repeat(4001)).length, 3);
  const ref = { channel: 'discord', chatId: 'room', messageId: 'm1', replyTo: 'm1', parts: ['hello @everyone'] };
  const receipt = await adapter.send(ref); assert.equal(receipt.messageId, 'sent'); assert.deepEqual(JSON.parse(requests[0].init.body).allowed_mentions, { parse: [], replied_user: false });
  await adapter.upload(ref, { filename: 'poem.txt', mime: 'text/plain', base64: Buffer.from('poem').toString('base64') });
  assert.equal(requests.at(-1).init.body.get('files[0]').name, 'poem.txt');
  status = 429; await assert.rejects(adapter.send(ref), error => error.kind === 'rate_limited' && error.retryAfterMs === 1500);
  status = 500; const outbox = new ChannelOutbox(); await assert.rejects(outbox.deliver(ref, adapter), error => error.kind === 'unknown' && !error.message.includes(settings.token));
  const count = requests.length; await assert.rejects(outbox.deliver(ref, adapter), { kind: 'unknown' }); assert.equal(requests.length, count);
});

test('Discord stops a pending socket handshake promptly without leaving readiness unresolved', async () => {
  const f = fixture(); await eventually(() => f.instances.length === 1); await f.adapter.stop();
  await assert.rejects(f.adapter.ready, /stopped/i); await f.loop;
});
