import { useEffect, useRef, useState } from 'react';
import type { DesktopPreferences, DesktopSettingsResult, DesktopSettingsUpdate, Model, Routine, Teammate } from '../../../shared/wire';
import { Icon } from './Icons';
import { detectTimezone, timezoneSuggestions } from '../lib/timezones';
import { TeammateAvatar } from './TeammateAvatar';
import { nextRunLabel } from '../lib/jobs';
import { CHATGPT_BROWSER_PROVIDER, CHATGPT_BROWSER_LABEL, CHATGPT_CURRENT_MODEL_LABEL } from '../../../shared/chatgpt-browser.mjs';
import { ChatGptConnection } from './ChatGptConnection';
import { PhonePairingSettings } from './PhonePairingSettings';
import { ChannelsSettings } from './ChannelsSettings';
import { cleanErrorMessage } from '../../../shared/error-notices.mjs';
import { VoiceSettings } from './voice/VoiceSettings';

export type SettingsTab = 'model' | 'providers' | 'profile' | 'images' | 'channels' | 'phone' | 'background' | 'privacy' | 'appearance' | 'about' | 'voice';

const tabs: { id: SettingsTab; label: string; icon: string }[] = [
  { id: 'model', label: 'Model', icon: 'cube' },
  { id: 'providers', label: 'Providers', icon: 'key' },
  { id: 'voice', label: 'Voice', icon: 'mic' },
  { id: 'profile', label: 'Profile', icon: 'user' },
  { id: 'images', label: 'Images', icon: 'sparkle' },
  { id: 'channels', label: 'Channels', icon: 'broadcast' },
  { id: 'phone', label: 'Phone', icon: 'phone' },
  { id: 'background', label: 'Background jobs', icon: 'clock' },
  { id: 'privacy', label: 'Privacy', icon: 'shield' },
  { id: 'appearance', label: 'Appearance', icon: 'palette' },
  { id: 'about', label: 'About', icon: 'info' },
];
const providers = [
  { id: 'copilot', name: 'GitHub Copilot', detail: 'Use your GitHub account' },
  { id: 'groq', name: 'Groq', detail: 'Fast hosted inference' },
  { id: 'kilo', name: 'Kilo', detail: 'Free and hosted models' },
  { id: 'custom', name: 'Custom provider', detail: 'OpenAI-compatible endpoint' },
  { id: CHATGPT_BROWSER_PROVIDER, name: CHATGPT_BROWSER_LABEL, detail: 'Your already-open ChatGPT chat' },
];
const themes: { id: DesktopPreferences['appearance']; name: string; detail: string }[] = [
  { id: 'graphite', name: 'Graphite', detail: 'The island’s graphite palette' },
  { id: 'mono', name: 'Mono', detail: 'Pure greyscale' },
  { id: 'slate', name: 'Slate', detail: 'Cool blue greys' },
];

type Secret = 'customApiKey' | 'groqApiKey' | 'kiloApiKey' | 'composioApiKey' | 'imageApiKey' | 'unsplashAccessKey' | 'pixabayApiKey';
type Draft = { provider: string; model: string; customApiBase: string; appearance: DesktopPreferences['appearance']; contextWindow: string; maxTokens: string; imageApiBase: string; imageModel: string; username: string; timeZone: string } & Record<Secret, string>;
const savedFlag: Record<Secret, keyof DesktopPreferences> = {
  customApiKey: 'hasCustomApiKey', groqApiKey: 'hasGroqKey', kiloApiKey: 'hasKiloKey', composioApiKey: 'hasComposioKey',
  imageApiKey: 'hasImageApiKey', unsplashAccessKey: 'hasUnsplashAccessKey', pixabayApiKey: 'hasPixabayApiKey',
};
function fromPreferences(value: DesktopPreferences): Draft {
  return { provider: value.provider, model: value.model, customApiBase: value.customApiBase, appearance: value.appearance,
    contextWindow: value.contextWindow ? String(value.contextWindow) : '', maxTokens: value.maxTokens ? String(value.maxTokens) : '',
    imageApiBase: value.imageApiBase || '', imageModel: value.imageModel || 'gpt-image-1',
    username: value.username || '', timeZone: value.timeZone || '',
    customApiKey: '', groqApiKey: '', kiloApiKey: '', composioApiKey: '', imageApiKey: '', unsplashAccessKey: '', pixabayApiKey: '' };
}

export function SettingsDialog({ tab, onTab, onClose, preferences, models, teammates, jobs, version, onSaved, onOpenJobs, selectedThreadId }: {
  tab: SettingsTab; onTab: (tab: SettingsTab) => void; onClose: () => void;
  preferences: DesktopPreferences; models: Model[]; teammates: Teammate[]; version: string; onSaved: (result: DesktopSettingsResult) => void;
  jobs: Routine[]; onOpenJobs: (job?: Routine) => void;
  selectedThreadId?: string | null;
}) {
  const [draft, setDraft] = useState(() => fromPreferences(preferences));
  const [removed, setRemoved] = useState<Secret[]>([]);
  const [visible, setVisible] = useState<Secret[]>([]);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [notice, setNotice] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const [testResult, setTestResult] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const [hostSettings, setHostSettings] = useState({ startAtLogin: false, supported: false });
  const [hostBusy, setHostBusy] = useState(false);
  const [hostLoaded, setHostLoaded] = useState(false);
  const [scrubConfirm, setScrubConfirm] = useState(false);
  useEffect(() => {
    if (tab !== 'background') return;
    let active = true;
    setHostLoaded(false);
    void window.ankita.invoke<typeof hostSettings>('scheduleHostSettings').then(value => { if (active) { setHostSettings(value); setHostLoaded(true); } }).catch(error => { if (active) setNotice({ tone: 'error', text: cleanErrorMessage(error) }); });
    return () => { active = false; };
  }, [tab]);

  useEffect(() => { setDraft(fromPreferences(preferences)); setRemoved([]); }, [preferences]);
  useEffect(() => { dialog.current?.focus(); }, []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
      if (event.key !== 'Tab' || !dialog.current) return;
      const elements = [...dialog.current.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled)')];
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft(current => ({ ...current, [key]: value }));
  const hasSaved = (key: Secret) => Boolean(preferences[savedFlag[key]]) && !removed.includes(key);
  const secretField = (key: Secret, label: string, placeholder: string, detail?: string) => <div className="settings-field" key={key}>
    <div className="settings-field-heading"><label htmlFor={`setting-${key}`}>{label}</label>{hasSaved(key) && <span className="settings-saved">Saved</span>}{removed.includes(key) && <span className="settings-removed">Will remove</span>}</div>
    <div className="settings-secret-control">
      <input id={`setting-${key}`} type={visible.includes(key) ? 'text' : 'password'} value={draft[key]}
        onChange={event => { set(key, event.target.value); setRemoved(current => current.filter(item => item !== key)); if (key === 'customApiKey') setTestResult(null); }}
        placeholder={hasSaved(key) ? 'Enter a new key to replace it' : placeholder} autoComplete="off" spellCheck={false} />
      <button type="button" aria-label={visible.includes(key) ? `Hide ${label}` : `Show ${label}`} onClick={() => setVisible(current => current.includes(key) ? current.filter(item => item !== key) : [...current, key])}><Icon name={visible.includes(key) ? 'eyeOff' : 'eye'} size={15} /></button>
    </div>
    <div className="settings-field-foot"><small>{detail || (hasSaved(key) ? 'Your saved key stays hidden.' : 'Stored on this device.')}</small>
      {hasSaved(key) && <button type="button" className="settings-text-button" onClick={() => { set(key, ''); setRemoved(current => [...current, key]); }}>Remove key</button>}
      {removed.includes(key) && <button type="button" className="settings-text-button" onClick={() => setRemoved(current => current.filter(item => item !== key))}>Undo</button>}
    </div>
  </div>;

  const save = async () => {
    const patch: DesktopSettingsUpdate = {};
    if (tab === 'model') {
      if (draft.model !== preferences.model) patch.model = draft.model;
      // Only send these when the backend advertises them. An older main process
      // would reject the unknown key and block the whole save.
      if (typeof preferences.contextWindow === 'number') {
        const contextWindow = Number(draft.contextWindow) || 0;
        if (contextWindow !== preferences.contextWindow) patch.contextWindow = contextWindow;
      }
      if (typeof preferences.maxTokens === 'number') {
        const maxTokens = Number(draft.maxTokens) || 0;
        if (maxTokens !== preferences.maxTokens) patch.maxTokens = maxTokens;
      }
    }
    if (tab === 'appearance' && draft.appearance !== preferences.appearance) patch.appearance = draft.appearance;
    if (tab === 'profile') {
      // Guarded like the model numbers: an older main process drops unknown
      // keys instead of failing, so these checks only gate what we send.
      if (typeof preferences.username === 'string' && draft.username.trim() !== (preferences.username || '')) patch.username = draft.username.trim();
      if (typeof preferences.timeZone === 'string' && draft.timeZone.trim() !== (preferences.timeZone || '')) patch.timeZone = draft.timeZone.trim();
    }
    if (tab === 'providers') {
      if (draft.provider !== preferences.provider) patch.provider = draft.provider;
      if (draft.customApiBase !== preferences.customApiBase) patch.customApiBase = draft.customApiBase;
      for (const key of Object.keys(savedFlag) as Secret[]) {
        if (draft[key]) patch[key] = draft[key];
        else if (removed.includes(key)) patch[key] = '';
      }
    }
    if (tab === 'images') {
      if (draft.imageApiBase !== preferences.imageApiBase) patch.imageApiBase = draft.imageApiBase;
      if (draft.imageModel !== preferences.imageModel) patch.imageModel = draft.imageModel;
      for (const key of ['imageApiKey', 'unsplashAccessKey', 'pixabayApiKey'] as const) {
        if (draft[key]) patch[key] = draft[key];
        else if (removed.includes(key)) patch[key] = '';
      }
    }
    if (!Object.keys(patch).length) { setNotice({ tone: 'ok', text: 'Everything is up to date.' }); return; }
    setBusy(true); setNotice(null);
    try {
      const result = await window.ankita.invoke<DesktopSettingsResult>('saveDesktopSettings', patch);
      onSaved(result);
      setDraft(fromPreferences(result.preferences)); setRemoved([]);
      setNotice({ tone: 'ok', text: 'Changes saved.' });
    } catch (error) { setNotice({ tone: 'error', text: cleanErrorMessage(error) }); }
    finally { setBusy(false); }
  };
  const test = async () => {
    setTesting(true); setTestResult(null);
    try {
      const result = await window.ankita.invoke<{ models: number }>('testCustomProvider', {
        apiBase: draft.customApiBase, ...(draft.customApiKey || removed.includes('customApiKey') ? { apiKey: draft.customApiKey } : {}),
      });
      setTestResult({ tone: 'ok', text: `Connected · ${result.models} model${result.models === 1 ? '' : 's'} found` });
    } catch (error) { setTestResult({ tone: 'error', text: cleanErrorMessage(error) }); }
    finally { setTesting(false); }
  };
  const applySecretScrubbing = async (enabled: boolean) => {
    setScrubConfirm(false); setBusy(true); setNotice(null);
    try {
      onSaved(await window.ankita.invoke<DesktopSettingsResult>('saveDesktopSettings', { secretScrubbing: enabled, ...(!enabled ? { secretWarningSeen: true } : {}) }));
      setNotice({ tone: 'ok', text: enabled ? 'Secret scrubbing is on.' : 'Secret scrubbing is off.' });
    } catch (error) { setNotice({ tone: 'error', text: cleanErrorMessage(error) }); }
    finally { setBusy(false); }
  };
  const changeSecretScrubbing = (enabled: boolean) => {
    if (!enabled && !preferences.secretWarningSeen) { setScrubConfirm(true); return; }
    void applySecretScrubbing(enabled);
  };
  const model = models.find(item => item.id === draft.model);
  const activeJobs = jobs.filter(job => job.enabled).length;
  const runningJobs = jobs.filter(job => job.running).length;
  const changeHost = async (startAtLogin: boolean) => {
    setHostBusy(true); setNotice(null);
    try { setHostSettings(await window.ankita.invoke<typeof hostSettings>('scheduleHostSettings', { startAtLogin })); }
    catch (error) { setNotice({ tone: 'error', text: cleanErrorMessage(error) }); }
    finally { setHostBusy(false); }
  };
  const pauseJobs = async () => {
    setHostBusy(true); setNotice(null);
    try { await window.ankita.invoke('schedulePauseAll'); setNotice({ tone: 'ok', text: 'All scheduled jobs paused. Active runs can finish; open a task to stop its run.' }); }
    catch (error) { setNotice({ tone: 'error', text: cleanErrorMessage(error) }); }
    finally { setHostBusy(false); }
  };

  return <div className="settings-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="settings-window" ref={dialog} role="dialog" aria-modal="true" aria-labelledby="settings-title" tabIndex={-1}>
      <aside className="settings-nav">
        <div className="settings-nav-brand"><TeammateAvatar /><div><strong>Ankita</strong><small>Preferences</small></div></div>
        <nav aria-label="Settings sections">{tabs.map(item => <button key={item.id} type="button" aria-label={item.label} title={item.label} className={`settings-nav-item ${tab === item.id ? 'active' : ''}`} aria-current={tab === item.id ? 'page' : undefined} onClick={() => { onTab(item.id); setNotice(null); }}><Icon name={item.icon} size={15} /><span>{item.label}</span></button>)}</nav>
        <div className="settings-nav-foot">Made with care by Krish.<br />Version {version || '—'}</div>
      </aside>
      <main className="settings-main">
        <div className="settings-top"><span>Settings / {tabs.find(item => item.id === tab)?.label}</span><button type="button" className="icon-button" onClick={onClose} aria-label="Close settings"><Icon name="close" size={17} /></button></div>
        <div className="settings-scroll" key={tab}>
          {tab === 'voice' && <VoiceSettings preferences={preferences} onSaved={onSaved} />}
          {tab === 'model' && <div className="settings-content">
            <div className="settings-heading"><span className="settings-heading-icon"><Icon name="cube" size={20} /></span><h1 id="settings-title">Model</h1><p>Choose the default model for new conversations.</p></div>
            <section className="settings-panel settings-model-choice"><div className="settings-section-lead"><span className="settings-section-symbol"><Icon name="cube" size={19} /></span><div><h2>Conversation model</h2><p>Your starting point for new teammates.</p></div><span className="settings-value-tag">{providers.find(item => item.id === preferences.provider)?.name || preferences.provider}</span></div><label className="settings-label" htmlFor="settings-model">Default model</label>
              <select id="settings-model" className="settings-select" value={draft.model} disabled={preferences.provider === CHATGPT_BROWSER_PROVIDER} onChange={event => set('model', event.target.value)}>
                <option value="">{preferences.provider === CHATGPT_BROWSER_PROVIDER ? CHATGPT_CURRENT_MODEL_LABEL : models.length ? 'Choose a model' : 'Connect a provider to see available models'}</option>
                {models.map(model => <option key={model.id} value={model.id}>{model.name || model.id}</option>)}
              </select>{model && <div className="settings-model-meta">{model.vendor && <span>{model.vendor}</span>}{model.context && <span>{model.context.toLocaleString()} token context</span>}{typeof model.tools === 'boolean' && <span>{model.tools ? 'Tool calling' : 'Text only'}</span>}</div>}<p className="settings-help">Change the active chat’s model in the composer. Teammates with their own model keep it.</p>
            </section>
            <section className="settings-panel settings-model-limits"><div className="settings-section-lead"><span className="settings-section-symbol"><Icon name="settings" size={19} /></span><div><h2>Conversation limits</h2><p>Leave these blank to use automatic limits.</p></div><span className="settings-value-tag">Optional</span></div>
              <div className="settings-form-pair">
                <div className="settings-field"><label htmlFor="settings-context-window">Context window (tokens)</label>
                  <input id="settings-context-window" type="number" min="0" step="1024" inputMode="numeric" value={draft.contextWindow} onChange={event => set('contextWindow', event.target.value)} placeholder="e.g. 128000" />
                  <small>Room for instructions, history and tool results. Override if your provider reports the wrong window.</small>
                </div>
                <div className="settings-field"><label htmlFor="settings-max-tokens">Max output tokens</label>
                  <input id="settings-max-tokens" type="number" min="0" step="256" inputMode="numeric" value={draft.maxTokens} onChange={event => set('maxTokens', event.target.value)} placeholder="e.g. 4096" />
                  <small>The maximum length of a reply. This space is reserved from the context window.</small>
                </div>
              </div>
            </section>
            <div className="settings-savebar"><span>Saved on this device</span><button type="button" className="settings-primary" onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save model settings'}</button></div>
            <button className="settings-navigation-link" onClick={() => { onTab('providers'); setNotice(null); }}><Icon name="key" size={15} /><span>Connect or change a provider</span><Icon name="arrowRight" size={15} /></button>
          </div>}
          {tab === 'providers' && <div className="settings-content">
            <div className="settings-heading"><span className="settings-heading-icon"><Icon name="key" size={20} /></span><h1 id="settings-title">Providers</h1><p>Connect a model provider and manage keys for connected apps.</p></div>
            <h2 className="settings-section-title">Model provider</h2>
            <div className="settings-provider-grid">{providers.map(item => <button type="button" key={item.id} className={`settings-provider-card ${draft.provider === item.id ? 'active' : ''}`} aria-pressed={draft.provider === item.id} onClick={() => { set('provider', item.id); setTestResult(null); }}><span className="settings-provider-radio" /><strong>{item.name}</strong><small>{item.detail}</small></button>)}</div>
            {draft.provider !== CHATGPT_BROWSER_PROVIDER && <div className="settings-panel settings-provider-detail">
              {draft.provider === 'copilot' && <><h2>GitHub Copilot</h2><p>Sign in through GitHub when you connect. Your account provides the available models.</p></>}
              {draft.provider === 'groq' && <><h2>Groq credentials</h2><p>Add your Groq API key to load available models.</p>{secretField('groqApiKey', 'API key', 'gsk_…')}</>}
              {draft.provider === 'kilo' && <><h2>Kilo credentials</h2><p>A key is optional for free models. Add one to access your account’s models.</p>{secretField('kiloApiKey', 'API key', 'Enter your Kilo key')}</>}
              {draft.provider === 'custom' && <><h2>Custom provider</h2><p>Use an OpenAI-compatible API. Include the version path, such as <code>/v1</code>.</p>
                <div className="settings-field"><label htmlFor="settings-custom-url">API base URL</label><input id="settings-custom-url" value={draft.customApiBase} onChange={event => { set('customApiBase', event.target.value); setTestResult(null); }} placeholder="http://localhost:11434/v1" spellCheck={false} /></div>
                {secretField('customApiKey', 'API key', 'Optional for local providers')}
                <div className="settings-provider-actions"><button type="button" className="settings-secondary" onClick={test} disabled={testing || !draft.customApiBase.trim()}>{testing ? 'Testing…' : 'Test connection'}</button><span role="status" className={testResult?.tone === 'error' ? 'settings-test-error' : 'settings-test-ok'}>{testResult?.text || 'Checks the endpoint and available models.'}</span></div>
              </>}
            </div>}
            {draft.provider === CHATGPT_BROWSER_PROVIDER && <ChatGptConnection teammates={teammates} initialThreadId={selectedThreadId} enabled={preferences.provider === CHATGPT_BROWSER_PROVIDER} />}
            <h2 className="settings-section-title">Connected apps</h2>
            <div className="settings-panel"><h2>Composio</h2><p>Connect Gmail, Slack, Notion and other app tools with your Composio project key.</p>{secretField('composioApiKey', 'Project key', 'Enter your Composio key')}</div>
            <div className="settings-savebar"><span>Keys are saved on this device and never shown again.</span><button type="button" className="settings-primary" onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save provider settings'}</button></div>
          </div>}
          {tab === 'images' && <div className="settings-content">
            <div className="settings-heading"><span className="settings-heading-icon"><Icon name="sparkle" size={20} /></span><h1 id="settings-title">Images</h1><p>Configure three separate image tools: original generation, Unsplash photos, and Pixabay photos or illustrations.</p></div>
            <h2 className="settings-section-title">Generate original images</h2>
            <div className="settings-panel">
              <p>Uses an OpenAI-compatible <code>/images/generations</code> endpoint. It saves generated files in <code>generated-images</code> in the current workspace.</p>
              <div className="settings-field"><label htmlFor="settings-image-api-base">Image API base URL</label><input id="settings-image-api-base" value={draft.imageApiBase} onChange={event => set('imageApiBase', event.target.value)} placeholder="Leave blank to use the current model provider (e.g. https://api.openai.com/v1)" spellCheck={false} /></div>
              <div className="settings-form-pair">
                <div className="settings-field"><label htmlFor="settings-image-model">Image model</label><input id="settings-image-model" value={draft.imageModel} onChange={event => set('imageModel', event.target.value)} placeholder="gpt-image-1" spellCheck={false} /></div>
                {secretField('imageApiKey', 'Image API key', 'Optional; falls back to the model provider key')}
              </div>
            </div>
            <h2 className="settings-section-title">Stock image search</h2>
            <div className="settings-panel">
              <p>These are separate search tools. Add each service's API key to enable its tool; search results include previews and attribution.</p>
              {secretField('unsplashAccessKey', 'Unsplash access key', 'Create an Unsplash developer app to get a key')}
              {secretField('pixabayApiKey', 'Pixabay API key', 'Get an API key from Pixabay')}
            </div>
            <div className="settings-provider-actions"><button type="button" className="settings-primary" onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save image settings'}</button><span>Keys stay on this device. You can also set IMAGE_API_BASE, IMAGE_API_KEY, IMAGE_MODEL, UNSPLASH_ACCESS_KEY, and PIXABAY_API_KEY in config.env.</span></div>
          </div>}
          {tab === 'channels' && <ChannelsSettings teammates={teammates} />}
          {tab === 'profile' && <div className="settings-content">
            <div className="settings-heading"><span className="settings-heading-icon"><Icon name="user" size={20} /></span><h1 id="settings-title">Profile</h1><p>How Ankita addresses you, and which clock it keeps.</p></div>
            <div className="settings-panel"><h2>About you</h2>
              <p>Your name appears in the assistant&apos;s instructions; your timezone drives journaling, reminders and quiet hours.</p>
              <div className="settings-field"><label htmlFor="setting-username">Display name</label>
                <input id="setting-username" value={draft.username} onChange={event => set('username', event.target.value)}
                  placeholder="e.g. Krish" maxLength={100} autoComplete="off" spellCheck={false} />
              </div>
              <div className="settings-field"><label htmlFor="setting-timezone">Timezone</label>
                <input id="setting-timezone" value={draft.timeZone} onChange={event => set('timeZone', event.target.value)}
                  list="settings-timezones" placeholder="e.g. Asia/Kolkata" autoComplete="off" spellCheck={false} />
                <datalist id="settings-timezones">{timezoneSuggestions(detectTimezone()).map(zone => <option key={zone} value={zone} />)}</datalist>
                <small>Blank means system local time. Any valid IANA zone works.</small>
              </div>
              <button type="button" className="settings-primary" onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save profile'}</button>
            </div>
          </div>}
          {tab === 'phone' && <PhonePairingSettings />}
          {tab === 'background' && <div className="settings-content">
            <div className="settings-heading"><span className="settings-heading-icon"><Icon name="clock" size={20} /></span><h1 id="settings-title">Background jobs</h1><p>The routine work, handled by your teammates.</p></div>
            <div className="settings-job-overview" aria-label="Scheduled task status"><div><strong>{jobs.length}</strong><span>Scheduled</span></div><div><strong>{activeJobs}</strong><span>Enabled</span></div><div><strong>{runningJobs}</strong><span>Running</span></div></div>
            <section className="settings-panel"><div className="settings-section-lead"><span className="settings-section-symbol"><Icon name="pulse" size={18} /></span><div><h2>Keep Ankita available</h2><p>Tasks keep running when the window is in the tray.</p></div></div>
              <label className="settings-switch-row"><span><strong>Start Ankita when I sign in</strong><small>{!hostLoaded ? 'Loading startup settings…' : hostSettings.supported ? 'Ready for scheduled work after you sign in.' : 'Startup control is unavailable on this system.'}</small></span><input type="checkbox" role="switch" checked={hostSettings.startAtLogin} disabled={!hostLoaded || !hostSettings.supported || hostBusy} onChange={event => void changeHost(event.target.checked)} /></label>
              <div className="settings-tray-note"><Icon name="info" size={14} /><span>Quit stops scheduling and active runs until you reopen Ankita.</span></div>
            </section>
            <section className="settings-background-tasks"><div className="section-heading"><h2>Your scheduled work</h2><button className="section-secondary" disabled={!teammates.length} onClick={() => onOpenJobs()}>Open tasks <Icon name="arrowRight" size={13} /></button></div>
              {jobs.length ? <div className="settings-job-list">{jobs.map(job => { const owner = teammates.find(item => item.id === job.threadId); return <button key={job.id} disabled={!owner && !job.deliveryThreadId} onClick={() => onOpenJobs(job)}><TeammateAvatar id={owner?.id} color={owner?.color} /><span><strong>{job.name}</strong><small>{owner?.name || 'Choose a teammate'} · {job.needsApproval ? 'Needs approval' : job.ownerMissing ? 'Owner missing' : nextRunLabel(job)}</small></span><Icon name="arrowRight" size={14} /></button>; })}</div> : <div className="settings-jobs-empty"><Icon name="clock" size={23} /><div><strong>No scheduled work yet</strong><p>Open a teammate’s tasks to set up the first one.</p></div></div>}
              <div className="settings-pause-row"><div><strong>Pause scheduled work</strong><small>Active runs can finish. Resume tasks individually.</small></div><button className="settings-secondary" disabled={hostBusy || !activeJobs} onClick={() => void pauseJobs()}>{hostBusy ? 'Updating…' : 'Pause all jobs'}</button></div>
            </section>
          </div>}
          {tab === 'privacy' && <div className="settings-content">
            <div className="settings-heading"><span className="settings-heading-icon"><Icon name="shield" size={20} /></span><h1 id="settings-title">Privacy</h1><p>Keep pasted secrets out of saved conversations.</p></div>
            <section className="settings-panel">
              <div className="settings-section-lead"><span className="settings-section-symbol"><Icon name="shield" size={18} /></span><div><h2>Secret scrubbing</h2><p>Supported API keys, tokens, passwords and private keys are removed from history, job logs and exports.</p></div></div>
              <label className="settings-switch-row"><span><strong>Scrub pasted secrets</strong><small>Explicitly saved secrets still go to the encrypted Secure store.</small></span><input type="checkbox" role="switch" checked={preferences.secretScrubbing !== false} disabled={busy} onChange={event => changeSecretScrubbing(event.target.checked)} /></label>
              <p className="settings-help">Arbitrary unlabeled secrets and secrets split between messages may not be detected.</p>
              {scrubConfirm && <div className="settings-confirm" role="alertdialog" aria-label="Turn off secret scrubbing">
                <Icon name="alert" size={16} />
                <div><strong>Turn off secret scrubbing?</strong><p>Passwords and tokens you paste can then be saved in plain text in chat history, job logs and exports.</p></div>
                <div className="settings-confirm-actions"><button type="button" className="settings-secondary" onClick={() => setScrubConfirm(false)}>Keep scrubbing</button><button type="button" className="settings-danger" onClick={() => void applySecretScrubbing(false)}>Turn off scrubbing</button></div>
              </div>}
            </section>
          </div>}
          {tab === 'appearance' && <div className="settings-content">
            <div className="settings-heading"><span className="settings-heading-icon"><Icon name="palette" size={20} /></span><h1 id="settings-title">Appearance</h1><p>Set the tone of your workspace.</p></div>
            <h2 className="settings-section-title">Theme</h2>
            <div className="settings-theme-grid">{themes.map(item => <button type="button" key={item.id} className={`settings-theme-card ${draft.appearance === item.id ? 'active' : ''}`} aria-pressed={draft.appearance === item.id} onClick={() => set('appearance', item.id)}><span className={`settings-theme-preview ${item.id}`}><i /><b /><em /></span><strong>{item.name}</strong><small>{item.detail}</small></button>)}</div>
            <div className="settings-note"><Icon name="info" size={15} />Your choice applies across the desktop app.</div>
            <button type="button" className="settings-primary" onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Apply appearance'}</button>
          </div>}
          {tab === 'about' && <div className="settings-content settings-about">
            <TeammateAvatar className="welcome-face" /><h1 id="settings-title">Ankita</h1><p className="settings-about-version">Version {version || '—'}</p>
            <div className="settings-about-rule" /><h2>Made by Krish.</h2>
            <p>Built at 15, while in high school. A personal AI workspace made with curiosity, care, and a lot of late nights.</p>
            <div className="settings-about-meta"><span>Desktop app</span><span>Built for the curious</span></div>
          </div>}
        </div>
        {notice && <div className={`settings-notice ${notice.tone === 'error' ? 'error' : ''}`} role="status"><Icon name={notice.tone === 'error' ? 'alert' : 'check'} size={15} />{notice.text}</div>}
      </main>
    </div>
  </div>;
}
