import { useEffect, useRef, useState } from 'react';
import type { SecureStoreRequest } from '../../../shared/wire';
import { Icon } from './Icons';

export function SecureStoreDialog({ request, onClose }: { request: SecureStoreRequest; onClose: () => void }) {
  const form = useRef<HTMLFormElement>(null);
  const password = useRef<HTMLInputElement>(null);
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    form.current?.querySelector<HTMLInputElement>('input[name="username"]')?.focus();
    const secret = password.current;
    return () => { if (secret) secret.value = ''; previous?.focus(); };
  }, [request.requestId]);
  const respond = async (action: 'cancel' | 'submit') => {
    if (busy) return;
    setBusy(true); setError('');
    const username = form.current?.querySelector<HTMLInputElement>('input[name="username"]')?.value || '';
    const save = form.current?.querySelector<HTMLInputElement>('input[name="save"]')?.checked === true;
    const payload = { requestId: request.requestId, threadId: request.threadId, callId: request.callId, action, username, password: action === 'submit' ? password.current?.value || '' : '', save };
    try {
      const work = window.ankita.invoke<boolean>('respondSecureStore', payload);
      payload.password = ''; if (password.current) password.current.value = '';
      if (await work) onClose(); else setError('This sign-in request has ended. Close this dialog and try again.');
    } catch { setError('Could not submit this sign-in. Try again or cancel.'); }
    finally { payload.password = ''; if (password.current) password.current.value = ''; setBusy(false); }
  };
  return <div className="modal-backdrop"><form ref={form} className="secure-store-dialog" role="dialog" aria-modal="true" aria-labelledby="secure-store-title" onSubmit={event => { event.preventDefault(); void respond('submit'); }} onKeyDown={event => {
    if (event.key === 'Escape') { event.stopPropagation(); event.preventDefault(); void respond('cancel'); }
    if (event.key === 'Tab') {
      const controls = [...(form.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled):not([readonly])') || [])];
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  }}>
    <button type="button" className="icon-button secure-store-close" aria-label="Cancel sign-in" disabled={busy} onClick={() => void respond('cancel')}><Icon name="close" /></button>
    <div className="modal-symbol"><Icon name="lock" size={23} /></div>
    <h2 id="secure-store-title">Secure credentials store</h2><p>Sign in to {request.website}. Your password goes directly to the browser.</p>
    <label className="settings-field">Website<input value={request.website} readOnly /></label>
    <label className="settings-field">Username<input name="username" defaultValue={request.username} autoComplete="username" required disabled={busy} /></label>
    <label className="settings-field">Password<div className="settings-secret-control"><input ref={password} name="password" type={visible ? 'text' : 'password'} autoComplete="off" required disabled={busy} spellCheck={false} /><button type="button" aria-label={visible ? 'Hide password' : 'Show password'} aria-pressed={visible} onClick={() => setVisible(!visible)}><Icon name={visible ? 'eyeOff' : 'eye'} size={17} /></button></div></label>
    <label className="secure-store-save"><input name="save" type="checkbox" defaultChecked={request.canSave} disabled={!request.canSave || busy} />Save to secure credentials store</label>
    {!request.canSave && <p>OS encryption is unavailable. This sign-in will not be saved.</p>}
    {error && <p role="alert">{error}</p>}
    <div className="dialog-actions"><button type="button" className="button-quiet" disabled={busy} onClick={() => void respond('cancel')}>Cancel</button><button className="button-primary" disabled={busy}>{busy ? 'Entering…' : 'Enter'}</button></div>
  </form></div>;
}
