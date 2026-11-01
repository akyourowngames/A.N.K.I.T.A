import { discordManifest, DISCORD_CHANNEL_ID } from './manifests/discord.mjs';
import { SocketChannel, SOCKET_RECONNECT_CODE, splitChannelText, approvalButtonId, approvalButton } from './core/socket.mjs';
import { requestJson } from './core/http.mjs';
import { DeliveryError } from './core/outbox.mjs';
import { ACK_STATES, UPLOAD_TIMEOUT_MS } from './core/contract.mjs';
import { platform } from 'node:os';

const API_BASE = 'https://discord.com/api/v10'; // Discord's stable REST version; injectable for local round trips.
const GATEWAY_VERSION = '10'; // Gateway protocol, explicitly negotiated rather than inheriting server defaults.
const MESSAGE_LIMIT = 2000; // UTF-16 code units per Discord message.
const IDENTIFY_INTERVAL_MS = 5000; // Minimum identify spacing; a single local shard avoids burst reconnects.
const INTENTS = (1 << 0) | (1 << 9) | (1 << 12) | (1 << 15); // Guilds, guild messages, DMs and privileged message content.
const OP = Object.freeze({ dispatch: 0, heartbeat: 1, identify: 2, resume: 6, reconnect: 7, invalid: 9, hello: 10, ack: 11 });
const FATAL_CLOSES = new Set([4004, 4010, 4011, 4012, 4013, 4014]); // Auth, shard/version and invalid/disallowed intent errors cannot heal by retrying.
const EXPIRED_CLOSES = new Set([4007, 4009]); // Invalid sequence or session timeout requires a fresh identify.
const COMPONENT = Object.freeze({ row: 1, button: 2, primary: 1, secondary: 2, danger: 4, interaction: 3, deferUpdate: 6 });
const THREAD_CHANNEL_TYPES = new Set([10, 11, 12]); // News, public and private thread channels.
const NO_MENTIONS = Object.freeze({ parse: [], replied_user: false }); // Generated content must never ping people/roles/everyone.
const id = value => encodeURIComponent(String(value));
const receipt = data => {
  if (!data?.id) throw new DeliveryError('unknown', 'Discord returned no message receipt; check the conversation before retrying');
  return { messageId: String(data.id), parts: [String(data.id)] };
};

export function discordEnvelope(data, botId) {
  const button = data.type === COMPONENT.interaction ? approvalButton(data.data?.custom_id) : null;
  if (data.type === COMPONENT.interaction && !button) return null;
  const sender = data.author || data.member?.user || data.user || {};
  return {
    channel: DISCORD_CHANNEL_ID, chatId: data.channel_id, messageId: data.id, senderId: sender.id, senderName: sender.global_name || sender.username || '',
    text: button ? '' : data.content || '', media: data.attachments?.length ? [{ kind: 'unsupported' }] : [],
    threadId: THREAD_CHANNEL_TYPES.has(data.channel_type) ? data.channel_id : null,
    raw: { isGroup: Boolean(data.guild_id), serverId: data.guild_id || null, bot: Boolean(sender.bot), webhook: Boolean(data.webhook_id),
      system: !button && ![undefined, 0, 19].includes(data.type), mentioned: Boolean(data.mentions?.some(user => user.id === botId)), ...button },
  };
}

export class DiscordAdapter extends SocketChannel {
  constructor({ fetchImpl = fetch, apiBase = API_BASE, random = Math.random, ...options } = {}) {
    super({ retryBaseMs: IDENTIFY_INTERVAL_MS, ...options }); Object.assign(this, { manifest: discordManifest, fetchImpl, apiBase, random });
    this.seq = null; this.sessionId = null; this.resumeUrl = null;
  }
  split(text) { return splitChannelText(text, MESSAGE_LIMIT); }
  async api(route, { method = 'POST', body, signal, token = this.settings?.token, timeoutMs, auth = true, emptyResponse = false } = {}) {
    const multipart = body instanceof FormData;
    const { data } = await requestJson(`${this.apiBase}${route}`, { platform: 'Discord', fetchImpl: this.fetchImpl, method, signal, timeoutMs, emptyResponse,
      headers: { ...(auth ? { Authorization: `Bot ${token}` } : {}), ...(multipart ? {} : { 'Content-Type': 'application/json' }) },
      ...(body == null ? {} : { body: multipart ? body : JSON.stringify(body) }),
    }); return data;
  }
  async verify(settings) {
    const me = await this.api('/users/@me', { method: 'GET', token: settings.token });
    // Bot user IDs and application IDs are the same snowflake in Discord's bot model.
    if (String(me.id) !== String(settings.applicationId)) throw new Error('Discord Application ID does not match this bot token');
    return { account: me.username || me.id };
  }
  async prepare() { this.gateway = await this.api('/gateway/bot', { method: 'GET', signal: this.controller.signal }); }
  async connectionUrl() {
    const url = new URL(this.sessionId ? this.resumeUrl : this.gateway.url); url.searchParams.set('v', GATEWAY_VERSION); url.searchParams.set('encoding', 'json'); return url.href;
  }
  packet(packet, ws, handshake) {
    if (packet.op === OP.ack) { this.awaitingAck = false; return; }
    if (packet.op === OP.heartbeat) { this.sendPacket({ op: OP.heartbeat, d: this.seq }, ws); return; }
    if (packet.op === OP.hello) {
      const interval = Number(packet.d?.heartbeat_interval);
      if (!Number.isFinite(interval) || interval <= 0) throw new Error('Invalid heartbeat interval');
      this.awaitingAck = false;
      const beat = () => { this.heartbeat(); if (this.ws === ws) this.heartbeatTimer = setTimeout(beat, interval); };
      this.heartbeatTimer = setTimeout(beat, interval * this.random());
      this.sendPacket(this.sessionId ? { op: OP.resume, d: { token: this.settings.token, session_id: this.sessionId, seq: this.seq } }
        : { op: OP.identify, d: { token: this.settings.token, intents: INTENTS, properties: { os: platform(), browser: 'ankita', device: 'ankita' } } }, ws); return;
    }
    if (packet.op === OP.reconnect || packet.op === OP.invalid) {
      if (packet.op === OP.invalid && !packet.d) this.clearSession(); ws.close(SOCKET_RECONNECT_CODE); return;
    }
    if (packet.op !== OP.dispatch) return;
    this.enqueuePacket(ws, async () => {
      const data = packet.d;
      if (packet.t === 'READY') {
        if (String(data.user?.id) !== String(this.settings.applicationId)) {
          // Identity mismatch cannot be repaired by reconnecting. The close code gives a credential-safe error.
          ws.close(4004); return;
        }
        this.sessionId = data.session_id; this.resumeUrl = data.resume_gateway_url; this.botId = data.user.id;
        this.markReady(data.user.username || this.botId); handshake();
      } else if (packet.t === 'RESUMED') { this.markReady(this.botId); handshake(); }
      else if (packet.t === 'MESSAGE_CREATE' || packet.t === 'INTERACTION_CREATE') {
        const ref = discordEnvelope(data, this.botId);
        if (ref) await this.ctx.receive(ref);
        if (packet.t === 'INTERACTION_CREATE' && data.type === COMPONENT.interaction) await this.api(`/interactions/${id(data.id)}/${id(data.token)}/callback`, { body: { type: COMPONENT.deferUpdate }, auth: false, signal: this.controller.signal, emptyResponse: true });
      }
      if (packet.s != null) this.seq = packet.s;
    });
  }
  heartbeat() {
    if (this.awaitingAck) { this.ws?.close(SOCKET_RECONNECT_CODE); return; }
    this.awaitingAck = true; this.sendPacket({ op: OP.heartbeat, d: this.seq });
  }
  cleanupConnection() { clearTimeout(this.heartbeatTimer); this.awaitingAck = false; }
  clearSession() { this.sessionId = null; this.resumeUrl = null; this.seq = null; }
  closeError(code) {
    if (EXPIRED_CLOSES.has(code)) this.clearSession();
    if (!FATAL_CLOSES.has(code)) return null;
    const error = new Error(code === 4014 ? 'Discord rejected the Message Content intent; enable it in the developer portal' : 'Discord rejected bot credentials, gateway intents or shard settings; check the app configuration'); error.fatal = true; return error;
  }
  payload(ref, extra = {}) {
    return { content: ref.parts?.join('\n') || '', allowed_mentions: NO_MENTIONS,
      ...(ref.replyTo ? { message_reference: { message_id: String(ref.replyTo), fail_if_not_exists: false } } : {}), ...extra };
  }
  async send(ref, { signal } = {}) { return receipt(await this.api(`/channels/${id(ref.chatId)}/messages`, { body: this.payload(ref), signal })); }
  typing(ref) { return this.api(`/channels/${id(ref.chatId)}/typing`, { emptyResponse: true }); }
  react(ref, state) { return this.api(`/channels/${id(ref.chatId)}/messages/${id(ref.messageId)}/reactions/${id(ACK_STATES[state] || state)}/@me`, { method: 'PUT', emptyResponse: true }); }
  async edit(ref) { return receipt(await this.api(`/channels/${id(ref.chatId)}/messages/${id(ref.messageId)}`, { method: 'PATCH', body: this.payload(ref) })); }
  async buttons(ref, options) {
    return receipt(await this.api(`/channels/${id(ref.chatId)}/messages`, { body: this.payload(ref, { components: [{ type: COMPONENT.row, components: options.map(option => ({ type: COMPONENT.button, style: option.value === 'no' ? COMPONENT.danger : option.value === 'yes' ? COMPONENT.primary : COMPONENT.secondary, label: option.label, custom_id: approvalButtonId(option.requestId, option.value) })) }] }) }));
  }
  async upload(ref, file, { signal } = {}) {
    const body = new FormData(); body.set('payload_json', JSON.stringify(this.payload(ref, { content: file.caption || '' })));
    body.set('files[0]', new Blob([Buffer.from(file.base64, 'base64')], { type: file.mime }), file.filename);
    return receipt(await this.api(`/channels/${id(ref.chatId)}/messages`, { body, signal, timeoutMs: UPLOAD_TIMEOUT_MS }));
  }
}
