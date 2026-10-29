import { useCallback, useEffect, useState } from 'react';
import { CONTROL_ACTIONS, CONTROL_STATUS_MS } from '../../../browser-helper/control-protocol.mjs';
import { CAPTURE_ACTIONS } from '../../../browser-helper/protocol.mjs';
import { cleanErrorMessage } from '../../../shared/error-notices.mjs';

type Connection = { paired: boolean; connected: boolean; paused: boolean };
export function ExtensionBrowserSetup() {
  const [state, setState] = useState<Connection | null>(null);
  const [code, setCode] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState(''), [copied, setCopied] = useState(false);
  const refresh = useCallback(async () => { try { setState(await window.ankita.invoke<Connection>(CONTROL_ACTIONS.status)); } catch (cause) { setError(cleanErrorMessage(cause)); } }, []);
  useEffect(() => { void refresh(); const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, CONTROL_STATUS_MS); return () => window.clearInterval(timer); }, [refresh]);
  const act = async (action: string) => {
    setBusy(true); setError('');
    try {
      const result = await window.ankita.invoke(action);
      if (action === CONTROL_ACTIONS.setup) { setCode(JSON.stringify(result)); setCopied(false); }
      if (action === CONTROL_ACTIONS.revoke) setCode('');
      await refresh();
    } catch (cause) { setError(cleanErrorMessage(cause)); }
    finally { setBusy(false); }
  };
  useEffect(() => { if (state?.paired && state.connected) setCode(''); }, [state?.paired, state?.connected]);
  return <section className="browser-extension-setup" aria-label="Browser companion connection">
    <div className="browser-plugin-setup-row"><span role="status"><strong>{state?.connected ? 'Connected to your browser' : state?.paused ? 'Connection paused' : state?.paired ? 'Waiting for your browser' : 'Pair your browser once'}</strong></span></div>
    <p>Your signed-in tabs stay in your browser. After pairing, Ankita reconnects automatically when you reopen either app.</p>
    {!state?.paired && <>
      <ol><li>Open the extension folder below. In your browser’s Extensions page, turn on Developer mode and choose Load unpacked.</li><li>Choose that folder, then open <strong>ANKITA Browser Companion</strong> from your browser toolbar.</li><li>Copy the setup code and paste it into the companion. Pair once to allow browser control.</li></ol>
      <div className="browser-plugin-setup-row"><button type="button" onClick={() => void act(CAPTURE_ACTIONS.openHelper)} disabled={busy}>Open extension folder</button><button type="button" className="browser-plugin-primary" onClick={() => void act(CONTROL_ACTIONS.setup)} disabled={busy}>{busy ? 'Preparing…' : code ? 'Refresh setup code' : 'Create setup code'}</button></div>
    </>}
    {code && <div className="browser-extension-code"><label htmlFor="browser-extension-code">One-time setup code</label><textarea id="browser-extension-code" readOnly value={code} rows={3} spellCheck={false} /><button type="button" onClick={() => { void navigator.clipboard.writeText(code).then(() => setCopied(true)).catch(() => setError('Select and copy the setup code above.')); }}>{copied ? 'Copied' : 'Copy setup code'}</button></div>}
    {state?.paired && <div className="browser-plugin-setup-row"><button type="button" onClick={() => void act(state.paused ? CONTROL_ACTIONS.resume : CONTROL_ACTIONS.disconnect)} disabled={busy}>{state.paused ? 'Reconnect' : 'Disconnect'}</button><button type="button" onClick={() => void act(CONTROL_ACTIONS.revoke)} disabled={busy}>Unpair browser</button></div>}
    <small>Disconnect keeps the pairing. Unpair removes browser access. Chrome may show a control notice for deeper actions.</small>
    {error && <p className="browser-details-error" role="alert">{error}</p>}
  </section>;
}
