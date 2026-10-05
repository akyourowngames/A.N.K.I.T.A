import { useState } from 'react';
import { CAPTURE_ACTIONS } from '../../../browser-helper/protocol.mjs';
import type { CaptureSetup } from '../lib/useMascotCapture';

export function BrowserHelperSetup() {
  const [status, setStatus] = useState('');
  const [code, setCode] = useState('');
  const pair = async () => {
    try {
      const setup = await window.ankita.invoke<CaptureSetup>(CAPTURE_ACTIONS.setup);
      const value = JSON.stringify({ address: setup.address, code: setup.code });
      setCode(value);
      try { await navigator.clipboard.writeText(value); setStatus('Code copied. Paste it into the helper popup.'); }
      catch { setStatus('Copy the code below into the helper popup.'); }
    } catch (error) { setStatus(String((error as Error).message || error)); }
  };
  return <div className="companion-helper-setup">
    <button type="button" onClick={() => { void window.ankita.invoke(CAPTURE_ACTIONS.openHelper).catch(error => setStatus(error.message)); }}>Open helper folder</button>
    <button type="button" onClick={() => void pair()}>Copy pairing code</button>
    <p>In Chrome or Edge's Extensions page, enable Developer mode and choose Load unpacked for this folder. Paste the pairing code into its popup, then drag a mascot onto a webpage.</p>
    {code && <input readOnly aria-label="Browser pairing code" value={code} onFocus={event => event.target.select()} />}
    {status && <span role="status">{status}</span>}
  </div>;
}
