import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { stripVTControlCharacters } from 'node:util';
import { redactText } from '../core/redact.mjs';
import { isToolFailure } from '../core/verify.mjs';
import { VOICE_TASK_COMMAND } from '../core/commands.mjs';
import { VOICE_TASK_LIMIT, VOICE_JOB_SPEAK_MIN_INTERVAL_MS, VOICE_SPEECH_GAP_MS, VOICE_JOB_WAIT_UPDATE_MS, VOICE_PROGRESS_PLAYBACK_MAX_MS, VOICE_PROGRESS_POLL_MS } from './voice-task-policy.mjs';
import { voiceActionContext, voiceResultConfirmation } from './voice-progress.mjs';

export { VOICE_TASK_COMMAND };
const RECORD_SUFFIX = '.json';
const ID_PATTERN = /^[a-f\d-]{36}$/i; // UUIDs only: command arguments cannot escape the task directory.
const FINAL_STATES = new Set(['done', 'failed', 'cancelled']);
const SILENT_TOOLS = new Set(['recall', 'remember', 'project_memory', 'find_tools', 'write_todos']); // Internal bookkeeping is never a spoken work update.
const TOOL_VERBS = new Map([
  ['read_file', 'Read'], ['list_dir', 'Read'], ['search_files', 'Read'], ['glob', 'Read'],
  ['write_file', 'Write'], ['edit_file', 'Write'], ['edit_lines', 'Write'], ['apply_patch', 'Write'],
  ['create_dir', 'Write'], ['run_command', 'Run'], ['browser', 'Browse'], ['web_fetch', 'Browse'],
]);
const TASK_ERRORS = {
  empty: 'The planner returned no final report.',
  steps: 'One or more work steps failed. Read the report before retrying.',
  cancelled: 'cancelled',
};
const cleanLine = value => stripVTControlCharacters(String(value ?? '')).replace(/[\r\n\x00-\x1f\x7f]/g, ' ');

export function voiceStepLabel(tool) {
  const name = cleanLine(tool || 'tool');
  return `${TOOL_VERBS.get(name) || 'Use'} · ${name}`;
}

/** Atomic, bounded records. Only observed step metadata is stored, never raw tool payloads. */
export class VoiceTaskStore {
  constructor({ directory, limit = VOICE_TASK_LIMIT, secrets = [] }) {
    this.directory = directory;
    this.limit = Math.max(1, limit);
    this.secrets = secrets;
    fs.mkdirSync(directory, { recursive: true });
  }

  get(id) {
    if (!ID_PATTERN.test(String(id))) return null;
    try {
      const record = JSON.parse(fs.readFileSync(path.join(this.directory, id + RECORD_SUFFIX), 'utf8'));
      if (record.id !== id || !Array.isArray(record.steps) || typeof record.transcript !== 'string') return null;
      return record;
    } catch { return null; }
  }

  list() {
    return fs.readdirSync(this.directory).filter(name => name.endsWith(RECORD_SUFFIX))
      .map(name => this.get(name.slice(0, -RECORD_SUFFIX.length))).filter(Boolean)
      .sort((a, b) => b.startedAt - a.startedAt || b.id.localeCompare(a.id));
  }

  save(record) {
    const target = path.join(this.directory, record.id + RECORD_SUFFIX);
    const temporary = `${target}.${randomUUID()}.tmp`;
    // Redact values before JSON encoding. Redacting the encoded document can
    // consume its closing quotes when a spoken credential ends a string.
    const safe = JSON.parse(JSON.stringify(record, (_key, value) =>
      typeof value === 'string' ? redactText(value, { secrets: this.secrets }) : value));
    try {
      fs.writeFileSync(temporary, JSON.stringify(safe, null, 2));
      fs.renameSync(temporary, target);
    } finally {
      fs.rmSync(temporary, { force: true });
    }
    const older = this.list().filter(item => item.id !== record.id);
    for (const item of older.slice(this.limit - 1)) fs.unlinkSync(path.join(this.directory, item.id + RECORD_SUFFIX));
    return safe;
  }
}

/** Best-effort preparation is disposable; call beginPlayback before playing so a started sentence can finish. */
export function createStepSpeech({ speak, now = Date.now, minIntervalMs = VOICE_JOB_SPEAK_MIN_INTERVAL_MS, gapMs = VOICE_SPEECH_GAP_MS, maxPlaybackMs = VOICE_PROGRESS_PLAYBACK_MAX_MS, isPlaying = () => false } = {}) {
  let pending = null;
  let controller = null;
  let lastStarted = -Infinity;
  let active = null;
  let queued = null, queueTimer = null, finishing = false, previousUpdate = '';
  const clearQueue = () => { queued = null; clearTimeout(queueTimer); queueTimer = null; };
  const pump = () => {
    if (!queued || pending || finishing) return;
    const delay = Math.max(isPlaying() ? VOICE_PROGRESS_POLL_MS : 0, minIntervalMs - (now() - lastStarted));
    if (delay) {
      clearTimeout(queueTimer); queueTimer = setTimeout(() => { queueTimer = null; pump(); }, delay); queueTimer.unref?.(); return;
    }
    const item = queued; queued = null; speech.offer(item);
  };
  const speech = {
    offer(text) {
      if (!speak || finishing || queued || pending || isPlaying() || now() - lastStarted < minIntervalMs) return false;
      lastStarted = now();
      controller = new AbortController();
      const state = { playing: false, controller };
      active = state;
      const { signal } = controller;
      let work;
      let playbackTimer;
      const beginPlayback = line => {
        if (signal.aborted || (line && line === previousUpdate)) return false;
        if (typeof line === 'string') previousUpdate = line;
        state.playing = true;
        playbackTimer = setTimeout(() => state.controller.abort(), maxPlaybackMs);
        return true;
      };
      const event = text && typeof text === 'object' ? { ...text, previousUpdate } : text;
      try { work = Promise.resolve(speak(event, { signal, beginPlayback })).catch(() => {}).then(async () => {
        if (state.playing && !signal.aborted && gapMs > 0) await new Promise(resolve => {
          const finish = () => { clearTimeout(timer); signal.removeEventListener('abort', finish); resolve(); };
          const timer = setTimeout(finish, gapMs);
          signal.addEventListener('abort', finish, { once: true });
        });
      }); }
      catch { work = Promise.resolve(); }
      // Synthesis may ignore AbortSignal. Detach it on interruption so optional
      // speech cannot hold a completed/cancelled task open until a network timeout.
      // The playback callback still receives this signal and must reject stale audio.
      pending = new Promise(resolve => {
        const finish = () => { signal.removeEventListener('abort', finish); resolve(); };
        signal.addEventListener('abort', finish, { once: true });
        if (signal.aborted) finish();
        void work.then(finish);
      });
      const current = pending;
      void current.finally(() => { clearTimeout(playbackTimer); if (pending === current) { pending = null; active = null; pump(); } });
      return true;
    },
    refresh(text) {
      if (!speak || finishing) return false;
      queued = text;
      if (active && !active.playing) active.controller.abort();
      pump(); return true;
    },
    interrupt() { clearQueue(); controller?.abort(); },
    async drain() { await pending; },
    async finish({ cancelled = false, final = false } = {}) {
      finishing = final; clearQueue();
      if (cancelled || !active?.playing) speech.interrupt();
      await speech.drain();
    },
  };
  return speech;
}

class VoiceTask {
  constructor({ store, transcript, language = '', confidence = null, onUpdate, now = Date.now, onApproval }) {
    this.store = store;
    this.now = now;
    this.onUpdate = onUpdate;
    this.onApproval = onApproval;
    this.record = { id: randomUUID(), transcript, language, confidence, status: 'queued', steps: [],
      startedAt: now(), endedAt: null, summary: '', error: null };
    this.persist();
  }

  persist() {
    this.store.save(this.record);
    // Display failures must never change whether an action is allowed.
    try { this.onUpdate?.(this.store.get(this.record.id)); } catch {}
  }

  start() { this.record.status = 'running'; this.persist(); }

  async approval(tool, ask) {
    if (FINAL_STATES.has(this.record.status)) return false;
    this.record.status = 'waiting_for_approval';
    this.persist();
    await this.onApproval?.();
    try { return await ask(tool); }
    finally {
      if (!FINAL_STATES.has(this.record.status)) { this.record.status = 'running'; this.persist(); }
    }
  }

  onToolCall(call) {
    if (FINAL_STATES.has(this.record.status) || this.record.steps.some(step => step.callId === call.id)) return;
    const tool = call.function?.name || 'tool';
    this.record.steps.push({ index: this.record.steps.length + 1, callId: call.id, label: voiceStepLabel(tool), tool, state: 'running' });
    this.persist();
  }

  onToolResult(call, result, verdict) {
    if (FINAL_STATES.has(this.record.status)) return;
    const step = this.record.steps.find(item => item.callId === call.id);
    if (!step) return;
    step.state = verdict?.ok === false || isToolFailure(result) ? 'failed' : 'done';
    this.persist();
  }

  finish(outcome) {
    const cancelled = outcome.error === TASK_ERRORS.cancelled;
    const error = outcome.error || (!outcome.text?.trim() ? TASK_ERRORS.empty : null) ||
      (this.record.steps.some(step => step.state !== 'done') ? TASK_ERRORS.steps : null);
    this.record.status = cancelled ? 'cancelled' : error ? 'failed' : 'done';
    this.record.error = error;
    this.record.summary = outcome.text || '';
    this.record.endedAt = this.now();
    for (const step of this.record.steps) if (step.state === 'running') step.state = cancelled ? 'cancelled' : 'failed';
    this.persist();
  }
}

/** One agent turn, with a durable observer. No invented JSON plan or second agent. */
export async function runVoiceTask({ store, transcript, language, confidence, run, onUpdate, speak, minIntervalMs, gapMs, waitUpdateMs = VOICE_JOB_WAIT_UPDATE_MS, isPlaying, now = Date.now, onTrackingError, signal, isCancelled = () => false }) {
  const speech = createStepSpeech({ speak, minIntervalMs, gapMs, isPlaying, now });
  const task = new VoiceTask({ store, transcript, language, confidence, onUpdate, now, onApproval: () => speech.finish() });
  task.interruptSpeech = () => speech.interrupt();
  task.start();
  const contexts = new Map(); // Per-job ephemeral labels; raw arguments/results never enter saved records.
  const steps = () => task.record.steps.filter(step => !SILENT_TOOLS.has(step.tool)).map(step => ({ ...contexts.get(step.callId), state: step.state }));
  const event = (kind, call, phase) => ({ kind, transcript, phase, action: call && { ...contexts.get(call.id) }, steps: steps() });
  const cancelSpeech = () => speech.interrupt();
  signal?.addEventListener('abort', cancelSpeech, { once: true });
  const waitTimer = speak ? setInterval(() => {
    if (task.record.status === 'running') speech.offer({ ...event('waiting'), elapsedMs: now() - task.record.startedAt });
  }, waitUpdateMs) : null;
  waitTimer?.unref();
  let outcome;
  let storageError;
  const observe = action => {
    // Agent UI hooks intentionally swallow exceptions. Remember persistence failures
    // so an interrupted audit trail cannot later appear as a completed task.
    try { action(); } catch (error) { storageError ||= error; onTrackingError?.(error); throw error; }
  };
  try {
    outcome = await run({
      onToolCall: call => observe(() => {
        if (contexts.has(call.id) || FINAL_STATES.has(task.record.status)) return;
        task.onToolCall(call);
        contexts.set(call.id, voiceActionContext(call));
        if (task.record.status === 'running' && !SILENT_TOOLS.has(call.function?.name)) speech.refresh({ ...event('step', call, 'started'), call: { id: call.id, function: { name: call.function?.name } } });
      }),
      onToolResult: (call, result, verdict) => observe(() => {
        if (task.record.steps.find(item => item.callId === call.id)?.state !== 'running') return;
        task.onToolResult(call, result, verdict);
        const step = task.record.steps.find(item => item.callId === call.id);
        const context = contexts.get(call.id);
        if (!step || !context) return;
        context.confirmation = voiceResultConfirmation(context, step.state, result, verdict);
        const phase = context.confirmation === 'submitted' ? 'submitted' : step.state === 'failed' ? 'failed' : 'completed';
        if (task.record.status === 'running' && !SILENT_TOOLS.has(context.tool)) speech.refresh(event('step_result', call, phase));
      }),
    }, task);
    if (storageError) throw storageError;
    outcome ||= {};
  } catch (error) {
    outcome = { text: '', error: error.name === 'AbortError' ? TASK_ERRORS.cancelled : error.message };
  } finally {
    clearInterval(waitTimer);
    await speech.finish({ cancelled: outcome?.error === TASK_ERRORS.cancelled || signal?.aborted || isCancelled(), final: true });
    signal?.removeEventListener('abort', cancelSpeech);
  }
  if (signal?.aborted || isCancelled()) outcome = { ...outcome, error: TASK_ERRORS.cancelled };
  task.finish(outcome);
  return { task: store.get(task.record.id), outcome };
}

export function renderVoiceTask(task) {
  const heading = `[voice task ${task.id}] ${task.status}`;
  const lines = [heading, `Heard: ${cleanLine(task.transcript)}`,
    ...task.steps.map(step => `  ${step.index}. [${step.state}] ${cleanLine(step.label)}`)];
  if (task.summary) lines.push(`Report: ${cleanLine(task.summary)}`);
  if (task.error) lines.push(`Error: ${cleanLine(task.error)}`);
  return lines.join('\n');
}

/** A failed/denied action must remain audible even if the planner overclaims success. */
export function voiceTaskReport(task) {
  if (task.status === 'cancelled') return 'Cancelled.';
  if (task.status === 'failed') return `Work did not finish. ${task.error || ''} ${task.summary || ''}`.trim();
  return task.summary || '';
}

export function voiceTaskCommand(text, store) {
  const [command, id, ...extra] = String(text).trim().split(/\s+/);
  if (command !== VOICE_TASK_COMMAND) return null;
  if (extra.length) return `Usage: ${VOICE_TASK_COMMAND} [id]`;
  if (id) {
    const record = store.get(id);
    return record ? renderVoiceTask(record) : `No voice task "${cleanLine(id)}".`;
  }
  const records = store.list();
  return records.length ? records.map(record => `[voice task ${record.id}] ${record.status} · ${cleanLine(record.transcript)}`).join('\n')
    : 'No voice tasks saved yet. Use /voice to speak a request.';
}
