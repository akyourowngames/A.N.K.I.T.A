import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import type { SecureStoreRequest, SecureStoreStatus, SecureStoreRecord } from '../../../shared/wire';
import { SecureStoreDialog } from './SecureStoreDialog';
import { Icon } from './Icons';
import { secureStoreReceipt } from '../../../shared/secure-store-receipt.mjs';
const key = (threadId: string, callId: string) => `${threadId}:${callId}`;
const SecureContext = createContext<{ requests: SecureStoreRequest[]; statuses: Record<string, SecureStoreStatus>; open: (request: SecureStoreRequest) => void }>({ requests: [], statuses: {}, open: () => {} });

export function SecureStoreProvider({ children }: { children: ReactNode }) {
  const [requests, setRequests] = useState<SecureStoreRequest[]>([]);
  const [statuses, setStatuses] = useState<Record<string, SecureStoreStatus>>({});
  const [selected, setSelected] = useState<SecureStoreRequest | null>(null);
  useEffect(() => window.ankita?.onEvent(event => {
    if (event.type === 'secure-store-request') setRequests(prior => [...prior.filter(r => r.requestId !== event.requestId), event]);
    if (event.type === 'secure-store-status') setStatuses(prior => ({ ...prior, [key(event.threadId, event.callId)]: event }));
    if (event.type === 'secure-store-resolved') { setRequests(prior => prior.filter(r => r.requestId !== event.requestId)); setSelected(prior => prior?.requestId === event.requestId ? null : prior); }
    if (event.type === 'turn-end') { setRequests(prior => prior.filter(r => r.threadId !== event.threadId)); setSelected(prior => prior?.threadId === event.threadId ? null : prior); }
  }), []);
  return <SecureContext.Provider value={{ requests, statuses, open: setSelected }}>{children}{selected && <SecureStoreDialog key={selected.requestId} request={selected} onClose={() => setSelected(null)} />}</SecureContext.Provider>;
}

export function SecureStoreCard({ threadId, callId, website, result }: { threadId: string; callId: string; website: string; result: string }) {
  const context = useContext(SecureContext);
  const request = context.requests.find(r => r.threadId === threadId && r.callId === callId);
  const receipt = secureStoreReceipt(result);
  const status = context.statuses[key(threadId, callId)];
  const state = status?.state || receipt.status || (request ? 'prompt' : result ? 'attention' : 'working');
  const retry = state === 'attention';
  const supplied = state === 'available' || state === 'filled';
  const takeover = () => { if (request) void window.ankita.invoke('respondSecureStore', { ...request, action: 'takeover' }); else void window.ankita.invoke('browserSessionTakeover', { enabled: true }); };
  return <div className={`tool-card secure-store-card ${retry ? 'failed' : ''}`}>
    <div className="secure-store-heading"><span className="tool-glyph">{state === 'working' ? <span className="tool-spinner" /> : <Icon name={state === 'ready' || supplied ? 'check' : 'lock'} size={16} />}</span><div><strong>Secure store</strong><span>{supplied ? state === 'available' ? 'Credentials available privately' : 'Selected controls filled' : state === 'ready' ? `Signed in${status?.username || receipt.username ? ` as ${status?.username || receipt.username}` : ''}` : `Sign in to ${request?.website || website}`}</span></div><small>{state === 'ready' ? 'Ready' : state === 'working' ? 'Working' : ''}</small></div>
    {status?.message || receipt.message ? <p role={retry ? 'status' : undefined}>{status?.message || receipt.message}</p> : null}
    {request && <div className="secure-store-card-actions"><button className="button-secondary" onClick={() => context.open(request)}>{retry ? 'Retry' : 'Add'}</button><button className="button-quiet" onClick={takeover}>Take control</button></div>}
    {!request && retry && <div className="secure-store-card-actions"><button className="button-quiet" onClick={takeover}>Take control</button></div>}
  </div>;
}

export function SecureStoreAccounts() {
  const [open, setOpen] = useState(false);
  const [records, setRecords] = useState<SecureStoreRecord[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!open) return;
    const load = () => void window.ankita.invoke<{ records: SecureStoreRecord[] }>('secureStoreList').then(value => { setRecords(value.records); setError(''); }).catch(() => setError('Could not read saved sign-ins.'));
    load(); return window.ankita.onEvent(event => { if (event.type === 'secure-store-changed') load(); });
  }, [open]);
  return <section className="secure-store-accounts"><button className="button-quiet" onClick={() => setOpen(!open)} aria-expanded={open}><Icon name="lock" size={14} /> Saved sign-ins</button>{open && <div>{error && <p role="alert">{error}</p>}{!records.length && <p>Save a sign-in from the secure dialog during a browser task.</p>}{records.map(record => <div className="secure-store-account" key={record.id}><div><strong>{record.website}</strong><span>{record.username}</span></div><button className="button-quiet" aria-label={`Remove ${record.username} from ${record.website}`} onClick={() => void window.ankita.invoke('secureStoreRemove', { id: record.id }).catch(() => setError('Could not remove this sign-in.'))}><Icon name="trash" size={15} />Remove</button></div>)}</div>}</section>;
}
