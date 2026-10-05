import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react';
import { CAPTURE_ACTIONS, CAPTURE_EVENT, DRAG_MIME, PROTOCOL_VERSION, TICKET_TTL_MS, RECEIPT_MS } from '../../../browser-helper/protocol.mjs';

export type CaptureSetup = {address: string; code: string; instanceId: string; paired: number};
export function useMascotCapture() {
  const [setup, setSetup] = useState<CaptureSetup | null>(null);
  const [message, setMessage] = useState('');
  const ticket = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);
  const refresh = useCallback(async () => {
    try { const value = await window.ankita.invoke<CaptureSetup>(CAPTURE_ACTIONS.setup); if (alive.current) { setSetup(value); setMessage(''); } return value; }
    catch (error) { if (alive.current) setMessage(String((error as Error).message || error)); return null; }
  }, []);
  useEffect(() => {
    alive.current = true; void refresh();
    const off = window.ankita.onEvent(event => {
      if (event.type === CAPTURE_EVENT && event.capture.ticketId === ticket.current) {
        if (timer.current) clearTimeout(timer.current); ticket.current = null; setMessage('Page attached');
        timer.current = setTimeout(() => { if (alive.current) setMessage(''); }, RECEIPT_MS);
      }
    });
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape' && ticket.current) { void window.ankita.invoke(CAPTURE_ACTIONS.cancel, {ticketId:ticket.current}).catch(() => {}); ticket.current = null; if (timer.current) clearTimeout(timer.current); setMessage(''); } };
    const focus = () => { void refresh(); };
    window.addEventListener('keydown', escape); window.addEventListener('focus', focus);
    return () => { alive.current = false; off(); window.removeEventListener('keydown', escape); window.removeEventListener('focus', focus); if (timer.current) clearTimeout(timer.current); if (ticket.current) void window.ankita.invoke(CAPTURE_ACTIONS.cancel, {ticketId: ticket.current}).catch(() => {}); };
  }, [refresh]);
  const start = (event: DragEvent, threadId: string | null) => {
    if (!threadId || !setup?.instanceId || !setup.paired) { event.preventDefault(); setMessage('Pair Chrome/Edge using Browser helper in the mascot menu'); void refresh(); return false; }
    if (ticket.current) void window.ankita.invoke(CAPTURE_ACTIONS.cancel, { ticketId: ticket.current }).catch(() => {});
    const ticketId = crypto.randomUUID(); ticket.current = ticketId;
    event.dataTransfer.setData(DRAG_MIME, JSON.stringify({ ticketId, instanceId: setup.instanceId, version: PROTOCOL_VERSION }));
    event.dataTransfer.effectAllowed = 'copy';
    const canvas = event.currentTarget.querySelector('canvas, .island-mini-face') || document.querySelector('.island-mascot-canvas');
    if (canvas) { const rect = canvas.getBoundingClientRect(); event.dataTransfer.setDragImage(canvas, rect.width / 2, rect.height / 2); }
    setMessage('Drop onto a webpage');
    void window.ankita.invoke(CAPTURE_ACTIONS.register, { ticketId, threadId }).catch(error => { if (alive.current) setMessage(String(error.message || error)); });
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { if (alive.current && ticket.current === ticketId) { ticket.current = null; setMessage('No page received. Check the helper, then drag again.'); } }, TICKET_TTL_MS);
    return true;
  };
  const end = (event: DragEvent) => {
    if (event.dataTransfer.dropEffect === 'none' && ticket.current) {
      void window.ankita.invoke(CAPTURE_ACTIONS.cancel, { ticketId: ticket.current }).catch(() => {});
      ticket.current = null; if (timer.current) clearTimeout(timer.current); setMessage('');
    }
  };
  return { setup, message, refresh, start, end };
}
