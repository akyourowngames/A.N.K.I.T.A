import { useEffect, useRef, useState } from 'react';
import type { DesktopPreferences, DesktopSettingsResult, DesktopSettingsUpdate } from '../../../../shared/wire';
import type { VoiceState, VoiceStatus } from '../../../../shared/voice.mjs';
import { VOICE_ACTIONS, VOICE_EVENT } from '../../../../shared/voice.mjs';
import { cleanErrorMessage } from '../../../../shared/error-notices.mjs';
import { Icon } from '../Icons';
import './voice.css';

export function VoiceSettings({ preferences, onSaved }: { preferences: DesktopPreferences; onSaved: (result: DesktopSettingsResult) => void }) {
  const [sarvam, setSarvam] = useState(''), [baseten, setBaseten] = useState('');
  const [mic, setMic] = useState(preferences.micDevice || '');
  const [output, setOutput] = useState(preferences.voiceOutputDevice || '');
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [busy, setBusy] = useState(false), [testing, setTesting] = useState(false), [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const latest = useRef<VoiceState | null>(null);
  const acceptStatus = (value: VoiceStatus) => {
    if (value.state && (!latest.current || value.state.revision >= latest.current.revision)) latest.current = value.state;
    setStatus(latest.current ? { ...value, state: latest.current } : value);
  };
  const locked = busy || testing || Boolean(status?.state?.active);
  const dirty = Boolean(sarvam.trim() || baseten.trim() || mic !== (preferences.micDevice || '') || output !== (preferences.voiceOutputDevice || ''));
  const refresh = async () => {
    setRefreshing(true); setError('');
    try { acceptStatus(await window.ankita.invoke<VoiceStatus>(VOICE_ACTIONS.status)); }
    catch (cause) { setError(cleanErrorMessage(cause)); }
    finally { setRefreshing(false); }
  };
  useEffect(() => {
    let alive = true;
    const off = window.ankita.onEvent(event => {
      if (event.type !== VOICE_EVENT || !event.state || !Number.isSafeInteger(event.state.revision) || (latest.current && event.state.revision < latest.current.revision)) return;
      latest.current = event.state;
      setStatus(current => current ? { ...current, state: event.state } : current);
    });
    void window.ankita.invoke<VoiceStatus>(VOICE_ACTIONS.status).then(value => { if (alive) acceptStatus(value); }).catch(cause => { if (alive) setError(cleanErrorMessage(cause)); });
    return () => { alive = false; off(); };
  }, []);
  const save = async () => {
    const patch: DesktopSettingsUpdate = {};
    if (sarvam.trim()) patch.sarvamApiKey = sarvam.trim();
    if (baseten.trim()) patch.basetenApiKey = baseten.trim();
    if (mic !== (preferences.micDevice || '')) patch.micDevice = mic;
    if (output !== (preferences.voiceOutputDevice || '')) patch.voiceOutputDevice = output;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await window.ankita.invoke<DesktopSettingsResult>('saveDesktopSettings', patch);
      onSaved(result); setSarvam(''); setBaseten(''); await refresh(); setNotice('Voice settings saved.');
    } catch (cause) { setError(cleanErrorMessage(cause)); }
    finally { setBusy(false); }
  };
  const test = async () => {
    setTesting(true); setError(''); setNotice('');
    try {
      const result = await window.ankita.invoke<{ cancelled: boolean }>(VOICE_ACTIONS.test);
      setNotice(result.cancelled ? 'Speaker test stopped.' : 'Test played. If you heard nothing, choose another speaker and try again.');
    } catch (cause) { setError(cleanErrorMessage(cause)); }
    finally { setTesting(false); }
  };
  const issues = status?.issues || [];
  const feedback = error || (status?.state?.active ? 'End voice before changing devices or testing speakers.' : notice || issues.join(' '));
  return <div className="settings-content voice-settings">
    <div className="settings-heading"><span className="settings-heading-icon"><Icon name="mic" size={20} /></span><h1 id="settings-title">Voice</h1><p>Your microphone, speakers and voice connections.</p></div>
    <section className="settings-panel" aria-labelledby="voice-audio-title">
      <div className="settings-section-lead"><span className="settings-section-symbol"><Icon name="mic" size={18} /></span><div><h2 id="voice-audio-title">Audio devices</h2><p>Choose where Ankita listens and where you hear her.</p></div><span className="settings-value-tag">{status?.state?.active ? 'In use' : status?.ready ? 'Ready' : 'Setup'}</span></div>
      <div className="settings-field"><label htmlFor="voice-microphone">Microphone</label><select id="voice-microphone" className="settings-select" value={mic} disabled={locked || refreshing} onChange={event => { setMic(event.target.value); setNotice(''); }}>
        <option value="">Choose automatically</option>{mic && !status?.microphones?.some(item => item.name === mic) && <option value={mic}>{mic} · unavailable</option>}{status?.microphones?.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}
      </select><small>Used for your requests and to hear when you interrupt.</small></div>
      <div className="settings-field"><label htmlFor="voice-output">Speakers</label><select id="voice-output" className="settings-select" value={output} disabled={locked || refreshing || !status?.outputs?.length} onChange={event => { setOutput(event.target.value); setNotice(''); }}>
        <option value="">Automatic{status?.defaultOutput ? ` · ${status.defaultOutput}` : ' · system output'}</option>{output && !status?.outputs?.some(item => item.id === output) && <option value={output}>Saved speaker · unavailable</option>}{status?.outputs?.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select><small>{status?.outputs?.length ? 'Your choice temporarily becomes the Windows output during voice. It is restored when voice ends.' : 'Uses your system output. Change speakers in your device settings.'}</small></div>
      <div className="voice-settings-audio-actions"><button type="button" className="settings-secondary" disabled={locked || dirty || !preferences.hasSarvamKey} onClick={() => void test()}><Icon name="broadcast" size={14} />{testing ? 'Playing test…' : 'Test speakers'}</button><button type="button" className="settings-text-button" disabled={locked || refreshing} onClick={() => void refresh()}>{refreshing ? 'Refreshing…' : 'Refresh devices'}</button></div>
      <p className="voice-settings-hint">{dirty ? 'Save your changes before testing.' : 'No sound? Try your laptop speakers first, then test your headset.'}</p>
    </section>
    <section className="settings-panel" aria-labelledby="voice-connections-title">
      <div className="settings-section-lead"><span className="settings-section-symbol"><Icon name="key" size={18} /></span><div><h2 id="voice-connections-title">Voice connections</h2><p>Sarvam for speech. Meta through Baseten for requests.</p></div></div>
      <div className="settings-field"><div className="settings-field-heading"><label htmlFor="voice-sarvam">Sarvam API key</label>{preferences.hasSarvamKey && <span className="settings-saved">Saved</span>}</div><input id="voice-sarvam" type="password" autoComplete="new-password" disabled={locked} value={sarvam} onChange={event => setSarvam(event.target.value)} placeholder={preferences.hasSarvamKey ? 'Enter a new key to replace it' : 'Enter your Sarvam key'} /><small>Listens to your voice and speaks replies.</small></div>
      <div className="settings-field"><div className="settings-field-heading"><label htmlFor="voice-baseten">Baseten API key</label>{preferences.hasBasetenKey && <span className="settings-saved">Saved</span>}</div><input id="voice-baseten" type="password" autoComplete="new-password" disabled={locked} value={baseten} onChange={event => setBaseten(event.target.value)} placeholder={preferences.hasBasetenKey ? 'Enter a new key to replace it' : 'Enter your Baseten key'} /><small>Plans and carries out your voice requests.</small></div>
    </section>
    <div className="settings-savebar"><span>Saved privately on this device</span><button type="button" className="settings-primary" disabled={locked || !dirty} onClick={() => void save()}>{busy ? 'Saving…' : 'Save voice settings'}</button></div>
    <p className={`voice-settings-feedback ${error || issues.length ? 'is-error' : ''}`} role="status" aria-live="polite">{feedback || (status?.ready ? 'Voice is ready.' : 'Checking your setup…')}</p>
    <div className="settings-note"><Icon name="info" size={15} /><span>End voice stops listening and speaking. Delegated work continues until you stop it.</span></div>
  </div>;
}
