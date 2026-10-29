import { useEffect, useRef, useState } from 'react';
import type { ChannelField, ChannelPreferences, ChannelsView, Teammate } from '../../../shared/wire';
import { channelDraft, channelPatch, CHANNEL_FORM_SECTIONS, CAPABILITY_LABELS } from '../../../shared/channel-settings.mjs';
import { cleanErrorMessage } from '../../../shared/error-notices.mjs';
import { Icon } from './Icons';
import { StatusPill } from './StatusPill';
import './channels-settings.css';

type Draft = Record<string, string | boolean>;
type Notice = { tone: 'ok' | 'error'; text: string } | null;
type Pairing = { code: string; expiresAt: number } | null;
const ADVANCED_SECTION = 'advanced'; // Descriptor section hidden until the person asks for more controls.

export function ChannelsSettings({ teammates }: { teammates: Teammate[] }) {
  const [view, setView] = useState<ChannelsView | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [selected, setSelected] = useState('');
  const [removed, setRemoved] = useState<Record<string, string[]>>({});
  const [visible, setVisible] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [testResult, setTestResult] = useState<Notice>(null);
  const [refresh, setRefresh] = useState(0);
  const [senderId, setSenderId] = useState('');
  const [pairing, setPairing] = useState<Pairing>(null);
  const tabs = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let active = true;
    const apply = (next: ChannelsView) => {
      if (!active) return;
      setView(next); setSelected(current => current && next.channels[current] ? current : Object.keys(next.channels)[0] || '');
      setDrafts(current => {
        const merged = { ...current };
        for (const [id, settings] of Object.entries(next.channels)) merged[id] ||= channelDraft(settings);
        return merged;
      });
    };
    void window.ankita.invoke<ChannelsView>('getChannels').then(apply).catch(error => { if (active) setNotice({ tone: 'error', text: cleanErrorMessage(error) }); });
    const off = window.ankita.onEvent(event => { if (event.type === 'channels-updated') apply(event.channels); });
    return () => { active = false; off(); };
  }, [refresh]);
  useEffect(() => {
    if (!pairing) return;
    const timer = setTimeout(() => setPairing(null), Math.max(0, pairing.expiresAt - Date.now()));
    return () => clearTimeout(timer);
  }, [pairing]);

  const current = view?.channels[selected], draft = drafts[selected];
  const removedHere = removed[selected] || [];
  const choose = (id: string) => { setSelected(id); setNotice(null); setTestResult(null); setVisible([]); setPairing(null); setSenderId(''); };
  const set = (key: string, value: string | boolean) => {
    setDrafts(all => ({ ...all, [selected]: { ...all[selected], [key]: value } }));
    setRemoved(all => ({ ...all, [selected]: (all[selected] || []).filter(item => item !== key) }));
    setTestResult(null); setNotice(null);
  };
  const save = async () => {
    if (!current || !draft) return;
    try {
      const patch = channelPatch(current, draft, removedHere);
      if (!Object.keys(patch).length) { setNotice({ tone: 'ok', text: 'Everything is up to date.' }); return; }
      setBusy('save'); setNotice(null);
      const next = await window.ankita.invoke<ChannelsView>('saveChannelSettings', { channel: selected, patch });
      setView(next); setDrafts(all => ({ ...all, [selected]: channelDraft(next.channels[selected]) }));
      setRemoved(all => ({ ...all, [selected]: [] })); setVisible([]);
      setNotice({ tone: 'ok', text: 'Changes saved.' });
    } catch (error) { setNotice({ tone: 'error', text: cleanErrorMessage(error) }); }
    finally { setBusy(null); }
  };
  const verify = async () => {
    if (!current || !draft) return;
    setBusy('test'); setTestResult(null);
    try {
      const result = await window.ankita.invoke<{ account?: string | null }>('testChannel', { channel: selected, input: channelPatch(current, draft, removedHere) });
      setTestResult({ tone: 'ok', text: result.account ? `Connected as ${result.account}` : 'Connection verified' });
    } catch (error) { setTestResult({ tone: 'error', text: cleanErrorMessage(error) }); }
    finally { setBusy(null); }
  };
  const createPairing = async () => {
    setBusy('pair'); setPairing(null);
    try { setPairing(await window.ankita.invoke<NonNullable<Pairing>>('createChannelPairing', { channel: selected, senderId: senderId.trim() })); }
    catch (error) { setNotice({ tone: 'error', text: cleanErrorMessage(error) }); }
    finally { setBusy(null); }
  };
  const field = (key: string, spec: ChannelField, settings: ChannelPreferences) => {
    if (spec.requiresCapability && !settings.manifest.capabilities.includes(spec.requiresCapability)) return null;
    const id = `channel-${selected}-${key}`, label = spec.label || key, value = draft[key];
    const saved = Boolean(settings.secrets[key]) && !removedHere.includes(key);
    if (spec.kind === 'bool') return <label className="settings-switch-row channels-toggle" key={key}>
      <span><strong>{label}</strong>{spec.help && <small>{spec.help}</small>}</span>
      <input type="checkbox" role="switch" checked={Boolean(value)} onChange={event => set(key, event.target.checked)} />
    </label>;
    const required = settings.manifest.required.includes(key) && !(spec.kind === 'secret' && saved);
    return <div className={`settings-field ${spec.kind === 'secret' ? 'channels-secret-field' : ''}`} key={key}>
      <div className="settings-field-heading"><label htmlFor={id}>{label}</label>{saved && <span className="settings-saved">Saved</span>}{removedHere.includes(key) && <span className="settings-removed">Will remove</span>}</div>
      {spec.source === 'teammates' ? <select id={id} className="settings-select" value={String(value || '')} onChange={event => set(key, event.target.value)}>
        <option value="">{teammates.length ? 'Choose a teammate' : 'Create a teammate first'}</option>
        {teammates.map(teammate => <option key={teammate.id} value={teammate.id}>{teammate.name}</option>)}
      </select> : spec.kind === 'enum' ? <select id={id} className="settings-select" value={String(value || '')} onChange={event => set(key, event.target.value)}>
        {(spec.values || []).map(option => <option key={option} value={option}>{option}</option>)}
      </select> : spec.kind === 'secret' ? <>
        <div className="settings-secret-control"><input id={id} type={visible.includes(key) ? 'text' : 'password'} value={String(value || '')}
          required={required} onChange={event => set(key, event.target.value)} autoComplete="off" spellCheck={false}
          placeholder={saved ? 'Enter a new key to replace it' : `Enter ${label.toLowerCase()}`} maxLength={spec.maxLength} />
          <button type="button" aria-label={`${visible.includes(key) ? 'Hide' : 'Show'} ${label.toLowerCase()}`} onClick={() => setVisible(keys => keys.includes(key) ? keys.filter(item => item !== key) : [...keys, key])}><Icon name={visible.includes(key) ? 'eyeOff' : 'eye'} size={15} /></button>
        </div>
        <div className="settings-field-foot"><small>{saved ? 'Your saved key stays hidden.' : 'Keys stay on this device.'}</small>
          {saved && <button type="button" className="settings-text-button" onClick={() => { setDrafts(all => ({ ...all, [selected]: { ...all[selected], [key]: '' } })); setRemoved(all => ({ ...all, [selected]: [...removedHere, key] })); }}>Remove key</button>}
          {removedHere.includes(key) && <button type="button" className="settings-text-button" onClick={() => setRemoved(all => ({ ...all, [selected]: removedHere.filter(item => item !== key) }))}>Undo</button>}
        </div>
      </> : <input id={id} type={['int', 'float'].includes(spec.kind) ? 'number' : 'text'} value={String(value ?? '')}
        required={required} min={spec.min} max={spec.max} step={spec.kind === 'float' ? 'any' : undefined} maxLength={spec.maxLength}
        onChange={event => set(key, event.target.value)} autoComplete="off" spellCheck={false} />}
      {spec.help && <small>{spec.help}</small>}
    </div>;
  };
  const section = (name: string) => current && <section className="channels-form-section" key={name}>
    <h3>{CHANNEL_FORM_SECTIONS[name] || name}</h3>
    <div className="channels-field-grid">{Object.entries(current.manifest.fields).filter(([key, spec]) => (spec.section || (current.manifest.required.includes(key) ? 'connection' : ADVANCED_SECTION)) === name).map(([key, spec]) => field(key, spec, current))}</div>
  </section>;

  return <div className="settings-content channels-settings">
    <div className="settings-heading"><span className="settings-heading-icon"><Icon name="broadcast" size={20} /></span><h1 id="settings-title">Channels</h1><p>Talk to Ankita from the chat apps you already use.</p></div>
    {!view || !current || !draft ? <div className="settings-loading">{notice ? <><p role="alert">{notice.text}</p><button type="button" className="settings-secondary" onClick={() => { setNotice(null); setRefresh(value => value + 1); }}>Try again</button></> : 'Loading channels…'}</div> : <>
      {view.doctor?.error && <p className="channel-error" role="alert">{view.doctor.error}</p>}
      <div className="channels-picker" role="tablist" aria-label="Messaging channels" ref={tabs}>
        {Object.entries(view.channels).map(([id, settings]) => <button type="button" key={id} role="tab" id={`channel-tab-${id}`} aria-controls={`channel-panel-${id}`} aria-selected={id === selected} tabIndex={id === selected ? 0 : -1} disabled={Boolean(busy)}
          className={`channels-choice ${id === selected ? 'is-selected' : ''}`} onClick={() => choose(id)} onKeyDown={event => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
            event.preventDefault(); const ids = Object.keys(view.channels), index = ids.indexOf(id);
            const next = event.key === 'Home' ? ids[0] : event.key === 'End' ? ids.at(-1)! : ids[(index + (event.key === 'ArrowRight' ? 1 : -1) + ids.length) % ids.length];
            choose(next); tabs.current?.querySelector<HTMLButtonElement>(`#channel-tab-${next}`)?.focus();
          }}><span className="channels-monogram" aria-hidden="true">{settings.manifest.label[0]}</span><span className="channels-choice-copy"><strong>{settings.manifest.label}</strong><small>{settings.status.running ? 'Connected' : settings.status.error ? 'Needs attention' : 'Not connected'}</small></span><span className={`channels-dot ${settings.status.running ? 'is-live' : ''}`} aria-hidden="true" /></button>)}
      </div>
      <form className="channels-form" id={`channel-panel-${selected}`} role="tabpanel" aria-labelledby={`channel-tab-${selected}`} onSubmit={event => { event.preventDefault(); void save(); }}>
        <header className="channels-form-heading"><div><h2>{current.manifest.label}</h2><p>{current.manifest.description || 'Connect your private channel to a teammate.'}</p></div><StatusPill tone={current.status.error ? 'error' : current.status.running ? 'live' : 'idle'}>{current.status.running ? current.status.account || 'Connected' : current.status.error ? 'Needs attention' : 'Off'}</StatusPill></header>
        {current.status.error && <p className="channel-error" role="alert">{current.status.error}</p>}
        <div className="channels-capabilities" aria-label="Supported features">{current.manifest.capabilities.map(capability => <span key={capability}>{CAPABILITY_LABELS[capability] || capability}</span>)}</div>
        {current.manifest.docsUrl && <button type="button" className="settings-text-button channels-setup-link" onClick={() => void window.ankita.openExternal(current.manifest.docsUrl!)}>Open setup guide <Icon name="external" size={12} /></button>}
        <fieldset disabled={Boolean(busy) || view.doctor?.ok === false}>
          {Object.keys(CHANNEL_FORM_SECTIONS).filter(name => name !== ADVANCED_SECTION).map(section)}
          {!String(draft.allowedChatIds || '').trim() && !String(draft.allowFrom || '').trim() && <p className="channels-private-note"><Icon name="shield" size={15} />Nobody can send requests until you add an allowed conversation or person.</p>}
          <details className="channels-advanced"><summary>Advanced controls <Icon name="chevron" size={14} /></summary>{section(ADVANCED_SECTION)}
            {current.pairingEnabled === true && <div className="channels-pairing"><label htmlFor={`pair-sender-${selected}`}>Pair a specific person</label><div className="channels-pair-row"><input id={`pair-sender-${selected}`} value={senderId} onChange={event => { setSenderId(event.target.value); setPairing(null); }} placeholder="Their user ID" /><button type="button" className="settings-secondary" onClick={createPairing} disabled={!senderId.trim()}>Create code</button></div>
              {pairing && <><input aria-label="Pairing code" value={pairing.code} readOnly onFocus={event => event.target.select()} /><small>Share only with this person. They send /pair followed by this code. It expires shortly and works once.</small></>}
            </div>}
          </details>
        </fieldset>
        <div className="channels-actions"><button type="button" className="settings-secondary" onClick={verify} disabled={Boolean(busy)}>{busy === 'test' ? 'Testing…' : 'Test connection'}</button><button type="submit" className="settings-primary" disabled={Boolean(busy) || view.doctor?.ok === false}>{busy === 'save' ? 'Saving…' : 'Save changes'}</button><span role="status" className={(notice || testResult)?.tone === 'error' ? 'settings-test-error' : 'settings-test-ok'}>{notice?.text || testResult?.text || ''}</span></div>
      </form>
      <p className="channels-local-note"><Icon name="broadcast" size={15} />Runs on this device while Ankita is open. Use one host per bot connection.</p>
    </>}
  </div>;
}
