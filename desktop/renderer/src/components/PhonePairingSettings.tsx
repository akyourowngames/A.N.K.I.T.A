import { useCallback, useEffect, useState } from 'react';
import type { PhonePairingInvitationResult, PhonePairingSnapshot } from '../../../shared/wire';
import { PHONE_PAIRING_ACTIONS } from '../../../shared/phone-pairing.mjs';
import { cleanErrorMessage } from '../../../shared/error-notices.mjs';
import { Icon } from './Icons';
import { StatusPill } from './StatusPill';
import { useCopy } from '../lib/clipboard';

const STATUS_REFRESH_MS = 5000; // Device heartbeat is minute-grained; five seconds keeps the list honest.
const COUNTDOWN_TICK_MS = 1000;
const EXPIRED_LABEL = 'Expired';

function secondsLeft(expiresAt: string | null | undefined, now: number) {
  if (!expiresAt) return 0;
  return Math.max(0, Math.ceil((Date.parse(expiresAt) - now) / 1000));
}

function clockLabel(seconds: number) {
  if (seconds <= 0) return EXPIRED_LABEL;
  const minutes = Math.floor(seconds / 60), rest = seconds % 60;
  return `${minutes}:${String(rest).padStart(2, '0')}`;
}

function lastSeenLabel(value: string | null, now: number) {
  if (!value) return 'Not connected yet';
  const seconds = Math.max(0, Math.round((now - Date.parse(value)) / 1000));
  if (seconds < 60) return 'Active just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `Last seen ${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `Last seen ${hours} h ago`;
  return `Last seen ${new Date(value).toLocaleDateString()}`;
}

export function PhonePairingSettings() {
  const [snapshot, setSnapshot] = useState<PhonePairingSnapshot | null>(null);
  const [invite, setInvite] = useState<PhonePairingInvitationResult | null>(null);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [revoking, setRevoking] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [now, setNow] = useState(() => Date.now());
  const link = useCopy();

  const apply = useCallback((next: PhonePairingSnapshot | null) => {
    setSnapshot(next);
    setInvite(current => {
      if (!next?.invitation) return null;
      return current && current.id === next.invitation.id ? current : null;
    });
  }, []);

  const refresh = useCallback(async () => {
    try { apply(await window.ankita.invoke<PhonePairingSnapshot>(PHONE_PAIRING_ACTIONS.status)); }
    catch (cause) { setError(cleanErrorMessage(cause)); }
  }, [apply]);

  useEffect(() => {
    void refresh();
    const unsubscribe = window.ankita.onEvent(event => {
      if (event.type === 'phone-pairing-changed') apply(event.snapshot);
      else if (event.type === 'phone-pairing-request') void refresh();
    });
    const timer = setInterval(() => { void refresh(); }, STATUS_REFRESH_MS);
    return () => { unsubscribe(); clearInterval(timer); };
  }, [refresh, apply]);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), COUNTDOWN_TICK_MS);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(''), 4000);
    return () => clearTimeout(timer);
  }, [notice]);

  const run = async (key: string, action: string, payload?: unknown) => {
    setBusy(key); setError(''); setNotice('');
    try { apply(await window.ankita.invoke<PhonePairingSnapshot>(action, payload)); }
    catch (cause) { setError(cleanErrorMessage(cause)); }
    finally { setBusy(null); }
  };

  const createInvitation = async () => {
    setBusy('invite'); setError(''); setNotice('');
    try {
      const next = await window.ankita.invoke<PhonePairingInvitationResult>(PHONE_PAIRING_ACTIONS.invite);
      setInvite(next);
      await refresh();
    } catch (cause) { setError(cleanErrorMessage(cause)); }
    finally { setBusy(null); }
  };

  const cancelInvitation = async () => { setInvite(null); await run('cancel', PHONE_PAIRING_ACTIONS.cancelInvite); };

  const saveCertificate = async () => {
    setBusy('certificate'); setError(''); setNotice('');
    try {
      const result = await window.ankita.invoke<{ canceled: boolean; path?: string }>(PHONE_PAIRING_ACTIONS.saveCertificate);
      if (!result.canceled && result.path) setNotice(`Certificate saved to ${result.path}`);
    } catch (cause) { setError(cleanErrorMessage(cause)); }
    finally { setBusy(null); }
  };

  const copyLink = async () => {
    if (!invite) return;
    if (!await link.copy(invite.uri)) setError('Could not copy the pairing link.');
  };

  const teammates = snapshot?.teammates || [];
  const defaultTeammate = teammates[0]?.id || '';
  const activeInvite = invite;
  const pendingCount = snapshot?.pending.length || 0;
  const canPair = snapshot?.state === 'ready' && snapshot.running;

  const stateCard = !snapshot || canPair ? null : <section className="settings-panel phone-state" role="status">
    <div className="settings-section-lead">
      <span className="settings-section-symbol"><Icon name={snapshot.state === 'starting' ? 'clock' : 'alert'} size={18} /></span>
      <div>
        <h2>{snapshot.state === 'starting' ? 'Starting the pairing service…'
          : snapshot.state === 'offline' ? 'This computer is offline'
          : snapshot.state === 'unsupported' ? 'Secure storage is unavailable'
          : 'The pairing service stopped'}</h2>
        <p>{snapshot.error || 'Ankita is preparing a private connection for your phone.'}</p>
      </div>
    </div>
    {snapshot.state !== 'starting' && snapshot.state !== 'unsupported' && <div className="phone-actions">
      <button type="button" className="settings-secondary" disabled={busy === 'restart'} onClick={() => void run('restart', PHONE_PAIRING_ACTIONS.restart)}>
        <Icon name="refresh" size={14} />{busy === 'restart' ? 'Checking…' : 'Try again'}
      </button>
    </div>}
  </section>;

  if (!snapshot) return <div className="settings-content"><div className="settings-loading">Loading phone pairing…</div>{error && <div className="settings-notice error" role="alert"><Icon name="alert" size={15} />{error}</div>}</div>;

  return <div className="settings-content phone-settings">
    <div className="settings-heading">
      <span className="settings-heading-icon"><Icon name="phone" size={20} /></span>
      <h1 id="settings-title">Pair a phone</h1>
      <p>Let your phone talk to this desktop assistant over your own network. Each phone gets its own key, and you approve every pairing here.</p>
    </div>

    {error && <div className="settings-notice error phone-notice" role="alert"><Icon name="alert" size={15} />{error}</div>}
    {notice && <div className="settings-notice phone-notice" role="status"><Icon name="check" size={15} />{notice}</div>}

    {stateCard}

    {canPair && <>
      <section className="settings-panel phone-connection">
        <div className="phone-connection-head">
          <div className="settings-section-lead">
            <span className="settings-section-symbol"><Icon name="globe" size={18} /></span>
            <div><h2>This computer</h2><p>Your phone must be on the same Wi-Fi or ethernet network.</p></div>
          </div>
          <StatusPill tone="live" role="status">Listening</StatusPill>
        </div>
        <div className="phone-facts">
          <div>
            <span>Address</span>
            {snapshot.addresses.length > 1
              ? <select className="settings-select phone-address-select" aria-label="Address a phone can reach" value={snapshot.preferredAddress || snapshot.addresses[0]} onChange={event => void run('address', PHONE_PAIRING_ACTIONS.selectAddress, { address: event.target.value })}>
                  {snapshot.addresses.map(address => <option key={address} value={address}>{address}</option>)}
                </select>
              : <code>{snapshot.addresses[0]}</code>}
            <small>Port {snapshot.port}. If the phone cannot connect, allow Ankita through the firewall.</small>
          </div>
          <div>
            <span>Certificate fingerprint</span>
            <code className="phone-fingerprint">{snapshot.fingerprint}</code>
            <small>Compare this on the phone after pairing. The certificate is unique to this computer.</small>
          </div>
        </div>
        <div className="phone-actions">
          <button type="button" className="settings-secondary" onClick={() => void saveCertificate()} disabled={busy === 'certificate'}><Icon name="file" size={14} />{busy === 'certificate' ? 'Saving…' : 'Save certificate'}</button>
          <button type="button" className="settings-secondary" onClick={() => void run('restart', PHONE_PAIRING_ACTIONS.restart)} disabled={busy === 'restart'}><Icon name="refresh" size={14} />{busy === 'restart' ? 'Restarting…' : 'Restart connection'}</button>
        </div>
        <p className="phone-trust"><Icon name="shield" size={14} /><span>Install the saved certificate on the phone once. Ankita never turns off HTTPS checks and never shares a password with the phone.</span></p>
      </section>

      <h2 className="settings-section-title">Pair a new phone</h2>
      <section className="settings-panel phone-invite">
        {activeInvite ? <div className="phone-invite-layout">
          <div className="phone-qr"><img src={activeInvite.qr} width={220} height={220} alt="Pairing QR code for the Ankita app" /></div>
          <div className="phone-invite-copy">
            <span className="phone-eyebrow">Scan with the Ankita app, or enter the code</span>
            <strong className="phone-code">{activeInvite.code}</strong>
            <small className={`phone-expiry ${secondsLeft(activeInvite.expiresAt, now) === 0 ? 'expired' : ''}`}>
              {secondsLeft(activeInvite.expiresAt, now) === 0 ? 'This code expired. Create a new one.' : `Expires in ${clockLabel(secondsLeft(activeInvite.expiresAt, now))} · ${activeInvite.attemptsLeft} attempts left`}
            </small>
            <code className="phone-invite-address">{activeInvite.address}</code>
            <div className="phone-actions">
              <button type="button" className="settings-primary" onClick={() => void copyLink()}>{link.copied ? 'Link copied' : 'Copy pairing link'}</button>
              <button type="button" className="settings-secondary" onClick={() => void cancelInvitation()} disabled={busy === 'cancel'}>Cancel</button>
            </div>
            <p>The code is single-use, opens this computer only, and never contains the phone’s permanent key.</p>
          </div>
        </div> : <div className="phone-invite-empty">
          <div className="settings-section-lead">
            <span className="settings-section-symbol"><Icon name="phone" size={18} /></span>
            <div><h2>Ready for a new phone</h2><p>Show a QR code or a short code. It expires in two minutes and can be used once.</p></div>
          </div>
          <button type="button" className="settings-primary" onClick={() => void createInvitation()} disabled={busy === 'invite'}>{busy === 'invite' ? 'Preparing…' : 'Create pairing code'}</button>
          <ol className="phone-steps">
            <li><span>1</span>Install the Ankita certificate on the phone.</li>
            <li><span>2</span>Open Settings → Connections → Desktop in the phone app.</li>
            <li><span>3</span>Scan the code, then approve the phone here.</li>
          </ol>
        </div>}
      </section>

      {pendingCount > 0 && <>
        <h2 className="settings-section-title">Waiting for approval</h2>
        <div className="phone-request-list">{snapshot.pending.map(request => {
          const remaining = secondsLeft(request.expiresAt, now);
          const selected = choices[request.requestId] ?? defaultTeammate;
          return <section key={request.requestId} className="settings-panel phone-request" aria-live="polite">
            <div className="phone-request-head">
              <span className="phone-device-mark"><Icon name="phone" size={17} /></span>
              <div><strong>{request.deviceName}</strong><small>{request.platform} · {remaining === 0 ? 'Request expired' : `Expires in ${clockLabel(remaining)}`}</small></div>
            </div>
            <label className="phone-field"><span>Send this phone’s messages to</span>
              <select className="settings-select" value={selected} onChange={event => setChoices(current => ({ ...current, [request.requestId]: event.target.value }))} disabled={remaining === 0}>
                {teammates.map(teammate => <option key={teammate.id} value={teammate.id}>{teammate.name}</option>)}
              </select>
            </label>
            <div className="phone-actions">
              <button type="button" className="settings-primary" disabled={!teammates.length || remaining === 0 || busy === request.requestId} onClick={() => void run(request.requestId, PHONE_PAIRING_ACTIONS.respond, { requestId: request.requestId, approve: true, teammateId: selected })}>
                {busy === request.requestId ? 'Approving…' : 'Approve phone'}
              </button>
              <button type="button" className="settings-secondary" disabled={busy === request.requestId} onClick={() => void run(request.requestId, PHONE_PAIRING_ACTIONS.respond, { requestId: request.requestId, approve: false })}>Reject</button>
            </div>
            {!teammates.length && <p className="phone-inline-warning">Create a teammate before approving a phone.</p>}
          </section>;
        })}</div>
      </>}

      <h2 className="settings-section-title">Paired phones</h2>
      <section className="settings-panel phone-devices">
        {snapshot.devices.length ? <div className="phone-device-list">{snapshot.devices.map(device => <div key={device.id} className="phone-device-row">
          <span className="phone-device-mark"><Icon name="phone" size={17} /></span>
          <div className="phone-device-copy">
            <strong>{device.name}</strong>
            <small>{device.platform} · {device.activeRun ? `Working · ${device.activeRun}` : lastSeenLabel(device.lastSeenAt, now)}</small>
          </div>
          <StatusPill tone={device.online ? 'live' : 'idle'}>{device.online ? 'Online' : 'Offline'}</StatusPill>
          <label className="phone-assign">
            <span className="sr-only">Teammate for {device.name}</span>
            <select className="settings-select" value={device.teammateId} onChange={event => void run(`assign-${device.id}`, PHONE_PAIRING_ACTIONS.assign, { deviceId: device.id, teammateId: event.target.value })} disabled={busy === `assign-${device.id}`}>
              {teammates.map(teammate => <option key={teammate.id} value={teammate.id}>{teammate.name}</option>)}
              {!teammates.some(teammate => teammate.id === device.teammateId) && <option value={device.teammateId}>{device.teammateName}</option>}
            </select>
          </label>
          {revoking === device.id ? <div className="phone-revoke-confirm">
            <span>Disconnect and forget this phone?</span>
            <button type="button" className="settings-secondary" onClick={() => setRevoking(null)}>Keep</button>
            <button type="button" className="settings-danger" onClick={() => { setRevoking(null); void run(`revoke-${device.id}`, PHONE_PAIRING_ACTIONS.revoke, { deviceId: device.id }); }}>Disconnect</button>
          </div> : <button type="button" className="settings-secondary phone-revoke" onClick={() => setRevoking(device.id)} disabled={busy === `revoke-${device.id}`}><Icon name="trash" size={14} />Disconnect</button>}
        </div>)}</div> : <div className="phone-empty"><Icon name="phone" size={22} /><div><strong>No phones paired</strong><p>Create a pairing code above to add your first phone.</p></div></div>}
        {snapshot.devices.length > 0 && <p className="phone-footnote">Disconnecting a phone cancels its active request and invalidates its key immediately.</p>}
      </section>
    </>}
  </div>;
}
