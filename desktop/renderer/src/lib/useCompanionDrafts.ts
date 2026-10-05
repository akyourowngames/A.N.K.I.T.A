import { useEffect, useSyncExternalStore } from 'react';
import { CompanionDrafts } from '../../../shared/companion-drafts.mjs';
import type { CompanionCaptureItem } from '../../../shared/wire';
import { CAPTURE_ACTIONS, CAPTURE_EVENT, FILE_ACTIVITY_EVENT } from '../../../browser-helper/protocol.mjs';

const stores = { main: new CompanionDrafts(), island: new CompanionDrafts() }; // Per-surface drafts survive panel unmounts in each renderer.
export function useCompanionDrafts(surface: 'main' | 'island', onCapture?: (item: CompanionCaptureItem) => void) {
  const store = stores[surface];
  const drafts = useSyncExternalStore(store.subscribe, store.getSnapshot);
  useEffect(() => {
    let alive = true;
    const receive = (item: CompanionCaptureItem) => {
      if (!alive || item.surface !== surface) return;
      const known = store.hasReceipt(item.id);
      if (store.capture(item)) {
        void window.ankita.invoke(CAPTURE_ACTIONS.ack, { id: item.id }).catch(() => {});
        if (!known) {
          window.dispatchEvent(new CustomEvent(FILE_ACTIVITY_EVENT, { detail: { threadId: item.threadId, phase: 'success', label: item.attachment.name } }));
          onCapture?.(item);
        }
      }
    };
    let loadingInbox = false;
    const loadInbox = () => {
      if (loadingInbox || !alive) return;
      loadingInbox = true;
      void window.ankita.invoke<CompanionCaptureItem[]>(CAPTURE_ACTIONS.inbox).then(items => { if (alive && Array.isArray(items)) items.forEach(receive); }).catch(() => {}).finally(() => { loadingInbox = false; });
    };
    let counts = Object.fromEntries(Object.entries(store.getSnapshot()).map(([id,draft]) => [id,draft.files.length]));
    const offDrafts = store.subscribe(() => {
      const next = Object.fromEntries(Object.entries(store.getSnapshot()).map(([id,draft]) => [id,draft.files.length]));
      const freed = Object.keys(counts).some(id => (next[id] || 0) < counts[id]); counts = next;
      if (freed) loadInbox(); // Retry held captures only when space is freed, never on typing/streaming.
    });
    const off = window.ankita.onEvent(event => { if (event.type === CAPTURE_EVENT) receive(event.capture); });
    loadInbox();
    return () => { alive = false; off(); offDrafts(); };
  }, [surface, store, onCapture]);
  const addFiles = async (threadId: string, files: File[], reader: (file: File) => Promise<import('../../../shared/companion-drafts.mjs').DraftAttachment>) => {
    if (!files.length) return { accepted: 0, error: '' };
    if (store.get(threadId).reading) {
      const result = await store.read(threadId, files, reader);
      store.update(threadId, draft => ({ ...draft, error: result.error }));
      return result;
    }
    const label = files.length > 1 ? files.length + ' files' : files[0].name;
    window.dispatchEvent(new CustomEvent(FILE_ACTIVITY_EVENT, { detail: { threadId, phase: 'gulp', label } }));
    const result = await store.read(threadId, files, reader);
    window.dispatchEvent(new CustomEvent(FILE_ACTIVITY_EVENT, { detail: { threadId, phase: result.error ? 'error' : 'success', label } }));
    return result;
  };
  return { drafts, store, addFiles };
}
