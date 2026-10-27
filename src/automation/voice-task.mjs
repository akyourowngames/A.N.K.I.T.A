import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { stripVTControlCharacters } from 'node:util';
import { redactText } from '../core/redact.mjs';
import { isToolFailure } from '../core/verify.mjs';
import { VOICE_TASK_COMMAND } from '../core/commands.mjs';
import { VOICE_TASK_LIMIT, VOICE_JOB_SPEAK_MIN_INTERVAL_MS } from './voice-task-policy.mjs';

export { VOICE_TASK_COMMAND };
const RECORD_SUFFIX = '.json';
const ID_PATTERN = /^[a-f\d-]{36}$/i; // UUIDs only: command arguments cannot escape the task directory.
const FINAL_STATES = new Set(['done', 'failed', 'cancelled']);
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

/** Progress is best effort, never queued, and cannot overlap itself or an acknowledgement. */
export function createStepSpeech({ speak, now = Date.now, minIntervalMs = VOICE_JOB_SPEAK_MIN_INTERVAL_MS, isPlaying = () => false } = {}) {
  let pending = null;
  let controller = null;
  let lastStarted = -Infinity;
  return {
    offer(text) {
      if (!speak || pending || isPlaying() || now() - lastStarted < minIntervalMs) return false;
      lastStarted = now();
      controller = new AbortController();
      const { signal } = controller;
      let work;
      try { work = Promise.resolve(speak(text, { signal })).catch(() => {}); }
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
      void current.finally(() => { if (pending === current) pending = null; });
      return true;
    },
    interrupt() { controller?.abort(); },
    async drain() { await pending; },
  };
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
    this.onApproval?.();
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
export async function runVoiceTask({ store, transcript, language, confidence, run, onUpdate, speak, minIntervalMs, isPlaying, now, onTrackingError }) {
  const speech = createStepSpeech({ speak, minIntervalMs, isPlaying, now });
  const task = new VoiceTask({ store, transcript, language, confidence, onUpdate, now, onApproval: () => speech.interrupt() });
  task.start();
  let outcome;
  let storageError;
  const observe = action => {
    // Agent UI hooks intentionally swallow exceptions. Remember persistence failures
    // so an interrupted audit trail cannot later appear as a completed task.
    try { action(); } catch (error) { storageError ||= error; onTrackingError?.(error); throw error; }
  };
  try {
    outcome = await run({
      onToolCall: call => observe(() => { task.onToolCall(call); speech.offer(voiceStepLabel(call.function?.name)); }),
      onToolResult: (call, result, verdict) => observe(() => task.onToolResult(call, result, verdict)),
    }, task);
    if (storageError) throw storageError;
    outcome ||= {};
  } catch (error) {
    outcome = { text: '', error: error.name === 'AbortError' ? TASK_ERRORS.cancelled : error.message };
  } finally {
    speech.interrupt();
    await speech.drain();
  }
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
