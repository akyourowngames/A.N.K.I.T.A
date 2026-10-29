import { VOICE_ACTIONS } from '../shared/voice.mjs';
const THREAD_ID_CHARS = 200; // Characters: bound IPC ownership identifiers before lookup.

/** The renderer can name an existing owner, never send credentials or executable configuration. */
export async function runVoiceAction({ engine, action, payload, focus = () => {} }) {
  if (payload != null && (typeof payload !== 'object' || Array.isArray(payload))) throw new Error('Invalid voice payload.');
  const allowed = action === VOICE_ACTIONS.start ? ['threadId'] : action === VOICE_ACTIONS.focus ? ['settings'] : action === VOICE_ACTIONS.cancel ? ['taskId', 'all'] : action === VOICE_ACTIONS.status ? ['refresh'] : [];
  if (Object.keys(payload || {}).some(key => !allowed.includes(key))) throw new Error('Invalid voice payload.');
  if (payload && Object.hasOwn(payload, 'settings') && typeof payload.settings !== 'boolean') throw new Error('Invalid voice payload.');
  if (payload && Object.hasOwn(payload, 'refresh') && typeof payload.refresh !== 'boolean') throw new Error('Invalid voice payload.');
  if (action === VOICE_ACTIONS.cancel && payload && (
    (Object.hasOwn(payload, 'all') && payload.all !== true) ||
    (Object.hasOwn(payload, 'taskId') && (typeof payload.taskId !== 'string' || !payload.taskId.trim() || payload.taskId.length > THREAD_ID_CHARS || /[\x00-\x1f]/.test(payload.taskId))) ||
    (payload.taskId && payload.all))) throw new Error('Invalid voice payload.');
  if (action === VOICE_ACTIONS.start) {
    const id = payload?.threadId;
    if (typeof id !== 'string' || !id.trim() || id.length > THREAD_ID_CHARS || /[\x00-\x1f]/.test(id)) throw new Error('Choose a valid conversation for voice.');
    return engine.voice().start({ threadId: id });
  }
  if (action === VOICE_ACTIONS.status) return engine.voice().status(payload);
  const voice = engine.voice();
  switch (action) {
    case VOICE_ACTIONS.snapshot: return voice.snapshot();
    case VOICE_ACTIONS.test: return voice.testPlayback();
    case VOICE_ACTIONS.end: return voice.end();
    case VOICE_ACTIONS.pause: return voice.pause();
    case VOICE_ACTIONS.resume: return voice.resume();
    case VOICE_ACTIONS.cancel: return voice.cancelWork(payload);
    case VOICE_ACTIONS.focus: await focus(voice.snapshot(), { settings: payload?.settings === true }); return voice.snapshot();
    default: throw new Error('Unknown voice action.');
  }
}
