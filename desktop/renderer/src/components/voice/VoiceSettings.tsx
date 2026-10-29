import { useEffect, useState } from 'react';
import type { DesktopPreferences, DesktopSettingsResult, DesktopSettingsUpdate } from '../../../../shared/wire';
import type { VoiceStatus } from '../../../../shared/voice.mjs';
import { VOICE_ACTIONS } from '../../../../shared/voice.mjs';
import { cleanErrorMessage } from '../../../../shared/error-notices.mjs';
import { VoiceOrb } from './VoiceOrb';
import { Icon } from '../Icons';
import './voice.css';

export function VoiceSettings({ preferences, onSaved }: { preferences: DesktopPreferences; onSaved: (result: DesktopSettingsResult) => void }) {
  const [sarvam, setSarvam] = useState(''), [baseten, setBaseten] = useState('');
  const [mic, setMic] = useState(preferences.micDevice || '');
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [saved, setSaved] = useState(false);
  const refresh = () => window.ankita.invoke<VoiceStatus>(VOICE_ACTIONS.status).then(setStatus).catch(cause => setError(cleanErrorMessage(cause)));
  useEffect(() => { let alive = true; void window.ankita.invoke<VoiceStatus>(VOICE_ACTIONS.status).then(value => { if (alive) setStatus(value); }).catch(cause => { if (alive) setError(cleanErrorMessage(cause)); }); return () => { alive = false; }; }, []);
  const save = async () => {
    const patch: DesktopSettingsUpdate = {};
    if (sarvam.trim()) patch.sarvamApiKey = sarvam.trim();
    if (baseten.trim()) patch.basetenApiKey = baseten.trim();
    if (mic !== (preferences.micDevice || '')) patch.micDevice = mic;
    setBusy(true); setError(''); setSaved(false);
    try { const result = await window.ankita.invoke<DesktopSettingsResult>('saveDesktopSettings', patch); onSaved(result); setSarvam(''); setBaseten(''); setSaved(true); await refresh(); }
    catch (cause) { setError(cleanErrorMessage(cause)); }
    finally { setBusy(false); }
  };
  return <div className="settings-content">
    <div className="settings-heading"><span className="settings-heading-icon"><Icon name="mic" size={20} /></span><h1 id="settings-title">Voice</h1><p>A conversation that can get things done.</p></div>
    <section className="settings-panel"><div className="voice-settings-orb"><VoiceOrb phase={status?.ready ? 'listening' : 'idle'} inputLevel={0} compact /><div><h2>Speak. Delegate. Keep going.</h2><p>Sarvam hears and speaks. Meta plans your voice requests through Baseten.</p></div></div>
      <label className="settings-label" htmlFor="voice-sarvam">Sarvam API key</label><input id="voice-sarvam" className="settings-input" type="password" autoComplete="new-password" value={sarvam} onChange={event => setSarvam(event.target.value)} placeholder={preferences.hasSarvamKey ? 'Key saved · enter a new key to replace it' : 'Enter your Sarvam key'} />
      <label className="settings-label" htmlFor="voice-baseten">Baseten API key</label><input id="voice-baseten" className="settings-input" type="password" autoComplete="new-password" value={baseten} onChange={event => setBaseten(event.target.value)} placeholder={preferences.hasBasetenKey ? 'Key saved · enter a new key to replace it' : 'Enter your Baseten key'} />
      <div className="voice-settings-device"><label className="settings-label" htmlFor="voice-microphone">Microphone</label><select id="voice-microphone" className="settings-select" value={mic} onChange={event => setMic(event.target.value)}><option value="">Choose automatically</option>{mic && !status?.microphones.some(item => item.name === mic) && <option value={mic}>{mic} · unavailable</option>}{status?.microphones.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}</select></div>
      <div className="voice-settings-actions"><button className="settings-primary" disabled={busy || status?.state.active} onClick={() => void save()}>{busy ? 'Saving…' : 'Save voice settings'}</button><button className="voice-text-button" onClick={() => void refresh()}>Refresh devices</button></div>
      <p className={error || status?.issues.length ? 'voice-settings-error' : ''} role="status">{error || (status?.state.active ? 'End voice before changing its setup.' : saved && status?.ready ? 'Saved. Voice is ready.' : status?.issues.join(' ') || (status?.ready ? 'Ready for voice.' : 'Checking your setup…'))}</p>
    </section>
    <section className="settings-panel"><h2>You’re in control.</h2><p>Pause turns off the microphone. End voice stops listening and speaking while delegated work continues. Stop work cancels the current task.</p><p>Your keys stay in the same private local settings file as your other provider keys.</p></section>
  </div>;
}
