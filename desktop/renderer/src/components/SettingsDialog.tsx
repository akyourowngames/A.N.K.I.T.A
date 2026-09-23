import { useEffect, useRef, useState } from 'react';
import type { DesktopPreferences, DesktopSettingsResult, DesktopSettingsUpdate, Model } from '../../../shared/wire';
import { Icon } from './Icons';

export type SettingsTab = 'model' | 'providers' | 'appearance' | 'about';

const tabs: { id: SettingsTab; label: string; icon: string }[] = [
  { id: 'model', label: 'Model', icon: 'cube' },
  { id: 'providers', label: 'Providers', icon: 'key' },
  { id: 'appearance', label: 'Appearance', icon: 'palette' },
  { id: 'about', label: 'About', icon: 'info' },
];
const providers = [
  { id: 'copilot', name: 'GitHub Copilot', detail: 'Use your GitHub account' },
  { id: 'groq', name: 'Groq', detail: 'Fast hosted inference' },
  { id: 'kilo', name: 'Kilo', detail: 'Free and hosted models' },
  { id: 'custom', name: 'Custom provider', detail: 'OpenAI-compatible endpoint' },
];
const themes: { id: DesktopPreferences['appearance']; name: string; detail: string }[] = [
  { id: 'graphite', name: 'Graphite', detail: 'Warm, quiet neutrals' },
  { id: 'mono', name: 'Mono', detail: 'Pure greyscale' },
  { id: 'slate', name: 'Slate', detail: 'Cool blue greys' },
];

type Secret = 'customApiKey' | 'groqApiKey' | 'kiloApiKey' | 'composioApiKey';
type Draft = { provider: string; model: string; customApiBase: string; appearance: DesktopPreferences['appearance']; contextWindow: string; maxTokens: string } & Record<Secret, string>;
const savedFlag: Record<Secret, keyof DesktopPreferences> = {
  customApiKey: 'hasCustomApiKey', groqApiKey: 'hasGroqKey', kiloApiKey: 'hasKiloKey', composioApiKey: 'hasComposioKey',
};
function fromPreferences(value: DesktopPreferences): Draft {
  return { provider: value.provider, model: value.model, customApiBase: value.customApiBase, appearance: value.appearance,
    contextWindow: value.contextWindow ? String(value.contextWindow) : '', maxTokens: value.maxTokens ? String(value.maxTokens) : '',
    customApiKey: '', groqApiKey: '', kiloApiKey: '', composioApiKey: '' };
}

export function SettingsDialog({ tab, onTab, onClose, preferences, models, version, onSaved }: {
  tab: SettingsTab; onTab: (tab: SettingsTab) => void; onClose: () => void;
  preferences: DesktopPreferences; models: Model[]; version: string; onSaved: (result: DesktopSettingsResult) => void;
}) {
  const [draft, setDraft] = useState(() => fromPreferences(preferences));
  const [removed, setRemoved] = useState<Secret[]>([]);
  const [visible, setVisible] = useState<Secret[]>([]);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [notice, setNotice] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const [testResult, setTestResult] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const dialog = useRef<HTMLDivElement>(null);

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
      const contextWindow = Number(draft.contextWindow) || 0;
      const maxTokens = Number(draft.maxTokens) || 0;
      if (contextWindow !== preferences.contextWindow) patch.contextWindow = contextWindow;
      if (maxTokens !== preferences.maxTokens) patch.maxTokens = maxTokens;
    }
    if (tab === 'appearance' && draft.appearance !== preferences.appearance) patch.appearance = draft.appearance;
    if (tab === 'providers') {
      if (draft.provider !== preferences.provider) patch.provider = draft.provider;
      if (draft.customApiBase !== preferences.customApiBase) patch.customApiBase = draft.customApiBase;
      for (const key of Object.keys(savedFlag) as Secret[]) {
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
    } catch (error) { setNotice({ tone: 'error', text: (error as Error).message }); }
    finally { setBusy(false); }
  };
  const test = async () => {
    setTesting(true); setTestResult(null);
    try {
      const result = await window.ankita.invoke<{ models: number }>('testCustomProvider', {
        apiBase: draft.customApiBase, ...(draft.customApiKey || removed.includes('customApiKey') ? { apiKey: draft.customApiKey } : {}),
      });
      setTestResult({ tone: 'ok', text: `Connected · ${result.models} model${result.models === 1 ? '' : 's'} found` });
    } catch (error) { setTestResult({ tone: 'error', text: (error as Error).message }); }
    finally { setTesting(false); }
  };

  return <div className="settings-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="settings-window" ref={dialog} role="dialog" aria-modal="true" aria-labelledby="settings-title" tabIndex={-1}>
      <aside className="settings-nav">
        <div className="settings-nav-brand"><span className="settings-brand-mark">A</span><div><strong>Ankita</strong><small>Preferences</small></div></div>
        <nav aria-label="Settings sections">{tabs.map(item => <button key={item.id} type="button" className={`settings-nav-item ${tab === item.id ? 'active' : ''}`} aria-current={tab === item.id ? 'page' : undefined} onClick={() => { onTab(item.id); setNotice(null); }}><Icon name={item.icon} size={15} /><span>{item.label}</span></button>)}</nav>
        <div className="settings-nav-foot">Made with care by Krish.<br />Version {version || '—'}</div>
      </aside>
      <main className="settings-main">
        <div className="settings-top"><span>Settings / {tabs.find(item => item.id === tab)?.label}</span><button type="button" className="icon-button" onClick={onClose} aria-label="Close settings"><Icon name="close" size={17} /></button></div>
        <div className="settings-scroll" key={tab}>
          {tab === 'model' && <div className="settings-content">
            <div className="settings-heading"><span className="settings-heading-icon"><Icon name="cube" size={20} /></span><h1 id="settings-title">Model</h1><p>Choose the default model for new conversations.</p></div>
            <div className="settings-panel"><label className="settings-label" htmlFor="settings-model">Default model</label>
              <select id="settings-model" className="settings-select" value={draft.model} onChange={event => set('model', event.target.value)}>
                <option value="">{models.length ? 'Choose a model' : 'Connect a provider to see available models'}</option>
                {models.map(model => <option key={model.id} value={model.id}>{model.name || model.id}</option>)}
              </select><p className="settings-help">The composer can switch models for the active chat. Teammates with their own model keep it.</p>
              <div className="settings-form-pair">
                <div className="settings-field"><label htmlFor="settings-context-window">Context window (tokens)</label>
                  <input id="settings-context-window" type="number" min="0" step="1024" inputMode="numeric" value={draft.contextWindow} onChange={event => set('contextWindow', event.target.value)} placeholder="e.g. 128000" />
                  <small>Leave blank to use the model's advertised window, or the 32768 default. Some OpenAI-compatible endpoints report no window — set it here so tools and history have room.</small>
                </div>
                <div className="settings-field"><label htmlFor="settings-max-tokens">Max output tokens</label>
                  <input id="settings-max-tokens" type="number" min="0" step="256" inputMode="numeric" value={draft.maxTokens} onChange={event => set('maxTokens', event.target.value)} placeholder="e.g. 4096" />
                  <small>Leave blank to let the model decide. A pinned value is sent as <code>max_tokens</code> and reserved from the window.</small>
                </div>
              </div>
              <button type="button" className="settings-primary" onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save model settings'}</button>
            </div>
            <div className="settings-note"><Icon name="info" size={15} />Need a different model list? Choose a provider in the Providers section.</div>
          </div>}
          {tab === 'providers' && <div className="settings-content">
            <div className="settings-heading"><span className="settings-heading-icon"><Icon name="key" size={20} /></span><h1 id="settings-title">Providers</h1><p>Connect a model provider and manage keys for connected apps.</p></div>
            <h2 className="settings-section-title">Model provider</h2>
            <div className="settings-provider-grid">{providers.map(item => <button type="button" key={item.id} className={`settings-provider-card ${draft.provider === item.id ? 'active' : ''}`} aria-pressed={draft.provider === item.id} onClick={() => { set('provider', item.id); setTestResult(null); }}><span className="settings-provider-radio" /><strong>{item.name}</strong><small>{item.detail}</small></button>)}</div>
            <div className="settings-panel settings-provider-detail">
              {draft.provider === 'copilot' && <><h2>GitHub Copilot</h2><p>Sign in through GitHub when you connect. Your account provides the available models.</p></>}
              {draft.provider === 'groq' && <><h2>Groq credentials</h2><p>Add your Groq API key to load available models.</p>{secretField('groqApiKey', 'API key', 'gsk_…')}</>}
              {draft.provider === 'kilo' && <><h2>Kilo credentials</h2><p>A key is optional for free models. Add one to access your account’s models.</p>{secretField('kiloApiKey', 'API key', 'Enter your Kilo key')}</>}
              {draft.provider === 'custom' && <><h2>Custom provider</h2><p>Use an OpenAI-compatible API. Include the version path, such as <code>/v1</code>.</p>
                <div className="settings-field"><label htmlFor="settings-custom-url">API base URL</label><input id="settings-custom-url" value={draft.customApiBase} onChange={event => { set('customApiBase', event.target.value); setTestResult(null); }} placeholder="http://localhost:11434/v1" spellCheck={false} /></div>
                {secretField('customApiKey', 'API key', 'Optional for local providers')}
                <div className="settings-provider-actions"><button type="button" className="settings-secondary" onClick={test} disabled={testing || !draft.customApiBase.trim()}>{testing ? 'Testing…' : 'Test connection'}</button><span role="status" className={testResult?.tone === 'error' ? 'settings-test-error' : 'settings-test-ok'}>{testResult?.text || 'Checks the endpoint and available models.'}</span></div>
              </>}
            </div>
            <h2 className="settings-section-title">Connected apps</h2>
            <div className="settings-panel"><h2>Composio</h2><p>Connect Gmail, Slack, Notion and other app tools with your Composio project key.</p>{secretField('composioApiKey', 'Project key', 'Enter your Composio key')}</div>
            <div className="settings-provider-actions"><button type="button" className="settings-primary" onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save provider settings'}</button><span>Keys are saved on this device and never shown again.</span></div>
          </div>}
          {tab === 'appearance' && <div className="settings-content">
            <div className="settings-heading"><span className="settings-heading-icon"><Icon name="palette" size={20} /></span><h1 id="settings-title">Appearance</h1><p>Set the tone of your workspace.</p></div>
            <h2 className="settings-section-title">Theme</h2>
            <div className="settings-theme-grid">{themes.map(item => <button type="button" key={item.id} className={`settings-theme-card ${draft.appearance === item.id ? 'active' : ''}`} aria-pressed={draft.appearance === item.id} onClick={() => set('appearance', item.id)}><span className={`settings-theme-preview ${item.id}`}><i /><b /><em /></span><strong>{item.name}</strong><small>{item.detail}</small></button>)}</div>
            <div className="settings-note"><Icon name="info" size={15} />Your choice applies across the desktop app.</div>
            <button type="button" className="settings-primary" onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Apply appearance'}</button>
          </div>}
          {tab === 'about' && <div className="settings-content settings-about">
            <div className="settings-about-mark">A</div><h1 id="settings-title">Ankita</h1><p className="settings-about-version">Version {version || '—'}</p>
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
