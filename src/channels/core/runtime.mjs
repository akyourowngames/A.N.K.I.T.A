import { ChannelInbox } from './inbox.mjs';
import { ChannelOutbox } from './outbox.mjs';
import { ChannelProgress } from './progress.mjs';
import { sendChannelArtifacts } from './artifacts.mjs';
import { normalizeInbound, sessionKey, CONFIRM_DEFAULT_SECONDS, assertAdapter } from './contract.mjs';
import { allows, isOwner, ownerIdentity, isBareApproval, parseApproval, isCancelMessage, stripAnsi, confirmationSeconds } from './policy.mjs';
import { randomUUID } from 'node:crypto';

const APPROVAL_OPTIONS = Object.freeze([{ label: 'Allow once', value: 'yes' }, { label: 'Always', value: 'always' }, { label: 'Deny', value: 'no' }]);
const APPROVAL_GUIDANCE = 'Reply y = allow once, a = always, n = deny';
const NO_PENDING_MESSAGE = 'Nothing is waiting for approval right now.';

export class ChannelRuntime {
  constructor({ adapter, surface, getSettings = () => ({}), outbox = new ChannelOutbox(), emit = () => {}, log = () => {}, transcribe = null, speak = null, pairing = null, onPair = null, settled = () => {}, legacy = false, runJob = null, approvalTimeoutMs = null } = {}) {
    Object.assign(this, { adapter, surface, getSettings, outbox, emit, log, transcribe, speak, pairing, onPair, settled, legacy, runJob, approvalTimeoutMs });
    assertAdapter(adapter);
    this.inbox = new ChannelInbox(); this.activeJobs = new Map(); this.pending = new Map(); this.approvalQueues = new Map();
    this.running = false; this.stopping = false; this.account = null; this.error = null; this.activeChat = null;
  }
  settings() { return this.getSettings(); }
  status() { return { running: this.running, account: this.account, error: this.error }; }
  get chains() { return new Map([...this.inbox.chains].map(([key, value]) => [key.slice(this.adapter.manifest.id.length + 1), value])); }
  async start() {
    if (this.running) return this.status();
    const settings = this.settings();
    if (!settings.enabled) return this.status();
    try { this.surface.assertReady?.(); }
    catch (error) { this.error = error.message; this.running = false; this.emit(); return this.status(); }
    for (const key of this.adapter.manifest.required || []) if (!settings[key]) { this.error = `Enter ${this.adapter.manifest.fields?.[key]?.label || key} before connecting`; this.emit(); return this.status(); }
    this.stopping = false; this.abort = new AbortController(); this.inbox = new ChannelInbox();
    this.running = true;
    const abort = this.abort;
    let work;
    try {
      work = this.adapter.start({ settings, signal: abort.signal, receive: message => this.receive(message), status: status => {
        if (this.abort === abort && !abort.signal.aborted) { Object.assign(this, status); this.emit(); }
      } });
    } catch (error) { this.error = error.message; this.running = false; await this.adapter.stop(); this.emit(); return this.status(); }
    this.loopPromise = Promise.resolve(work).catch(error => { if (!this.stopping) { this.error = error.message; this.running = false; this.emit(); } });
    try {
      const ready = await this.adapter.ready;
      if (this.abort === abort && !abort.signal.aborted && !this.stopping) { this.account = ready?.account || this.account; this.error = null; }
    }
    catch (error) { if (this.abort === abort && !abort.signal.aborted) { this.error = error.message; this.running = false; await this.adapter.stop(); } }
    this.emit(); return this.status();
  }
  async stop() {
    this.stopping = true; this.running = false;
    this.abort?.abort(new DOMException('Channel stopped', 'AbortError'));
    for (const active of this.activeJobs.values()) { active.cancelled = true; if (active.claimed && !this.inbox.controllers.has(sessionKey(active.ref))) this.surface.cancel(active.target); void active.progress.stop(); }
    for (const entry of this.pending.values()) entry.settle('no');
    for (const entries of this.approvalQueues.values()) for (const entry of entries) entry.settle('no');
    this.pending.clear(); this.approvalQueues.clear();
    await this.adapter.stop(); await this.inbox.stop();
    await this.loopPromise; this.loopPromise = null; this.account = null;
    this.emit(); return this.status();
  }
  async drain() { await Promise.allSettled([...this.inbox.chains.values()]); }
  async receive(input) {
    if (this.stopping || !this.running) return 0;
    const ref = normalizeInbound(input), settings = this.settings();
    if (ref.channel !== this.adapter.manifest.id || ref.raw?.bot || ref.raw?.webhook || ref.raw?.system) return 0;
    if (ref.raw?.approvalId && !isOwner(ref, settings)) return 0;
    const owned = this.activeJobs.get(String(ref.chatId));
    if (isCancelMessage(ref) && owned?.ref.senderId === ref.senderId) return this.control(ref, () => this.cancelJob(ref));
    if (this.pending.has(String(ref.chatId)) && isOwner(ref, settings)) return this.control(ref, () => this.resolvePending(ref));
    if (settings.pairingEnabled && /^\/pair\s+\S+\s*$/.test(ref.text) && this.pairing?.consume({ channel: ref.channel, senderId: ref.senderId, code: ref.text.split(/\s+/)[1] })) {
      return this.control(ref, async () => { await this.onPair?.(ref); await this.notice(ref, 'Paired. You can send requests now.'); });
    }
    if (!allows(ref, settings)) return 0;
    if (ref.media.some(media => media.kind === 'unsupported')) return this.control(ref, () => this.notice(ref, this.adapter.unsupportedMediaMessage || 'Incoming files are not supported yet. Send text or a voice note.'));
    if (isCancelMessage(ref)) return this.control(ref, () => this.cancelJob(ref));
    if (isBareApproval(ref.text) || ref.raw?.approvalId) return this.control(ref, () => this.notice(ref, NO_PENDING_MESSAGE));
    if (!this.outbox.claimInbound(ref)) return 0;
    this.dispatch(ref); return 1;
  }
  async control(ref, work) {
    if (!this.outbox.claimInbound(ref)) return 0;
    try { await work(); this.outbox.finishInbound(ref, 'control'); return 1; }
    catch (error) { this.outbox.finishInbound(ref, 'failed'); throw error; }
  }
  dispatch(ref) {
    const promise = this.inbox.enqueue(sessionKey(ref), ({ signal }) => this.runJob ? this.runJob(ref, { signal }) : this.handleJob(ref, { signal }));
    void promise.catch(error => this.log(`${this.adapter.manifest.id} turn failed: ${error.message}`));
    return promise;
  }
  notice(ref, text, intent = 'notice') { return this.adapter.send({ ...ref, parts: [text], replyTo: ref.messageId, intent }); }
  async handleJob(input, { signal } = {}) {
    if (this.stopping) return;
    const ref = normalizeInbound(input), settings = this.settings();
    if (!settings.teammateId) { await this.notice(ref, 'No agent is connected to this channel yet. Choose a teammate in Settings, then Channels.'); return; }
    const target = this.surface.targetFor(settings.teammateId, ref);
    const progress = new ChannelProgress(this.adapter, ref, { enabled: settings.progressBeats !== false });
    const active = { ref, target, teammateId: settings.teammateId, progress, cancelled: false, claimed: false, started: false, calls: new Map(), artifacts: [] };
    this.activeJobs.set(String(ref.chatId), active);
    const cancel = () => { active.cancelled = true; };
    signal?.addEventListener('abort', cancel, { once: true });
    try {
      let text = ref.text;
      if (ref.media.some(media => media.kind === 'voice')) {
        if (!this.transcribe) throw new Error('Voice notes are not configured for this channel');
        text = await this.transcribe(ref, { signal, cancelled: () => active.cancelled || this.stopping });
        if (!text) { await this.notice(ref, 'I could not make out that voice note.'); return; }
      }
      await progress.start();
      if (active.cancelled || this.stopping) return;
      const reply = await this.surface.run(ref, target, text, active, {
        signal, toolBudget: settings.toolBudget,
        claimed: () => { active.claimed = true; active.started = true; this.activeChat = String(ref.chatId); },
        released: () => { active.claimed = false; if (this.activeChat === String(ref.chatId)) this.activeChat = null; },
      });
      await progress.stop();
      if (active.cancelled || this.stopping) return;
      const body = String(reply || '').trim() || '(no reply)';
      const parts = this.adapter.split ? this.adapter.split(body) : [body];
      await this.outbox.deliver({ ...ref, parts, replyTo: ref.messageId, intent: 'reply' }, this.adapter, { signal });
      const cwd = this.surface.workspaceFor(target);
      if (cwd) await sendChannelArtifacts(this.adapter, ref, cwd, active.artifacts, () => active.cancelled || this.stopping, this.outbox);
      if (settings.voiceReply && this.adapter.manifest.capabilities.includes('voice')) await this.speak?.(ref, body);
      if (!active.cancelled) await progress.react('complete');
      this.outbox.finishInbound(ref);
    } catch (error) {
      active.error = error;
      await progress.stop();
      if (!active.cancelled && !this.stopping) { await this.notice(ref, `error: ${error.message}`).catch(() => {}); await progress.react('failed'); }
      try { this.outbox.finishInbound(ref, active.cancelled ? 'cancelled' : 'failed'); } catch {}
      this.log(`${this.adapter.manifest.id} request failed: ${error.message}`);
    } finally {
      signal?.removeEventListener('abort', cancel); await progress.stop();
      if (this.activeJobs.get(String(ref.chatId)) === active) this.activeJobs.delete(String(ref.chatId));
      if (this.activeChat === String(ref.chatId)) this.activeChat = null;
      this.settled(ref, active);
    }
  }
  handleEngineEvent(event) {
    let active = [...this.activeJobs.values()].find(job => !job.cancelled && job.target === event?.threadId && this.surface.owns(job.target, job));
    if (!active && this.legacy && this.activeChat && event?.type === 'approval-request' && this.settings().teammateId === event.threadId) {
      const chatId = String(this.activeChat);
      this.askApproval({ channel: this.adapter.manifest.id, chatId, senderId: chatId, messageId: event.requestId, raw: { isGroup: false } }, event);
      return;
    }
    if (!active) return;
    if (event.type === 'tool-call') active.calls.set(event.callId, { name: event.name, args: event.args });
    if (event.type === 'tool-result') {
      const call = active.calls.get(event.callId);
      if (call) { active.artifacts.push({ role: 'tool', ...call, result: event.text, isError: event.isError }); active.calls.delete(event.callId); }
    }
    active.progress.beat(event);
    if (event.type === 'approval-request') this.askApproval(active.ref, event, active);
  }
  askApproval(ref, event, active = null) {
    const settings = this.settings(), owner = ownerIdentity(ref.channel, settings);
    if (!owner || this.stopping) { this.answerApproval(event, 'no'); return; }
    const ownerRef = { channel: ref.channel, chatId: owner.chatId, senderId: owner.senderId, messageId: event.requestId, threadId: null, raw: { isGroup: false } };
    const entry = { event, active, ref: ownerRef, settled: false, settle: answer => {
      if (entry.settled) return;
      entry.settled = true; clearTimeout(entry.timer);
      if (this.pending.get(owner.chatId) === entry) this.pending.delete(owner.chatId);
      else { const queued = this.approvalQueues.get(owner.chatId) || []; this.approvalQueues.set(owner.chatId, queued.filter(item => item !== entry)); }
      this.answerApproval(event, answer);
      this.emit({ type: 'approval-resolved', requestId: event.requestId });
      const next = this.approvalQueues.get(owner.chatId)?.shift();
      if (next) { if (this.stopping) next.settle('no'); else this.showApproval(owner.chatId, next); }
    } };
    if (this.pending.has(owner.chatId)) {
      const queue = this.approvalQueues.get(owner.chatId) || []; queue.push(entry); this.approvalQueues.set(owner.chatId, queue);
    } else this.showApproval(owner.chatId, entry);
    return entry;
  }
  answerApproval(event, answer) { if (event.respond) event.respond(answer); else this.surface.respondApproval(event.requestId, answer); }
  requestApproval(ref, event, active = null) {
    return new Promise(resolve => this.askApproval(ref, { ...event, requestId: event.requestId || randomUUID(), respond: resolve }, active));
  }
  showApproval(chatId, entry) {
    this.pending.set(chatId, entry);
    const envelope = { ...entry.ref, intent: 'approval', parts: [`Permission needed: ${entry.event.toolName}\n\n${stripAnsi(entry.event.detail).trim()}\n\n${APPROVAL_GUIDANCE}`] };
    const request = this.adapter.manifest.capabilities.includes('buttons')
      ? this.adapter.buttons(envelope, APPROVAL_OPTIONS.map(option => ({ ...option, requestId: entry.event.requestId })))
      : this.adapter.send(envelope);
    Promise.resolve(request).catch(() => entry.settle('no'));
    const timeoutMs = this.approvalTimeoutMs?.() ?? confirmationSeconds(this.settings().confirmTimeout || CONFIRM_DEFAULT_SECONDS) * 1000;
    entry.timer = setTimeout(() => { entry.settle('no'); void this.notice(entry.ref, `No reply, so I skipped ${entry.event.toolName}.`).catch(() => {}); }, timeoutMs);
  }
  resolvePending(ref) {
    const waiting = this.pending.get(String(ref.chatId));
    if (!waiting || !isOwner(ref, this.settings())) return false;
    if (ref.raw?.approvalId && ref.raw.approvalId !== waiting.event.requestId) return true;
    if (ref.media?.length) { void this.notice(ref, 'Reply with text (y / n / a) to approve.').catch(() => {}); return true; }
    const answer = ref.raw?.approvalAnswer;
    waiting.settle(['yes', 'always', 'no'].includes(answer) ? answer : parseApproval(ref.text));
    return true;
  }
  async cancelJob(ref) {
    const key = String(ref.chatId), active = this.activeJobs.get(key);
    if (!active) { await this.notice(ref, 'Nothing is running in this chat.').catch(() => {}); return; }
    active.cancelled = true;
    // The surface's abort listener owns cancellation; direct handleJob calls use this fallback.
    const controller = this.inbox.controllers.get(sessionKey(ref));
    if (controller) this.inbox.cancel(sessionKey(ref));
    else if (active.claimed) this.surface.cancel(active.target);
    for (const pending of this.pending.values()) if (pending.active === active) pending.settle('no');
    for (const entries of this.approvalQueues.values()) for (const pending of [...entries]) if (pending.active === active) pending.settle('no');
    await active.progress.stop(); await active.progress.react('failed');
    await this.notice(ref, 'Stopped this task.').catch(() => {});
  }
}
