import { useCallback, useEffect, useRef, useState } from 'react';
import type { VoiceState, VoiceStatus } from '../../../../shared/voice.mjs';
import { emptyVoiceState, VOICE_ACTIONS, VOICE_EVENT } from '../../../../shared/voice.mjs';
import { cleanErrorMessage } from '../../../../shared/error-notices.mjs';

/** Audio stays in main; mounted windows observe the same monotonically versioned state. */
export function useVoice() {
  const [state, setState] = useState<VoiceState>(emptyVoiceState);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const alive = useRef(false);
  const apply = useCallback((next: VoiceState | undefined) => {
    // Older/minimal bridges can omit this optional capability; never put an invalid snapshot in React state.
    if (!next || !Number.isSafeInteger(next.revision)) return;
    if (alive.current) setState(current => next.revision >= current.revision ? next : current);
  }, []);
  useEffect(() => {
    alive.current = true;
    if (!window.ankita) return;
    const off = window.ankita.onEvent(event => { if (event.type === VOICE_EVENT) apply(event.state); });
    // Subscribe before taking a snapshot, so a slow device check cannot roll back newer events.
    void window.ankita.invoke<VoiceStatus>(VOICE_ACTIONS.status).then(result => apply(result.state)).catch(() => {});
    return () => { alive.current = false; off(); };
  }, [apply]);
  const act = useCallback(async (action: string, payload?: { threadId?: string; settings?: boolean; taskId?: string; all?: boolean }) => {
    setBusy(true); setError('');
    try { const next = await window.ankita.invoke<VoiceState>(action, payload); apply(next); return next; }
    catch (cause) { if (alive.current) setError(cleanErrorMessage(cause)); return null; }
    finally { if (alive.current) setBusy(false); }
  }, [apply]);
  return { state, error, busy, act,
    start: (threadId: string) => act(VOICE_ACTIONS.start, { threadId }),
    end: () => act(VOICE_ACTIONS.end), pause: () => act(VOICE_ACTIONS.pause), resume: () => act(VOICE_ACTIONS.resume),
    cancel: (taskId?: string) => act(VOICE_ACTIONS.cancel, taskId ? { taskId } : { all: true }), focus: (settings = false) => act(VOICE_ACTIONS.focus, settings ? { settings: true } : undefined) };
}
