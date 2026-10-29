import { slackManifest, SLACK_CHANNEL_ID } from './manifests/slack.mjs';
import { SocketChannel, SOCKET_RECONNECT_CODE, splitChannelText, approvalButtonId, approvalButton } from './core/socket.mjs';
import { requestJson, requestResponse, httpFailure } from './core/http.mjs';
import { DeliveryError } from './core/outbox.mjs';
import { UPLOAD_TIMEOUT_MS } from './core/contract.mjs';

const API_BASE = 'https://slack.com/api/'; // Official Web API; injected in local transport tests.
const UPLOAD_ORIGIN = 'https://files.slack.com'; // Signed upload tickets may send bytes here only, never bot credentials.
const MESSAGE_LIMIT = 4000; // Characters: conservative Slack accessibility/performance recommendation.
const SECTION_LIMIT = 3000; // Characters per Block Kit section text object.
const REACTIONS = Object.freeze({ received: 'eyes', complete: '+1', failed: '-1' }); // Slack expects emoji names, not Unicode glyphs.
const AUTH_ERRORS = new Set(['invalid_auth', 'not_authed', 'token_expired', 'token_revoked', 'account_inactive', 'not_allowed_token_type', 'missing_scope']);
const DEAD_TARGET_ERRORS = new Set(['channel_not_found', 'not_in_channel', 'is_archived', 'no_permission', 'posting_to_channel_denied']);
const UNCERTAIN_ERRORS = new Set(['internal_error', 'fatal_error', 'service_unavailable', 'request_timeout']);
const escapeText = text => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const receipt = messageId => {
  if (!messageId) throw new DeliveryError('unknown', 'Slack returned no delivery receipt; check the conversation before retrying');
  return { messageId: String(messageId), parts: [String(messageId)] };
};

export function slackEnvelope(packet, botId) {
  const payload = packet.payload || {}, event = payload.event;
  if (packet.type === 'events_api' && event && ['message', 'app_mention'].includes(event.type)) {
    return { channel: SLACK_CHANNEL_ID, chatId: event.channel, messageId: event.ts, senderId: event.user || event.bot_id, senderName: event.username || event.user || '',
      text: event.text || '', media: event.files?.length ? [{ kind: 'unsupported' }] : [], threadId: event.thread_ts || null,
      raw: { isGroup: event.channel_type ? event.channel_type !== 'im' : !String(event.channel).startsWith('D'), serverId: payload.team_id || event.team || null,
        bot: Boolean(event.bot_id || event.user === botId), webhook: Boolean(event.subtype === 'bot_message'), system: Boolean(event.subtype),
        mentioned: event.type === 'app_mention' || Boolean(botId && event.text?.includes(`<@${botId}>`)) } };
  }
  if (packet.type !== 'interactive' || payload.type !== 'block_actions') return null;
  const action = payload.actions?.[0], button = approvalButton(action?.value || action?.action_id);
  if (!button) return null;
  return { channel: SLACK_CHANNEL_ID, chatId: payload.channel?.id, messageId: packet.envelope_id, senderId: payload.user?.id, senderName: payload.user?.username || '', text: '', media: [],
    raw: { isGroup: !String(payload.channel?.id).startsWith('D'), serverId: payload.team?.id || null, ...button } };
}

export class SlackAdapter extends SocketChannel {
  constructor({ fetchImpl = fetch, apiBase = API_BASE, uploadOrigin = UPLOAD_ORIGIN, ...options } = {}) {
    super(options); Object.assign(this, { manifest: slackManifest, fetchImpl, apiBase, uploadOrigin });
  }
  split(text) { return splitChannelText(text, MESSAGE_LIMIT); }
  async api(method, body = {}, { token = this.settings?.botToken, signal, timeoutMs } = {}) {
    const { data, headers } = await requestJson(new URL(method, this.apiBase), { platform: 'Slack', fetchImpl: this.fetchImpl, method: 'POST', signal, timeoutMs,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json; charset=utf-8' }, body: JSON.stringify(body) });
    if (data.ok !== true) {
      if (data.error === 'already_reacted' && method === 'reactions.add') return data;
      if (data.error === 'ratelimited') throw httpFailure('Slack', 429, data, headers);
      if (UNCERTAIN_ERRORS.has(data.error)) throw new DeliveryError('unknown', 'Slack send outcome is unknown; check the conversation before retrying');
      const auth = AUTH_ERRORS.has(data.error), failure = new DeliveryError('permanent', auth ? 'Slack rejected credentials or required scopes; check both app and bot tokens' : 'Slack rejected this request; check membership, conversation ID and app permissions', { deadTarget: DEAD_TARGET_ERRORS.has(data.error) });
      failure.fatal = auth; throw failure;
    }
    return data;
  }
  async verify(settings) {
    const me = await this.api('auth.test', {}, { token: settings.botToken });
    await this.api('apps.connections.open', {}, { token: settings.appToken });
    return { account: me.user || me.user_id };
  }
  async prepare() { this.me = await this.api('auth.test', {}, { signal: this.controller.signal }); this.botId = this.me.user_id; }
  async connectionUrl() { return (await this.api('apps.connections.open', {}, { token: this.settings.appToken, signal: this.controller.signal })).url; }
  packet(packet, ws, handshake) {
    if (packet.type === 'hello') { this.markReady(this.me.user || this.botId); handshake(); return; }
    if (packet.type === 'disconnect') { this.disabled = packet.reason === 'link_disabled'; ws.close(SOCKET_RECONNECT_CODE); return; }
    if (!packet.envelope_id) return;
    this.enqueuePacket(ws, async () => {
      const ref = slackEnvelope(packet, this.botId);
      if (ref) await this.ctx.receive(ref);
      this.sendPacket({ envelope_id: packet.envelope_id }, ws);
    });
  }
  closeError() {
    if (!this.disabled) return null;
    const error = new Error('Slack Socket Mode was disabled; enable it in the app configuration'); error.fatal = true; return error;
  }
  payload(ref, extra = {}) {
    const thread = ref.threadId || ref.replyTo;
    return { channel: String(ref.chatId), text: escapeText(ref.parts?.join('\n') || ''), parse: 'none', link_names: false, unfurl_links: false, unfurl_media: false,
      ...(thread ? { thread_ts: String(thread) } : {}), ...extra };
  }
  async send(ref, { signal } = {}) { return receipt((await this.api('chat.postMessage', this.payload(ref), { signal })).ts); }
  react(ref, state) { return this.api('reactions.add', { channel: String(ref.chatId), timestamp: String(ref.messageId), name: REACTIONS[state] || state }); }
  async edit(ref) { return receipt((await this.api('chat.update', { ...this.payload(ref), ts: String(ref.messageId) })).ts); }
  async buttons(ref, options) {
    const blocks = splitChannelText(ref.parts.join('\n'), SECTION_LIMIT).map(text => ({ type: 'section', text: { type: 'plain_text', text } }));
    blocks.push({ type: 'actions', elements: options.map(option => ({ type: 'button', text: { type: 'plain_text', text: option.label }, action_id: approvalButtonId(option.requestId, option.value), value: approvalButtonId(option.requestId, option.value), ...(option.value === 'no' ? { style: 'danger' } : option.value === 'yes' ? { style: 'primary' } : {}) })) });
    return receipt((await this.api('chat.postMessage', this.payload(ref, { blocks }))).ts);
  }
  async upload(ref, file, { signal } = {}) {
    const bytes = Buffer.from(file.base64, 'base64');
    const ticket = await this.api('files.getUploadURLExternal', { filename: file.filename, length: bytes.length }, { signal });
    let url; try { url = new URL(ticket.upload_url); } catch { throw new DeliveryError('permanent', 'Slack returned an invalid upload ticket'); }
    if (url.origin !== this.uploadOrigin || url.username || url.password || !ticket.file_id) throw new DeliveryError('permanent', 'Slack returned an untrusted upload destination');
    const response = await requestResponse(url, { platform: 'Slack upload', fetchImpl: this.fetchImpl, method: 'POST', signal, timeoutMs: UPLOAD_TIMEOUT_MS, headers: { 'Content-Type': file.mime || 'application/octet-stream' }, body: bytes });
    if (!response.ok) throw httpFailure('Slack upload', response.status, {}, response.headers);
    // Consume the small response so native fetch can reuse its connection.
    await response.text();
    const thread = ref.threadId || ref.replyTo;
    const complete = await this.api('files.completeUploadExternal', { files: [{ id: ticket.file_id, title: file.filename }], channel_id: String(ref.chatId), ...(thread ? { thread_ts: String(thread) } : {}), ...(file.caption ? { initial_comment: escapeText(file.caption) } : {}) }, { signal, timeoutMs: UPLOAD_TIMEOUT_MS });
    return receipt(complete.files?.find(entry => entry.id === ticket.file_id)?.id);
  }
}
