import test from 'node:test';
import assert from 'node:assert/strict';
import { DiscordAdapter } from '../../src/channels/discord.mjs';
import { SlackAdapter } from '../../src/channels/slack.mjs';
import { ChannelRuntime } from '../../src/channels/core/runtime.mjs';
import { ChannelSurface } from '../../src/channels/core/surface.mjs';
import { localSocketServer } from './local-socket-server.mjs';
import { eventually } from './socket-fixture.mjs';

const json = (response, value) => { response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify(value)); };
for (const channel of ['discord', 'slack']) test(`${channel} completes a real native WebSocket and HTTP agent/reply/button/file round trip`, async t => {
  const requests = [], received = [], packets = []; let counter = 0, peer;
  const local = await localSocketServer(t, {
    request: async (request, response, bytes) => {
      const route = request.url, multipart = request.headers['content-type']?.includes('multipart/form-data');
      const body = bytes.length && !multipart && route !== '/upload' ? JSON.parse(bytes) : null;
      requests.push({ route, body, auth: request.headers.authorization, bytes: bytes.toString() });
      if (route === '/gateway/bot') return json(response, { url: local.socketUrl });
      if (route === '/users/@me') return json(response, { id: 'bot', username: 'Ankita' });
      if (route.endsWith('/typing') || route.includes('/reactions/') || route.endsWith('/callback')) { response.writeHead(204); response.end(); return; }
      if (route === '/auth.test') return json(response, { ok: true, user: 'ankita', user_id: 'bot' });
      if (route === '/apps.connections.open') return json(response, { ok: true, url: local.socketUrl });
      if (route === '/files.getUploadURLExternal') return json(response, { ok: true, file_id: 'F1', upload_url: `${local.origin}/upload` });
      if (route === '/upload') { response.end('OK'); return; }
      if (route === '/files.completeUploadExternal') return json(response, { ok: true, files: [{ id: 'F1' }] });
      json(response, channel === 'discord' ? { id: String(++counter) } : { ok: true, ts: `reply-${++counter}` });
    },
    connect: client => {
      peer = client;
      client.onMessage = packet => {
        packets.push(packet);
        if (packet.op === 1) client.send({ op: 11 });
        if (packet.op === 2) {
          client.send({ op: 0, s: 1, t: 'READY', d: { session_id: 'local-session', resume_gateway_url: local.socketUrl, user: { id: 'bot', username: 'Ankita' } } });
          client.send({ op: 0, s: 2, t: 'MESSAGE_CREATE', d: { id: 'incoming', channel_id: 'room', author: { id: 'owner' }, content: 'hello' } });
        }
      };
      client.send(channel === 'discord' ? { op: 10, d: { heartbeat_interval: 10000 } } : { type: 'hello' });
      if (channel === 'slack') client.send({ type: 'events_api', envelope_id: 'accepted', payload: { team_id: 'workspace', event: { type: 'message', channel: 'D1', channel_type: 'im', user: 'owner', ts: '123.001', text: 'hello' } } });
    },
  });
  const adapter = channel === 'discord' ? new DiscordAdapter({ apiBase: local.origin }) : new SlackAdapter({ apiBase: `${local.origin}/`, uploadOrigin: local.origin });
  const chatId = channel === 'discord' ? 'room' : 'D1';
  const settings = { enabled: true, token: 'local-bot-token', applicationId: 'bot', botToken: 'local-bot-token', appToken: 'local-app-token', allowedChatIds: chatId, ownerChatId: chatId, ownerUserId: 'owner', teammateId: 'chief' };
  const runtime = new ChannelRuntime({ adapter, getSettings: () => settings, surface: new ChannelSurface({ engine: { send: async (_target, text) => received.push(text), waitForTurn: async () => 'Hello back' } }) });
  t.after(() => runtime.stop()); await runtime.start();
  await eventually(() => requests.some(request => request.body?.content === 'Hello back' || request.body?.text === 'Hello back')); await runtime.drain();
  assert.deepEqual(received, ['hello']);
  const ref = { channel, chatId, messageId: 'incoming', parts: ['Allow this?'] };
  const answers = [];
  runtime.askApproval(ref, { requestId: 'permission', toolName: 'write_file', detail: 'Save note', respond: answer => answers.push(answer) });
  await eventually(() => requests.some(request => request.body?.components || request.body?.blocks));
  const buttons = requests.find(request => request.body?.components || request.body?.blocks).body;
  if (channel === 'discord') peer.send({ op: 0, s: 3, t: 'INTERACTION_CREATE', d: { type: 3, id: 'button-event', token: 'local-interaction-token', channel_id: chatId, user: { id: 'owner' }, data: { custom_id: buttons.components[0].components[0].custom_id } } });
  else peer.send({ type: 'interactive', envelope_id: 'button-event', payload: { type: 'block_actions', user: { id: 'owner' }, channel: { id: chatId }, actions: [buttons.blocks.at(-1).elements[0]] } });
  await eventually(() => answers.length === 1); assert.deepEqual(answers, ['yes']);
  await adapter.edit({ ...ref, messageId: 'sent-message', parts: ['Edited'] });
  await adapter.upload(ref, { filename: 'poem.txt', mime: 'text/plain', base64: Buffer.from('local poem').toString('base64') });
  if (channel === 'slack') { assert.equal(requests.find(request => request.route === '/upload').auth, undefined); assert.ok(packets.some(packet => packet.envelope_id === 'accepted')); }
  assert.ok(requests.some(request => request.auth === 'Bot local-bot-token' || request.auth === 'Bearer local-bot-token'));
  await runtime.stop(); assert.equal(runtime.running, false);
  console.log(`${channel.toUpperCase()}_LOCAL_ROUNDTRIP_OK: native socket; HTTP; one turn; final reply; owner button; edit; upload; clean shutdown.`);
});
