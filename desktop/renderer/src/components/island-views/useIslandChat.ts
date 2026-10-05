import { useCallback, useEffect, useRef, useState } from 'react';
import type { EngineEvent, Teammate } from '../../../../shared/wire';
import { hydrateIslandState, reduceIslandState, type IslandSnapshot, type IslandState } from '../../../../shared/island-state.mjs';
import { playSound } from '../../island/sound';
import { useCompanionDrafts } from '../../lib/useCompanionDrafts';
import { EMPTY_COMPANION_DRAFT } from '../../../../shared/companion-drafts.mjs';
import { CAPTURE_UI_EVENTS } from '../../../../browser-helper/protocol.mjs';

const EMPTY_DRAFT = EMPTY_COMPANION_DRAFT;
const EMPTY_STATE: IslandState = { threads: {} };
export type IslandChat = ReturnType<typeof useIslandChat>;

// Live events and drafts belong to the island, so changing tabs or teammates preserves them.
export function useIslandChat() {
  const [state, setState] = useState<IslandState>(EMPTY_STATE);
  const [teammates, setTeammates] = useState<Teammate[]>([]);
  const [teammateId, setTeammateId] = useState<string | null>(null);
  const captured = useCallback((item: import('../../../../shared/wire').CompanionCaptureItem) => {
    setTeammateId(item.threadId);
    window.dispatchEvent(new CustomEvent(CAPTURE_UI_EVENTS.island));
  }, []);
  const { drafts, store, addFiles: readFiles } = useCompanionDrafts('island', captured);
  const [loading, setLoading] = useState(true);
  const [connectionError, setConnectionError] = useState('');
  const [pending, setPending] = useState<string[]>([]);
  const pendingRef = useRef(new Set<string>());
  const stateRef = useRef(state);
  stateRef.current = state;
  const aliveRef = useRef(false);

  useEffect(() => {
    let alive = true, ready = false;
    const queued: EngineEvent[] = [];
    aliveRef.current = true;
    const off = window.ankita.onEvent(event => {
      if (!alive) return;
      if (event.type === 'teammates-changed') {
        void window.ankita.invoke<Teammate[]>('listTeammates').then(list => {
          if (alive) setTeammates(list);
        }).catch(error => { if (alive) setConnectionError(String(error.message || error)); });
      }
      if (!ready) queued.push(event);
      else setState(current => reduceIslandState(current, event));
      if (event.type === 'turn-start' || event.type === 'turn-end') {
        pendingRef.current.delete(event.threadId);
        setPending([...pendingRef.current]);
      }
    });
    void window.ankita.invoke<IslandSnapshot>('islandSnapshot').then(snapshot => {
      if (!alive) return;
      ready = true;
      setTeammates(snapshot.teammates);
      setState(hydrateIslandState(snapshot, queued));
      setTeammateId(current => current || snapshot.threads.find(thread => thread.running)?.id || snapshot.teammates[0]?.id || null);
      setLoading(false);
    }).catch(error => {
      if (!alive) return;
      ready = true;
      setState(current => queued.reduce(reduceIslandState, current));
      setConnectionError(String(error.message || error));
      setLoading(false);
    });
    return () => { alive = false; aliveRef.current = false; off(); };
  }, []);

  useEffect(() => {
    if (!loading && !teammates.some(teammate => teammate.id === teammateId)) setTeammateId(teammates[0]?.id || null);
  }, [teammates, teammateId, loading]);

  const updateDraft = store.update.bind(store);
  const draft = teammateId ? drafts[teammateId] || EMPTY_DRAFT : EMPTY_DRAFT;
  const thread = teammateId ? state.threads[teammateId] : undefined;
  const sending = Boolean(teammateId && pending.includes(teammateId));
  const thinking = thread?.running === true;
  const setInput = useCallback((text: string) => {
    if (teammateId) updateDraft(teammateId, current => ({ ...current, text }));
  }, [teammateId, updateDraft]);

  const addFiles = async (files: File[], id = teammateId) => {
    if (!id) return;
    const { readFile } = await import('../Composer');
    const result = await readFiles(id, files, readFile);
    if (result.accepted) playSound('attach');
    return result;
  };

  const removeFile = (index: number) => {
    if (teammateId) updateDraft(teammateId, current => ({ ...current, files: current.files.filter((_, i) => i !== index) }));
  };
  const submit = useCallback(async () => {
    const id = teammateId;
    if (!id || pendingRef.current.has(id) || store.get(id).reading || stateRef.current.threads[id]?.running) return;
    const text = draft.text.trim();
    if (!text && !draft.files.length) return;
    pendingRef.current.add(id);
    setPending([...pendingRef.current]);
    updateDraft(id, current => ({ ...current, error: '' }));
    try {
      await window.ankita.invoke('send', { id, text, surface: 'island', attachments: draft.files.map(({ name, data, kind, images }) => ({ name, data, kind, images })) });
      if (aliveRef.current) updateDraft(id, () => EMPTY_DRAFT);
      playSound('send');
    } catch (error) {
      if (aliveRef.current) updateDraft(id, current => ({ ...current, error: error instanceof Error ? error.message : String(error) }));
    } finally {
      pendingRef.current.delete(id);
      if (aliveRef.current) setPending([...pendingRef.current]);
    }
  }, [teammateId, draft, updateDraft]);
  const stop = async () => {
    if (!teammateId) return;
    try { await window.ankita.invoke('cancel', { id: teammateId }); }
    catch (error) { updateDraft(teammateId, current => ({ ...current, error: error instanceof Error ? error.message : String(error) })); }
  };

  return { state, teammates, teammateId, selectTeammate: setTeammateId,
    teammateName: teammates.find(item => item.id === teammateId)?.name || 'Ankita',
    log: thread?.log || [], thinking, sending, loading,
    error: draft.error || thread?.error || connectionError,
    input: draft.text, setInput, attachments: draft.files, addFiles, removeFile,
    reading: draft.reading, submit, stop };
}
