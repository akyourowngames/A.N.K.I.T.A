import { useCallback, useEffect, useState } from 'react';
import type { BrowserPlugin, BrowserPluginsOverview } from '../../../shared/wire';
import { Icon } from './Icons';

function errorText(error: unknown) {
  return (error instanceof Error ? error.message : String(error)).replace(/^Error invoking remote method ['"]engine:invoke['"]:\s*(?:Error:\s*)?/, '');
}

function BrowserMark({ mode }: { mode: 'isolated' | 'local' }) {
  return mode === 'isolated'
    ? <span className="plugin-logo browser-mark" aria-hidden="true"><svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M4 7c5-2 9-2 13 0l-1 15c-3 5-6 7-10 5L4 7Z"/><path d="M14 9c4-3 9-4 14-1l-2 17c-4 3-8 3-12 0V9Z"/><path d="M8 13h3m9 0h3M8 20c2 2 3 2 5 0m5 0c2 2 3 2 5 0"/></svg></span>
    : <span className="plugin-logo browser-mark" aria-hidden="true"><svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="16" cy="16" r="11"/><circle cx="16" cy="16" r="4.5"/><path d="M16 11.5h10M12 18.5 7 10m11 9.5-5 7"/></svg></span>;
}

function SiteRules({ plugin, busy, onChange }: { plugin: BrowserPlugin; busy: boolean; onChange: (kind: 'allow' | 'block', site: string, add: boolean) => void }) {
  const [draft, setDraft] = useState({ allow: '', block: '' });
  const add = (kind: 'allow' | 'block') => {
    const site = draft[kind].trim();
    if (!site) return;
    onChange(kind, site, true);
    setDraft(current => ({ ...current, [kind]: '' }));
  };
  return <div className="browser-site-rules"><div className="browser-site-rules-heading"><strong>Site access</strong><small>Blocked sites always win. An allow list limits where this browser can open.</small></div>
    {(['allow', 'block'] as const).map(kind => <div className="browser-site-rule" key={kind}>
      <label htmlFor={`${plugin.mode}-${kind}-site`}>{kind === 'allow' ? 'Allowed' : 'Blocked'}</label>
      <div className="browser-site-rule-input"><input id={`${plugin.mode}-${kind}-site`} placeholder="example.com" value={draft[kind]} onChange={event => setDraft(current => ({ ...current, [kind]: event.target.value }))} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); add(kind); } }} disabled={busy} /><button type="button" onClick={() => add(kind)} disabled={busy || !draft[kind].trim()}>Add</button></div>
      <div className="browser-site-chips">{(kind === 'allow' ? plugin.allowedSites : plugin.blockedSites).map(site => <button type="button" key={site} title={`Remove ${site}`} onClick={() => onChange(kind, site, false)} disabled={busy}>{site} <span aria-hidden="true">×</span></button>)}</div>
    </div>)}
  </div>;
}

function BrowserDetails({ plugin, busy, progress, onToggle, onInstall, onStart, onMode, onHeadless, onPort, onTest, onSiteRule }: {
  plugin: BrowserPlugin; busy: string | null; progress: string;
  onToggle: () => void; onInstall: () => void; onStart: () => void; onMode: (mode: 'profile' | 'port' | 'active') => void;
  onHeadless: (value: boolean) => void; onPort: (value: number) => void; onTest: (port: number) => void;
  onSiteRule: (kind: 'allow' | 'block', site: string, add: boolean) => void;
}) {
  const [portDraft, setPortDraft] = useState(String(plugin.port || 9222));
  useEffect(() => setPortDraft(String(plugin.port || 9222)), [plugin.port]);
  const local = plugin.mode === 'local';
  return <>
    <BrowserMark mode={plugin.mode} /><h2 id="browser-detail-title">{plugin.name}</h2><p>{local ? 'Use a separate Chrome profile, a debug port, or your existing session.' : 'A separate Chromium profile for browsing, with its own cookies and sign-ins.'}</p>
    <div className="browser-detail-enabled"><div><strong>{plugin.enabled ? 'Enabled' : 'Disabled'}</strong><small>{plugin.enabled ? plugin.ready ? 'Ready to browse' : plugin.reason : 'Enable to make this browser available'}</small></div><button type="button" role="switch" className={`skill-toggle ${plugin.enabled ? 'on' : ''}`} aria-checked={plugin.enabled} aria-label={`${plugin.enabled ? 'Disable' : 'Enable'} ${plugin.name}`} onClick={onToggle} disabled={busy !== null}><span /></button></div>
    <div className="browser-plugin-details">
      {!local ? <>
        <p>Runs in its own profile. Sites cannot use your Chrome cookies or saved logins.</p>
        {!plugin.ready && <div className="browser-plugin-setup-row"><span>Chromium download · about 310 MB</span><button type="button" className="browser-plugin-primary" onClick={onInstall} disabled={busy !== null}>{busy === plugin.mode ? 'Downloading…' : 'Download Chromium'}</button></div>}
        {busy === plugin.mode && progress && <div className="browser-plugin-progress" role="status">{progress}</div>}
        <label className="browser-plugin-check"><input type="checkbox" checked={plugin.headless !== false} onChange={event => onHeadless(event.target.checked)} disabled={busy !== null} /><span>Run in the background</span></label>
      </> : <>
        <p>Choose how Ankita connects. Active session uses your existing tabs and asks permission in Chrome each time.</p>
        <div className="browser-mode-picker" role="group" aria-label="Chrome connection mode">
          {(['profile', 'port', 'active'] as const).map(mode => <button key={mode} type="button" className={plugin.connection === mode ? 'active' : ''} onClick={() => onMode(mode)} disabled={busy !== null}>{mode === 'profile' ? 'Private Chrome' : mode === 'port' ? 'Debug port' : 'My session'}</button>)}
        </div>
        {plugin.connection === 'active' && <div className="browser-plugin-instruction"><span>1. Open <code>chrome://inspect/#remote-debugging</code> and enable remote debugging.</span><button type="button" onClick={() => void navigator.clipboard.writeText('chrome://inspect/#remote-debugging')}>Copy address</button></div>}
        {plugin.connection === 'port' && <div className="browser-plugin-instruction"><label htmlFor="chrome-port">Chrome debug port</label><input id="chrome-port" type="number" min="1" max="65535" value={portDraft} onChange={event => setPortDraft(event.target.value)} onBlur={() => { const port = Number(portDraft); if (Number.isInteger(port) && port >= 1 && port <= 65535 && port !== plugin.port) onPort(port); }} /><button type="button" onClick={() => onTest(Number(portDraft))} disabled={busy !== null || !Number.isInteger(Number(portDraft)) || Number(portDraft) < 1 || Number(portDraft) > 65535}>Test port</button></div>}
        <div className="browser-plugin-setup-row"><span>{plugin.ready ? 'Connected to Chrome' : 'Chrome permission may appear when you start'}</span><button type="button" className="browser-plugin-primary" onClick={onStart} disabled={busy !== null || !plugin.enabled}>{busy === plugin.mode ? 'Connecting…' : plugin.ready ? 'Reconnect' : 'Start connection'}</button></div>
      </>}
      <SiteRules plugin={plugin} busy={busy !== null} onChange={onSiteRule} />
      <small className="browser-detail-version">{local ? 'Chrome DevTools MCP 1.10.1' : 'Playwright · Chromium'}</small>
    </div>
  </>;
}

export function BrowserPluginsSection() {
  const [overview, setOverview] = useState<BrowserPluginsOverview | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [progress, setProgress] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<'isolated' | 'local' | null>(null);
  const refresh = useCallback(async () => {
    try { setOverview(await window.ankita.invoke<BrowserPluginsOverview>('browserPluginsOverview')); }
    catch (cause) { setError(errorText(cause)); }
  }, []);
  useEffect(() => { void refresh(); return window.ankita.onEvent(event => {
    if (event.type === 'browser-plugins-changed') void refresh();
    if (event.type === 'browser-install-progress') setProgress(event.text);
  }); }, [refresh]);
  const act = async (mode: string, action: string, payload?: object, success?: string) => {
    setBusy(mode); setError(''); setNotice('');
    try { await window.ankita.invoke(action, payload); if (success) setNotice(success); await refresh(); }
    catch (cause) { setError(errorText(cause)); }
    finally { setBusy(null); }
  };
  const cards = overview ? [overview.isolated, overview.local] : [];
  const plugin = selected && overview ? overview[selected] : null;
  useEffect(() => {
    if (!selected) return;
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setSelected(null); };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [selected]);
  return <section className="plugins-section browser-plugins-section" aria-labelledby="browser-plugins-heading">
    <div className="plugins-section-head"><h2 id="browser-plugins-heading">By Ankita team</h2></div>
    {error && <div className="plugins-alert" role="alert"><Icon name="alert" size={16} /><span>{error}</span><button type="button" onClick={() => setError('')} aria-label="Dismiss browser error"><Icon name="close" size={15} /></button></div>}
    {notice && <div className="plugins-notice" role="status"><Icon name="check" size={16} /><span>{notice}</span><button type="button" onClick={() => setNotice('')} aria-label="Dismiss browser notice"><Icon name="close" size={15} /></button></div>}
    {!overview ? <div className="plugins-loading">Checking browsers…</div> : <div className="plugin-grid">{cards.map(item => <div className="plugin-row" key={item.mode}>
      <button type="button" className="plugin-row-main" onClick={() => setSelected(item.mode)} aria-label={`Configure ${item.name}`}><BrowserMark mode={item.mode} /><span className="plugin-row-copy"><strong>{item.name}</strong><small>{item.mode === 'isolated' ? 'Browse in a separate Chromium profile' : 'Browse with Chrome or your signed-in session'}</small></span></button>
      {item.enabled && <span className={`plugin-row-state ${item.ready ? '' : 'pending'}`}>{item.ready ? 'Ready' : 'Setup needed'}</span>}
      <button type="button" className="plugin-row-action" aria-label={item.enabled ? `Open ${item.name} options` : `Enable ${item.name}`} disabled={busy !== null} onClick={() => { setSelected(item.mode); if (!item.enabled) void act(item.mode, 'browserPluginSetEnabled', { mode: item.mode, enabled: true }); }}><Icon name={item.enabled ? 'arrowRight' : 'plus'} size={17} /></button>
    </div>)}</div>}
    {plugin && <div className="plugins-drawer-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setSelected(null); }}><section className="plugins-drawer" role="dialog" aria-modal="true" aria-labelledby="browser-detail-title"><div className="plugins-drawer-top"><span>Browser settings</span><button type="button" className="icon-button" onClick={() => setSelected(null)} aria-label="Close browser settings"><Icon name="close" size={17} /></button></div><div className="plugins-drawer-body"><BrowserDetails key={plugin.mode} plugin={plugin} busy={busy} progress={progress}
      onToggle={() => void act(plugin.mode, 'browserPluginSetEnabled', { mode: plugin.mode, enabled: !plugin.enabled })}
      onInstall={() => void act(plugin.mode, 'browserPluginInstallChromium', undefined, 'Chromium is ready.')}
      onStart={() => void act(plugin.mode, 'browserPluginStartChrome', undefined, 'Chrome is connected.')}
      onMode={mode => void act(plugin.mode, 'browserPluginConfigureChrome', { connection: mode, port: plugin.port || 9222 })}
      onHeadless={headless => void act(plugin.mode, 'browserPluginSetHeadless', { headless })}
      onPort={port => void act(plugin.mode, 'browserPluginConfigureChrome', { connection: 'port', port })}
      onTest={port => void act(plugin.mode, 'browserPluginTestChromePort', { port }, `Chrome is listening on port ${port}.`)}
      onSiteRule={(kind, site, add) => void act(plugin.mode, 'browserPluginSiteRule', { mode: plugin.mode, kind, site, add })}
    />{error && <p className="browser-details-error" role="alert">{error}</p>}{notice && <p className="browser-details-notice" role="status">{notice}</p>}</div></section></div>}
  </section>;
}
