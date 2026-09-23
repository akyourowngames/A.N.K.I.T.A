import { useEffect, useRef } from 'react';
import { Icon } from './Icons';

export function ConfirmDialog({ action, name, onCancel, onConfirm }: {
  action: 'clear' | 'delete'; name: string; onCancel: () => void; onConfirm: () => void;
}) {
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => { cancel.current?.focus(); }, []);
  useEffect(() => {
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') onCancel(); };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onCancel]);
  return <div className="modal-backdrop"><div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
    <div className="modal-symbol danger-symbol"><Icon name="trash" size={21}/></div>
    <h2 id="confirm-title">{action === 'clear' ? 'Clear this conversation?' : `Delete ${name}?`}</h2>
    <p>{action === 'clear' ? `The conversation with ${name} will be permanently removed. You can start a new one anytime.` : `${name} and their conversation will be permanently removed from your workspace.`}</p>
    <div className="dialog-actions"><button ref={cancel} className="button-secondary" onClick={onCancel}>Cancel</button><button className="button-danger" onClick={onConfirm}>{action === 'clear' ? 'Clear conversation' : 'Delete teammate'}</button></div>
  </div></div>;
}
