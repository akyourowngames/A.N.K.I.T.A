import { useState } from 'react';
import type { JobReceipt, Routine } from '../../../shared/wire';
import { Icon } from './Icons';
import { relativeTime } from '../lib/relative-time';

// Receipts are read at a glance after a run lands in chat, so the card leads with
// a plain-language status and how long ago it happened; raw details stay folded.
const RECEIPT_STATUS_LABELS: Record<string, string> = {
  ok: 'Completed',
  'disabled-mid-run': 'Paused mid-run',
  'needs-review': 'Needs review',
  failed: 'Needs review',
  missed: 'Missed',
};

function receiptStatus(receipt: JobReceipt) {
  const ok = ['ok', 'disabled-mid-run'].includes(receipt.status);
  return { ok, label: RECEIPT_STATUS_LABELS[receipt.status] || receipt.status.replaceAll('-', ' ') };
}

export function JobCard({ receipt, compact = false }: { receipt: JobReceipt; compact?: boolean }) {
  const { ok, label } = receiptStatus(receipt);
  const at = new Date(receipt.at);
  const full = at.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
  const proofUrl = receipt.proof?.url;
  return <section className={`scheduled-result ${compact ? 'compact' : ''} ${ok ? '' : 'needs-review'}`} aria-label={`Scheduled job ${receipt.name}`}>
    <div className="scheduled-result-heading">
      <span className={`scheduled-result-badge ${ok ? 'ok' : 'review'}`}><Icon name={ok ? 'check' : 'alert'} size={12} />{label}</span>
      <strong>{receipt.name}</strong>
      <time title={full}>{relativeTime(receipt.at)}</time>
    </div>
    {receipt.ownerMissing && <p className="job-owner-warning">Owner was deleted. Choose a teammate in job settings.</p>}
    {compact && <details className="job-proof"><summary><Icon name="eye" size={13} /> Run details and browser proof</summary><p>{receipt.text}</p>{receipt.proof?.screenshot && <img src={receipt.proof.screenshot} alt={`Browser proof for ${receipt.name}`} />}</details>}
    {!compact && <p className="scheduled-result-text">{receipt.text}</p>}
    {!compact && receipt.proof?.screenshot && <details className="job-proof"><summary><Icon name="eye" size={13} /> View browser proof</summary><img src={receipt.proof.screenshot} alt={`Browser proof for ${receipt.name}`} /></details>}
    {proofUrl && <button type="button" className="job-link" onClick={() => void window.ankita.openExternal(proofUrl)}>{proofUrl}<Icon name="external" size={12} /></button>}
  </section>;
}

export function JobApprovalCard({ job, onEdit }: { job: Routine; onEdit: (id: string) => void }) {
  const [error, setError] = useState('');
  const pending = job.pendingApproval;
  if (!pending) return null;
  const answer = (value: string) => { setError(''); void window.ankita.invoke('respondApproval', { requestId: pending.requestId, answer: value }).catch(cause => setError(cause.message)); };
  return <section className="job-approval-card" id={`job-review-${job.id}`} aria-label={`${job.name} needs approval`}>
    <div className="scheduled-result-heading"><span className="scheduled-result-badge review"><Icon name="alert" size={12} />Needs access</span><strong>{job.name}</strong><time>Step {job.step}</time></div>
    <p>{pending.redactedDetail}</p><small>Waiting until {new Date(pending.expiresAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}. Chat stays available.</small>
    <div className="job-actions"><button className="button-primary" onClick={() => answer('yes')}>Allow this step</button><button onClick={() => answer('always')}>Always for this job</button><button onClick={() => onEdit(job.id)}>Edit permissions</button><button onClick={() => answer('no')}>Skip run</button></div>
    {error && <p role="status" className="job-owner-warning">{error}</p>}
  </section>;
}
