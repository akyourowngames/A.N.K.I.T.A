import { useEffect, useRef } from 'react';
import type { Approval } from '../state/store';
import { Icon } from './Icons';

export function ApprovalDialog({ approval, onAnswer }: { approval: Approval; onAnswer: (answer: 'yes' | 'no' | 'always') => void }) {
  const deny = useRef<HTMLButtonElement>(null);
  useEffect(() => { deny.current?.focus(); }, [approval.requestId]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') onAnswer('no'); };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onAnswer]);
  return <div className="modal-backdrop"><div className="approval-dialog" role="dialog" aria-modal="true" aria-labelledby="approval-title">
    <div className="modal-symbol"><Icon name="alert" size={23}/></div>
    <h2 id="approval-title">Allow this action?</h2>
    <p><strong>{approval.toolName}</strong> needs your approval before it runs.</p>
    <pre className="approval-detail">{approval.detail}</pre>
    <div className="approval-actions"><button ref={deny} className="button-quiet" onClick={() => onAnswer('no')}>Deny</button><button className="button-secondary" onClick={() => onAnswer('yes')}>Allow once</button><button className="button-primary" onClick={() => onAnswer('always')}>Always allow</button></div>
  </div></div>;
}
