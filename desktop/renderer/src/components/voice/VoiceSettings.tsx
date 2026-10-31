import { useEffect, useRef, useState } from 'react';
import type { DesktopPreferences, DesktopSettingsResult, DesktopSettingsUpdate } from '../../../../shared/wire';
import type { VoiceState, VoiceStatus } from '../../../../shared/voice.mjs';
import { VOICE_ACTIONS, VOICE_EVENT } from '../../../../shared/voice.mjs';
import { cleanErrorMessage } from '../../../../shared/error-notices.mjs';
import { Icon } from '../Icons';
import './voice.css';

// Display defaults mirror config.mjs; the backend remains the source of truth.
const DEFAULT_IDLE_MS = 15000;
const DEFAULT_STANDBY_MS = 600000;
const IDLE_MIN_SEC = 0, IDLE_MAX_SEC = 600; // 0 = return to standby as soon as the wake word is heard.
const STANDBY_MIN_MIN = 1, STANDBY_MAX_MIN = 60;
const toIdleMs = (seconds: string) => Math.round(Number(seconds) * 1000);
const toStandbyMs = (minutes: string) => Math.round(Number(minutes) * 60000);

export function VoiceSettings({ preferences, onSaved }: { preferences: DesktopPreferences; onSaved: (result: DesktopSettingsResult) => void }) {
  const [sarvam, setSarvam] = useState(''), [baseten, setBaseten] = useState('');
  const [mic, setMic] = useState(preferences.micDevice || '');
  const [output, setOutput] = useState(preferences.voiceOutputDevice || '');
  // Hands-free behaviour: plain settings, editable even while a session is live.
  const [wake, setWake] = useState(preferences.voiceWakeWord !== false);
  const [stop, setStop] = useState(preferences.voiceStopWord !== false);
  const [idleSec, setIdleSec] = useState(String(Math.round((preferences.voiceIdleMs || DEFAULT_IDLE_MS) / 1000)));
  const [standbyMin, setStandbyMin] = useState(String(Math.round((preferences.voiceStandbyMs || DEFAULT_STANDBY_MS) / 60000)));
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [busy, setBusy] = useState(false), [testing, setTesting] = useState(false), [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const latest = useRef<VoiceState | null>(null);
  const acceptStatus = (value: VoiceStatus) => {
    if (value.state && (!latest.current || value.state.revision >= latest.current.revision)) latest.current = value.state;
    setStatus(latest.current ? { ...value, state: latest.current } : value);
  };
  const locked = busy || testing || Boolean(status?.state?.active);
  const handsFreeDirty = wake !== (preferences.voiceWakeWord !== false)
    || stop !== (preferences.voiceStopWord !== false)
    || toIdleMs(idleSec) !== (preferences.voiceIdleMs || DEFAULT_IDLE_MS)
    || toStandbyMs(standbyMin) !== (preferences.voiceStandbyMs || DEFAULT_STANDBY_MS);
  const dirty = Boolean(handsFreeDirty || sarvam.trim() || baseten.trim() || mic !== (preferences.micDevice || '') || output !== (preferences.voiceOutputDevice || ''));
  const refresh = async () => {
    setRefreshing(true); setError('');
    try { acceptStatus(await window.ankita.invoke<VoiceStatus>(VOICE_ACTIONS.status, { refresh: true })); }
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
    // Only changed behaviour keys are sent, so untouched values keep their defaults.
    if (wake !== (preferences.voiceWakeWord !== false)) patch.voiceWakeWord = wake;
    if (stop !== (preferences.voiceStopWord !== false)) patch.voiceStopWord = stop;
    if (toIdleMs(idleSec) !== (preferences.voiceIdleMs || DEFAULT_IDLE_MS)) patch.voiceIdleMs = toIdleMs(idleSec);
    if (toStandbyMs(standbyMin) !== (preferences.voiceStandbyMs || DEFAULT_STANDBY_MS)) patch.voiceStandbyMs = toStandbyMs(standbyMin);
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
      </select><small>{status?.outputs?.length ? 'Your choice temporarily becomes the Windows output during voice. It is restored when voice ends.' : 'Uses your system output. Change speakers in your device settings.'}</small><small>Speakers pause listening during replies to prevent feedback. Recognized headphones keep voice interruption.</small></div>
      <div className="voice-settings-audio-actions"><button type="button" className="settings-secondary" disabled={locked || dirty || !preferences.hasSarvamKey} onClick={() => void test()}><Icon name="broadcast" size={14} />{testing ? 'Playing test…' : 'Test speakers'}</button><button type="button" className="settings-text-button" disabled={locked || refreshing} onClick={() => void refresh()}>{refreshing ? 'Refreshing…' : 'Refresh devices'}</button></div>
      <p className="voice-settings-hint">{dirty ? 'Save your changes before testing.' : 'No sound? Try your laptop speakers first, then test your headset.'}</p>
    </section>
    <section className="settings-panel" aria-labelledby="voice-handsfree-title">
      <div className="settings-section-lead"><span className="settings-section-symbol"><Icon name="layers" size={18} /></span><div><h2 id="voice-handsfree-title">Hands-free</h2><p>How Ankita pays attention during a voice session.</p></div><span className="settings-value-tag">{status?.state?.active ? 'In use' : 'Ready'}</span></div>
      <label className="settings-switch-row">
        <span><strong>Wake word</strong><small>{wake ? 'Ankita rests on "Ankita" and asks for it after every request, so nearby talk is never transcribed.' : 'Off: the microphone listens freely for the whole session.'}</small></span>
        <input type="checkbox" role="switch" aria-label="Wake word" checked={wake} onChange={event => { setWake(event.target.checked); setNotice(''); }} />
      </label>
      <label className="settings-switch-row">
        <span><strong>Stop word</strong><small>{stop ? 'Saying "stop" or "cancel" cuts a reply or stops current work.' : 'Off: use the Stop button instead.'}</small></span>
        <input type="checkbox" role="switch" aria-label="Stop word" checked={stop} onChange={event => { setStop(event.target.checked); setNotice(''); }} />
      </label>
      <div className="settings-form-pair voice-handsfree-timers">
        <div className="settings-field"><label htmlFor="voice-idle">Keep listening after “Ankita” (seconds)</label>
          <input id="voice-idle" type="number" min={IDLE_MIN_SEC} max={IDLE_MAX_SEC} step="5" inputMode="numeric" value={idleSec} disabled={!wake} onChange={event => { setIdleSec(event.target.value); setNotice(''); }} />
          <small>How long a bare wake word keeps the microphone open. 0 returns to standby at once.</small>
        </div>
        <div className="settings-field"><label htmlFor="voice-standby">Microphone off after (minutes)</label>
          <input id="voice-standby" type="number" min={STANDBY_MIN_MIN} max={STANDBY_MAX_MIN} step="1" inputMode="numeric" value={standbyMin} onChange={event => { setStandbyMin(event.target.value); setNotice(''); }} />
          <small>Quiet time in standby before the microphone closes until you resume.</small>
        </div>
      </div>
      <p className="settings-help">In standby, speech is checked for the wake word by the speech service; anything without it is discarded.</p>
    </section>
    <section className="settings-panel" aria-labelledby="voice-connections-title">
      <div className="settings-section-lead"><span className="settings-section-symbol"><Icon name="key" size={18} /></span><div><h2 id="voice-connections-title">Voice connections</h2><p>Sarvam for speech. Meta through Baseten for requests.</p></div></div>
      <div className="settings-field"><div className="settings-field-heading"><label htmlFor="voice-sarvam">Sarvam API key</label>{preferences.hasSarvamKey && <span className="settings-saved">Saved</span>}</div><input id="voice-sarvam" type="password" autoComplete="new-password" disabled={locked} value={sarvam} onChange={event => setSarvam(event.target.value)} placeholder={preferences.hasSarvamKey ? 'Enter a new key to replace it' : 'Enter your Sarvam key'} /><small>Listens to your voice and speaks replies.</small></div>
      <div className="settings-field"><div className="settings-field-heading"><label htmlFor="voice-baseten">Baseten API key</label>{preferences.hasBasetenKey && <span className="settings-saved">Saved</span>}</div><input id="voice-baseten" type="password" autoComplete="new-password" disabled={locked} value={baseten} onChange={event => setBaseten(event.target.value)} placeholder={preferences.hasBasetenKey ? 'Enter a new key to replace it' : 'Enter your Baseten key'} /><small>Plans and carries out your voice requests.</small></div>
    </section>
    <div className="settings-savebar"><span>Saved privately on this device</span><button type="button" className="settings-primary" disabled={busy || testing || !dirty} onClick={() => void save()}>{busy ? 'Saving…' : 'Save voice settings'}</button></div>
    <p className={`voice-settings-feedback ${error || issues.length ? 'is-error' : ''}`} role="status" aria-live="polite">{feedback || (status?.ready ? 'Voice is ready.' : 'Checking your setup…')}</p>
    <div className="settings-note"><Icon name="info" size={15} /><span>End voice stops listening and speaking. Delegated work continues until you stop it.</span></div>
  </div>;
}
