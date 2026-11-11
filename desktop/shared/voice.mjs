/** Public desktop voice protocol. Audio and credentials stay in the main process. */
import { VOICE_FINAL_STATES, VOICE_TASK_LIMIT, VOICE_BARGE_GUARD_MS, VOICE_REPORT_ACTIONS } from '../../src/automation/voice-task-policy.mjs';
export { VOICE_BARGE_GUARD_MS };
export const VOICE_EVENT = 'voice-state';
export const VOICE_API_REQUIRED_MESSAGE = 'Voice needs an API-backed conversation. Choose a model in Settings first.'; // Shared setup guard for status, session start and direct engine calls.
export const VOICE_ACTIONS = Object.freeze({ status: 'voiceStatus', snapshot: 'voiceSnapshot', start: 'voiceStart', end: 'voiceEnd',
  pause: 'voicePause', resume: 'voiceResume', cancel: 'voiceCancel', focus: 'voiceShowMain', test: 'voiceTestPlayback', speech: 'voiceSpeechControl' });
export const VOICE_SPEECH_ACTIONS = Object.freeze({ stop: 'stop', resume: VOICE_REPORT_ACTIONS.resume, repeat: VOICE_REPORT_ACTIONS.repeat, dismiss: VOICE_REPORT_ACTIONS.dismiss }); // Separate speech control from task cancellation.
export const VOICE_SPEECH_ERRORS = Object.freeze({ invalid: 'Invalid speech control.', missing: 'This report has expired. Choose a current report.' }); // Shared validation copy for the local dispatcher and audio owner.
export const VOICE_LOCAL_ACTIONS = Object.freeze({ ...VOICE_SPEECH_ACTIONS, pause: 'pause', status: 'status' }); // Controls that never require a planner.
const LOCAL_CONTROL_PHRASES = new Map(Object.entries({
  status: ['status', 'what is the status', 'what is the progress', 'how is it going', 'are you still working', 'what are you working on'],
  resume: ['continue', 'continue speaking', 'continue the report', 'resume speaking', 'resume the report'],
  repeat: ['repeat that', 'repeat the report', 'say that again'],
  dismiss: ['skip the report', 'skip this report', 'skip that report'],
  stop: ['stop speaking', 'stop talking', 'be quiet'],
  pause: ['pause listening', 'pause the microphone', 'mute the microphone', 'mute your microphone'],
}).flatMap(([action, phrases]) => phrases.map(phrase => [phrase, action]))); // Whole utterances only: mixed requests still need the planner.
const REPORT_STATES = new Set(['queued', 'speaking', 'suspended', 'delivered', 'dismissed', 'unavailable']); // Public queue states, never private clips or text.
const DELIVERY_MODES = new Set(['pending', 'streaming', 'buffered', 'cached']); // Observed audio delivery, not a prediction of provider readiness.
const DELIVERY_FALLBACKS = new Set(['provider', 'runtime']); // Capability reason only; never raw provider responses.
export const VOICE_CAPTION_CHARS = 1200; // Characters: bound a displayed utterance; the full transcript stays in chat.
export const VOICE_UPDATE_CHARS = 240; // Characters: one current work update, not a raw tool dump.
export const VOICE_ERROR_CHARS = 360; // Characters: keep an actionable error readable in the island.
export const VOICE_DEVICE_CHARS = 200; // Characters: friendly OS audio-device name.
export const VOICE_METER_INTERVAL_MS = 80; // Milliseconds: cap state traffic while keeping the orb responsive.
export const VOICE_POLL_MS = 80; // Milliseconds: react promptly to VAD and cancellation without a busy loop.
export const VOICE_PUBLIC_JOBS = VOICE_TASK_LIMIT; // Rows: shared history bound, with active work reserved first.
export const VOICE_PHASE_LABELS = Object.freeze({ idle: 'Voice', starting: 'Getting ready', listening: 'Listening',
  standby: 'Say Ankita', transcribing: 'Transcribing', working: 'Working', speaking: 'Speaking',
  approval: 'Permission needed', paused: 'Paused', error: 'Voice needs attention' });
export const VOICE_WAKE_PHRASE = 'ankita'; // Lowercase single token: the only phrase that wakes standby listening.
// Whole-utterance stop phrases. A command that merely contains one of these words
// ("stop by the store") is not a stop, so matching is exact, not a search.
const VOICE_STOP_PHRASES = new Set(['stop', 'stop it', 'stop that', 'cancel', 'cancel that', 'never mind', 'nevermind']);
// "mode"/"session" are optional suffixes people say: "exit voice mode", "end the session".
const VOICE_END_PHRASES = new Set(['exit', 'quit', 'end', 'end voice', 'exit voice', 'leave', 'leave voice', 'goodbye', 'bye']);
const VOICE_MODE_SUFFIXES = new Set(['mode', 'session']);
const VOICE_ARTICLES = new Set(['the', 'a', 'an', 'this', 'my']);
const VOICE_GREETINGS = new Set(['hi', 'hey', 'hello', 'ok', 'okay', 'yo']); // Optional lead-in before the wake word.
const VOICE_PUNCTUATION = /[.!?,;:'"“”‘’]/g; // Stripped before matching so "Ankita!" still wakes.
const VOICE_EDGE_PUNCTUATION = /^[.!?,;:"“”‘’]+|[.!?,;:]+$/g; // Keeps an internal apostrophe: "Ankita's" is not the wake word.
const VOICE_WAKE_SEPARATORS = /^[\s,.:;-]+/; // Characters allowed between the wake word and the command.
const CAPTION_ROLES = new Set(['user', 'assistant']);
const normalizeCommand = value => String(value ?? '').replace(VOICE_PUNCTUATION, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
const commandWords = value => normalizeCommand(value).split(' ').filter(Boolean);
// Words with only leading/trailing punctuation removed, so possessives stay distinct.
const edgeWord = word => word.replace(VOICE_EDGE_PUNCTUATION, '').toLowerCase();

/** Called only after the attention/wake gate; no substring matching of app commands. */
export const voiceLocalControl = value => LOCAL_CONTROL_PHRASES.get(normalizeCommand(value)) || null;

/**
 * Classify one transcript inside a voice session. Pure and shared so the desktop
 * loop, the CLI and the tests agree on the exact phrases.
 *
 * - end:     leave voice mode
 * - stop:    interrupt speech / cancel the running job
 * - wake:    the wake word alone, no command attached
 * - command: an actionable request, with any wake prefix removed
 * - ignored: not addressed to Ankita while asleep (dropped, never shown)
 *
 * `listening` describes the current attention level: awake, any unmatched text is
 * a command; asleep, only the wake word (alone or with a command) is acted on.
 */
export function voiceCommand(value, { wake = true, stop = true, listening = true } = {}) {
  const words = commandWords(value);
  if (!words.length) return { kind: 'ignored', text: '' };
  // Accept "exit voice mode", "end the session": drop an optional article and an
  // optional "mode"/"session" tail before comparing end phrases.
  const trimEnd = list => {
    const tail = VOICE_MODE_SUFFIXES.has(list.at(-1)) ? list.slice(0, -1) : list;
    return VOICE_ARTICLES.has(tail.at(-1)) ? tail.slice(0, -1) : tail;
  };
  if (VOICE_END_PHRASES.has(trimEnd(words).join(' '))) return { kind: 'end', text: '' };
  if (stop && VOICE_STOP_PHRASES.has(words.join(' '))) return { kind: 'stop', text: '' };
  // The wake word may be preceded by a greeting ("Hi Ankita"), and must be its
  // own word ("Ankita's Notes" is a command, not a wake).
  if (wake) {
    // Match on edge-trimmed words (so "Ankita!" wakes, "Ankita's" does not) but
    // slice the ORIGINAL words, keeping the user's own punctuation after it.
    const raw = String(value ?? '').trim().split(/\s+/).filter(Boolean);
    const lead = raw.map(edgeWord);
    const wakeIndex = lead[0] === VOICE_WAKE_PHRASE ? 0 : VOICE_GREETINGS.has(lead[0]) && lead[1] === VOICE_WAKE_PHRASE ? 1 : -1;
    if (wakeIndex >= 0) {
      const remainder = raw.slice(wakeIndex + 1).join(' ').replace(VOICE_WAKE_SEPARATORS, '').trim();
      return remainder ? { kind: 'command', text: remainder } : { kind: 'wake', text: '' };
    }
  }
  if (!listening) return { kind: 'ignored', text: '' };
  return { kind: 'command', text: String(value ?? '').trim() };
}
const text = (value, limit) => String(value ?? '').slice(0, limit);
export const voiceTaskActive = task => Boolean(task && (task.resourcesHeld || !VOICE_FINAL_STATES.includes(task.status)));
export const VOICE_PUBLIC_STEPS = 12; // Rows/job: recent real actions without an unbounded cross-window transcript.
const publicTask = task => task && typeof task.id === 'string' ? {
  id: text(task.id, VOICE_DEVICE_CHARS), label: text(task.label, VOICE_UPDATE_CHARS), status: text(task.status, VOICE_UPDATE_CHARS),
  summary: text(task.summary, VOICE_CAPTION_CHARS), error: task.error ? text(task.error, VOICE_ERROR_CHARS) : null,
  waitingFor: task.waitingFor ? text(task.waitingFor, VOICE_UPDATE_CHARS) : null, resourcesHeld: Boolean(task.resourcesHeld),
  // Set when a child process outlived the hold ceiling: the job is finished, the
  // program is still running. Voice is free again.
  holdExpired: Boolean(task.holdExpired),
  steps: Array.isArray(task.steps) ? task.steps.slice(-VOICE_PUBLIC_STEPS).map(step => ({ index: step.index,
    label: text(step.label, VOICE_UPDATE_CHARS), tool: text(step.tool, VOICE_UPDATE_CHARS), state: text(step.state, VOICE_UPDATE_CHARS) })) : [],
} : null;

export function emptyVoiceState() {
  return { sessionId: null, threadId: null, active: false, paused: false, phase: 'idle', caption: '', captionRole: 'assistant',
    update: '', inputLevel: 0, task: null, jobs: [], error: null, microphone: '', wakeCue: 0, revision: 0,
    bargeIn: false, delivery: { mode: 'pending', fallback: '', firstChunkMs: null }, speech: { turn: 0, speaking: false, reports: [] } };
}

/** Only explicit public fields can enter snapshots; unknown fields cannot leak secrets. */
export function voiceStatePatch(state, patch) {
  const next = { ...state };
  for (const key of Object.keys(emptyVoiceState())) if (Object.hasOwn(patch, key)) next[key] = patch[key];
  next.phase = Object.hasOwn(VOICE_PHASE_LABELS, next.phase) ? next.phase : state.phase;
  next.captionRole = CAPTION_ROLES.has(next.captionRole) ? next.captionRole : state.captionRole;
  next.active = Boolean(next.active); next.paused = Boolean(next.paused);
  next.caption = text(next.caption, VOICE_CAPTION_CHARS);
  next.update = text(next.update, VOICE_UPDATE_CHARS);
  next.error = next.error ? text(next.error, VOICE_ERROR_CHARS) : null;
  next.microphone = text(next.microphone, VOICE_DEVICE_CHARS);
  next.inputLevel = Number.isFinite(next.inputLevel) ? Math.max(0, Math.min(1, next.inputLevel)) : 0;
  // A timestamp the renderer watches for change; it drives one wake animation.
  next.wakeCue = Number.isFinite(next.wakeCue) ? Math.max(0, next.wakeCue) : 0;
  const jobs = Array.isArray(next.jobs) ? next.jobs.map(publicTask).filter(Boolean) : [];
  next.jobs = [...jobs.filter(voiceTaskActive), ...jobs.filter(job => !voiceTaskActive(job))].slice(0, VOICE_PUBLIC_JOBS);
  next.task = publicTask(next.task);
  next.bargeIn = Boolean(next.bargeIn);
  const delivery = next.delivery || {};
  next.delivery = { mode: DELIVERY_MODES.has(delivery.mode) ? delivery.mode : 'pending',
    fallback: DELIVERY_FALLBACKS.has(delivery.fallback) ? delivery.fallback : '',
    firstChunkMs: Number.isFinite(delivery.firstChunkMs) && delivery.firstChunkMs >= 0 ? Math.round(delivery.firstChunkMs) : null };
  const speech = next.speech || {};
  next.speech = { turn: Number.isSafeInteger(speech.turn) && speech.turn >= 0 ? speech.turn : 0, speaking: Boolean(speech.speaking),
    reports: (Array.isArray(speech.reports) ? speech.reports : []).filter(report => report && typeof report.id === 'string' && REPORT_STATES.has(report.state)).slice(-VOICE_PUBLIC_JOBS)
      .map(report => ({ id: text(report.id, VOICE_DEVICE_CHARS), label: text(report.label, VOICE_UPDATE_CHARS), state: report.state })) };
  next.revision = state.revision + 1;
  return next;
}
