import { useState } from 'react';
import type { JobReceipt, Routine } from '../../../shared/wire';
import { Icon } from './Icons';
export function JobCard({ receipt, compact = false }: { receipt: JobReceipt; compact?: boolean }) {
  const ok = ['ok', 'disabled-mid-run'].includes(receipt.status);
  return <section className={`scheduled-result ${compact ? 'compact' : ''} ${ok ? '' : 'needs-review'}`} aria-label={`Scheduled job ${receipt.name}`}>
    <div className="scheduled-result-heading"><Icon name={ok ? 'check' : 'alert'} size={16} /><strong>{receipt.name}</strong><span>{receipt.status.replaceAll('-', ' ')}</span><time>{new Date(receipt.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></div>
    {receipt.ownerMissing && <p className="job-owner-warning">Owner was deleted. Choose a teammate in job settings.</p>}
    {compact ? <details className="job-proof"><summary>Run details and browser proof</summary><p>{receipt.text}</p>{receipt.proof?.screenshot && <img src={receipt.proof.screenshot} alt={`Browser proof for ${receipt.name}`} />}</details> : <p>{receipt.text}</p>}
    {!compact && receipt.proof?.screenshot && <details className="job-proof"><summary>View browser proof</summary><img src={receipt.proof.screenshot} alt={`Browser proof for ${receipt.name}`} /></details>}
    {receipt.proof?.url && <button type="button" className="job-link" onClick={() => void window.ankita.openExternal(receipt.proof!.url!)}>{receipt.proof.url}<Icon name="external" size={12} /></button>}
  </section>;
}
export function JobApprovalCard({ job, onEdit }: { job: Routine; onEdit: (id: string) => void }) {
  const [error, setError] = useState('');
  const pending = job.pendingApproval;
  if (!pending) return null;
  const answer = (value: string) => { setError(''); void window.ankita.invoke('respondApproval', { requestId: pending.requestId, answer: value }).catch(cause => setError(cause.message)); };
  return <section className="job-approval-card" id={`job-review-${job.id}`} aria-label={`${job.name} needs approval`}>
    <div className="scheduled-result-heading"><Icon name="clock" size={16} /><strong>{job.name} needs access</strong><span>Step {job.step}</span></div>
    <p>{pending.redactedDetail}</p><small>Waiting until {new Date(pending.expiresAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}. Chat stays available.</small>
    <div className="job-actions"><button onClick={() => answer('yes')}>Allow this step</button><button onClick={() => answer('always')}>Always for this job</button><button onClick={() => onEdit(job.id)}>Edit permissions</button><button onClick={() => answer('no')}>Skip run</button></div>
    {error && <p role="status" className="job-owner-warning">{error}</p>}
  </section>;
}
