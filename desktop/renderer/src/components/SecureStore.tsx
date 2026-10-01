import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import type { SecureStoreRequest, SecureStoreStatus, SecureStoreRecord } from '../../../shared/wire';
import { SecureStoreDialog } from './SecureStoreDialog';
import { Icon } from './Icons';
import { relativeTime } from '../lib/relative-time';
import { secureStoreReceipt } from '../../../shared/secure-store-receipt.mjs';
const key = (threadId: string, callId: string) => `${threadId}:${callId}`;
/** `https://www.linkedin.com` -> `linkedin.com`, for a readable site label. */
const siteHost = (website: string) => { try { return new URL(website).hostname.replace(/^www\./, ''); } catch { return website; } };
const siteHue = (host: string) => [...host].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 360;
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

/**
 * The browser vault, presented as a first-class section of Plugins rather than
 * a stray disclosure. It is what the built-in browser and Chromium fill from, so
 * it reads like the rest of the page: a section head, then a framed card.
 */
export function SecureStoreAccounts() {
  const [records, setRecords] = useState<SecureStoreRecord[] | null>(null);
  const [error, setError] = useState('');
  const [removing, setRemoving] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => void window.ankita.invoke<{ records: SecureStoreRecord[] }>('secureStoreList')
      .then(value => { if (alive) { setRecords(value.records); setError(''); } })
      .catch(() => { if (alive) { setRecords([]); setError('Could not read saved sign-ins.'); } });
    load();
    const off = window.ankita.onEvent(event => { if (event.type === 'secure-store-changed') load(); });
    return () => { alive = false; off(); };
  }, []);
  const remove = async (id: string) => {
    setRemoving(id); setError('');
    try { await window.ankita.invoke('secureStoreRemove', { id }); setRecords(current => (current || []).filter(record => record.id !== id)); }
    catch { setError('Could not remove this sign-in.'); }
    finally { setRemoving(null); }
  };
  const count = records?.length || 0;
  return <section className="plugins-section vault-section" aria-labelledby="saved-sign-ins-heading">
    <div className="plugins-section-head"><h2 id="saved-sign-ins-heading">Saved sign-ins</h2><span>{count ? `${count} saved · encrypted on this device` : 'Private to this device'}</span></div>
    <div className="vault-card">
      <div className="vault-intro">
        <span className="vault-mark"><Icon name="lock" size={16} /></span>
        <div><strong>Browser vault</strong><p>Sign-ins Ankita fills for the built-in browser and Chromium. Sealed with this device's encryption — never shown in chat.</p></div>
      </div>
      {error ? <p className="vault-error" role="alert">{error}</p> : null}
      {records === null ? <p className="vault-status">Reading the vault…</p>
        : count === 0 ? <div className="vault-empty"><Icon name="key" size={20} /><p>No sign-ins saved yet.</p><small>When a browser task asks you to sign in, choose Save and it will appear here.</small></div>
        : <ul className="vault-list">{records.map(record => {
            const host = siteHost(record.website), when = relativeTime(record.updatedAt);
            return <li className="vault-item" key={record.id}>
              <span className="vault-site" style={{ '--vault-hue': siteHue(host) } as React.CSSProperties} aria-hidden="true">{host.slice(0, 1).toUpperCase()}</span>
              <span className="vault-item-copy"><strong>{host}</strong><small>{record.username || 'Saved sign-in'}</small></span>
              <span className="vault-item-when">{when === 'now' ? 'just now' : when}</span>
              <button type="button" className="vault-remove" onClick={() => void remove(record.id)} disabled={removing === record.id} aria-label={`Remove saved sign-in for ${record.username || 'this site'} at ${record.website}`}><Icon name="trash" size={14} /><span>{removing === record.id ? 'Removing…' : 'Remove'}</span></button>
            </li>;
          })}</ul>}
    </div>
  </section>;
}
