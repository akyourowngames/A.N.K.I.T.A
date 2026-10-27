/** Public desktop voice protocol. Audio and credentials stay in the main process. */
export const VOICE_EVENT = 'voice-state';
export const VOICE_API_REQUIRED_MESSAGE = 'Voice needs an API-backed conversation. Choose a model in Settings first.'; // Shared setup guard for status, session start and direct engine calls.
export const VOICE_ACTIONS = Object.freeze({ status: 'voiceStatus', start: 'voiceStart', end: 'voiceEnd',
  pause: 'voicePause', resume: 'voiceResume', cancel: 'voiceCancel', focus: 'voiceShowMain' });
export const VOICE_CAPTION_CHARS = 1200; // Characters: bound a displayed utterance; the full transcript stays in chat.
export const VOICE_UPDATE_CHARS = 240; // Characters: one current work update, not a raw tool dump.
export const VOICE_ERROR_CHARS = 360; // Characters: keep an actionable error readable in the island.
export const VOICE_DEVICE_CHARS = 200; // Characters: friendly OS audio-device name.
export const VOICE_METER_INTERVAL_MS = 80; // Milliseconds: cap state traffic while keeping the orb responsive.
export const VOICE_BARGE_GUARD_MS = 400; // Milliseconds: ignore playback-start transients before accepting interruption.
export const VOICE_POLL_MS = 80; // Milliseconds: react promptly to VAD and cancellation without a busy loop.
export const VOICE_PHASE_LABELS = Object.freeze({ idle: 'Voice', starting: 'Getting ready', listening: 'Listening',
  transcribing: 'Transcribing', working: 'Working', speaking: 'Speaking', approval: 'Permission needed', paused: 'Paused', error: 'Voice needs attention' });
const CAPTION_ROLES = new Set(['user', 'assistant']);
const text = (value, limit) => String(value ?? '').slice(0, limit);

export function emptyVoiceState() {
  return { sessionId: null, threadId: null, active: false, paused: false, phase: 'idle', caption: '', captionRole: 'assistant',
    update: '', inputLevel: 0, task: null, error: null, microphone: '', revision: 0 };
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
  next.revision = state.revision + 1;
  return next;
}
