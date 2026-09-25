import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { PluginCard, PluginService, PluginsCatalogPage, PluginsOverview } from '../../../shared/wire';
import { Icon } from './Icons';
import { WindowControls } from './WindowControls';
import { SkillsSection } from './SkillsSection';

const PAGE_SIZE = 24;
const featured = ['gmail', 'google_drive', 'googledrive', 'github', 'slack', 'notion', 'outlook', 'outlookemail'];

function title(slug: string) { return slug.replace(/[_-]+/g, ' ').replace(/\b\w/g, char => char.toUpperCase()); }
function message(error: unknown) {
  return (error instanceof Error ? error.message : String(error)).replace(/^Error invoking remote method ['"]engine:invoke['"]:\s*(?:Error:\s*)?/, '');
}

function PluginLogo({ slug, label }: { slug: string; label: string }) {
  if (slug === 'gmail') return <span className="plugin-logo gmail"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M5 24V9l11 8L27 9v15" fill="none" stroke="#e66b61" strokeWidth="4" strokeLinejoin="round"/><path d="M5 9v15" stroke="#7ea5d8" strokeWidth="4"/><path d="M27 9v15" stroke="#8db68b" strokeWidth="4"/></svg></span>;
  if (slug === 'github') return <span className="plugin-logo github"><svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M12 2a10 10 0 0 0-3.16 19.49c.5.09.68-.22.68-.48v-1.69c-2.78.61-3.37-1.18-3.37-1.18-.45-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.61.07-.61 1 .07 1.53 1.02 1.53 1.02.9 1.53 2.36 1.09 2.94.83.09-.65.35-1.09.64-1.34-2.22-.25-4.56-1.11-4.56-4.94 0-1.09.39-1.98 1.03-2.68-.1-.26-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02A9.6 9.6 0 0 1 12 6.96c.85 0 1.7.11 2.5.34 1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.39.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.69-4.57 4.94.36.31.69.92.69 1.85v2.61c0 .26.18.58.69.48A10 10 0 0 0 12 2Z"/></svg></span>;
  if (slug.includes('drive')) return <span className="plugin-logo drive"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M11 5h8l10 17h-8Z" fill="#e8c967"/><path d="M11 5h8L8 25H1Z" fill="#8cbc8e"/><path d="M8 25h21l-4 6H4Z" fill="#6e9bc9"/></svg></span>;
  if (slug === 'slack') return <span className="plugin-logo slack"><svg viewBox="0 0 32 32" aria-hidden="true"><rect x="12" y="2" width="7" height="17" rx="3.5" fill="#7da6d4"/><rect x="13" y="12" width="17" height="7" rx="3.5" fill="#e6be62"/><rect x="13" y="13" width="7" height="17" rx="3.5" fill="#9ac590"/><rect x="2" y="13" width="17" height="7" rx="3.5" fill="#dd7f83"/></svg></span>;
  const hue = [...slug].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 360;
  return <span className="plugin-logo letter" style={{ '--plugin-hue': hue } as React.CSSProperties}>{label.slice(0, 1).toUpperCase()}</span>;
}

export function PluginsPage({ chrome, sidebarOpen, onToggleSidebar, onOpenSettings, hasComposioKey, toolsRevision }: {
  chrome: string; sidebarOpen: boolean; onToggleSidebar: () => void; onOpenSettings: () => void; hasComposioKey: boolean; toolsRevision: number;
}) {
  const [overview, setOverview] = useState<PluginsOverview | null>(null);
  const [cards, setCards] = useState<PluginCard[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [visible, setVisible] = useState(PAGE_SIZE);
  const [tab, setTab] = useState<'discover' | 'installed'>('discover');
  const [section, setSection] = useState<'apps' | 'skills'>('apps');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [acting, setActing] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [alias, setAlias] = useState('');
  const [awaiting, setAwaiting] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<{ slug: string; accountId?: string; name: string } | null>(null);
  const requestId = useRef(0);

  const loadOverview = useCallback(async (reconnect = false) => {
    setRefreshing(true);
    try {
      const result = await window.ankita.invoke<PluginsOverview>(reconnect ? 'pluginsRefresh' : 'pluginsOverview');
      setOverview(result); setError('');
      return result;
    } catch (cause) { setError(message(cause)); return null; }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useEffect(() => { void loadOverview(); }, [loadOverview, hasComposioKey, toolsRevision]);

  useEffect(() => {
    if (!overview || overview.mode === 'unavailable') { setCards([]); setCursor(null); return; }
    const id = ++requestId.current;
    const timer = window.setTimeout(async () => {
      setCatalogBusy(true); setVisible(PAGE_SIZE);
      try {
        const result = await window.ankita.invoke<PluginsCatalogPage>('pluginsCatalog', { query: query.trim() });
        if (id === requestId.current) { setCards(result.cards); setCursor(result.nextCursor); setError(''); }
      } catch (cause) { if (id === requestId.current) setError(message(cause)); }
      finally { if (id === requestId.current) setCatalogBusy(false); }
    }, query ? 250 : 0);
    return () => { window.clearTimeout(timer); requestId.current++; };
  }, [overview?.mode, query]);

  useEffect(() => {
    if (!awaiting) return;
    let attempts = 0, inFlight = false;
    const timer = window.setInterval(async () => {
      if (inFlight) return;
      if (++attempts > 15) { setAwaiting(null); setNotice('Still waiting for authorization. Use Refresh after you finish in the browser.'); return; }
      inFlight = true;
      const result = await loadOverview();
      if (result?.services[awaiting]?.connected) { setAwaiting(null); setNotice(`${title(awaiting)} is connected.`); void loadOverview(true); }
      inFlight = false;
    }, 8000);
    return () => window.clearInterval(timer);
  }, [awaiting, loadOverview]);

  useEffect(() => {
    if (!selected && !confirm) return;
    const root = document.querySelector<HTMLElement>(confirm ? '.plugins-confirm' : '.plugins-drawer');
    const focusable = [...(root?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)') || [])];
    focusable[0]?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setConfirm(null); if (!confirm) setSelected(null); }
      if (event.key !== 'Tab' || !focusable.length) return;
      if (event.shiftKey && document.activeElement === focusable[0]) { event.preventDefault(); focusable.at(-1)?.focus(); }
      else if (!event.shiftKey && document.activeElement === focusable.at(-1)) { event.preventDefault(); focusable[0]?.focus(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selected, confirm]);

  const services = overview?.services || {};
  const installed = useMemo(() => Object.entries(services).filter(([, item]) => item.connected || item.pending || item.accounts.length).sort(([a], [b]) => a.localeCompare(b)), [services]);
  const installedCount = installed.filter(([, item]) => item.connected).length;
  const lookup = (slug: string) => cards.find(card => card.slug === slug) || { slug, label: title(slug), blurb: '', noAuth: false };

  const loadMore = async () => {
    if (visible < cards.length) { setVisible(current => current + PAGE_SIZE); return; }
    if (!cursor || catalogBusy) return;
    const id = requestId.current;
    setCatalogBusy(true);
    try {
      const result = await window.ankita.invoke<PluginsCatalogPage>('pluginsCatalog', { query: query.trim(), cursor });
      if (id !== requestId.current) return;
      setCards(current => [...current, ...result.cards.filter(card => !current.some(old => old.slug === card.slug))]);
      setCursor(result.nextCursor); setVisible(current => current + PAGE_SIZE);
    } catch (cause) { setError(message(cause)); }
    finally { if (id === requestId.current) setCatalogBusy(false); }
  };

  const connect = async (slug: string) => {
    if (acting) return;
    setActing(slug); setError(''); setNotice('');
    try {
      const result = await window.ankita.invoke<{ url: string }>('pluginsConnect', { slug, ...(alias.trim() ? { alias: alias.trim() } : {}) });
      await window.ankita.openExternal(result.url);
      setAlias(''); setAwaiting(slug);
      setNotice(`Finish connecting ${lookup(slug).label} in your browser. This page will update when it is ready.`);
    } catch (cause) { setError(message(cause)); }
    finally { setActing(null); }
  };

  const disconnect = async () => {
    if (!confirm || acting) return;
    const { slug, accountId } = confirm;
    setActing(slug); setError(''); setConfirm(null);
    try {
      await window.ankita.invoke(accountId ? 'pluginsDisconnectAccount' : 'pluginsDisconnectService', { slug, accountId });
      setNotice(accountId ? 'Account disconnected.' : `${lookup(slug).label} disconnected.`);
      await loadOverview(true);
    } catch (cause) { setError(message(cause)); }
    finally { setActing(null); }
  };

  const renderRow = (card: PluginCard) => {
    const service = services[card.slug];
    const connected = Boolean(service?.connected);
    const pending = Boolean(service?.pending || awaiting === card.slug);
    return <div className="plugin-row" key={card.slug}>
      <button type="button" className="plugin-row-main" onClick={() => { setSelected(card.slug); setAlias(''); }}>
        <PluginLogo slug={card.slug} label={card.label} />
        <span className="plugin-row-copy"><strong>{card.label}</strong><small>{card.blurb || 'Connect and use this app with Ankita'}</small></span>
      </button>
      {connected && <span className="plugin-row-state">Connected</span>}
      {pending && !connected && <span className="plugin-row-state pending">Connecting</span>}
      <button type="button" className="plugin-row-action" onClick={() => connected || pending || card.noAuth ? setSelected(card.slug) : void connect(card.slug)} disabled={acting === card.slug} aria-label={connected ? `Manage ${card.label}` : pending ? `View ${card.label} connection` : card.noAuth ? `View ${card.label}` : `Connect ${card.label}`} title={connected ? 'Manage' : pending ? 'Connecting' : card.noAuth ? 'View' : 'Connect'}><Icon name={connected || pending || card.noAuth ? 'arrowRight' : 'plus'} size={17} /></button>
    </div>;
  };

  const shown = cards.slice(0, visible);
  const popular = !query ? [...shown].sort((a, b) => {
    const ai = featured.indexOf(a.slug), bi = featured.indexOf(b.slug);
    return (ai < 0 ? 100 : ai) - (bi < 0 ? 100 : bi);
  }).slice(0, 8) : [];
  const popularSlugs = new Set(popular.map(card => card.slug));
  const remainder = shown.filter(card => !popularSlugs.has(card.slug));
  const detail = selected ? lookup(selected) : null;
  const service: PluginService | undefined = selected ? services[selected] : undefined;

  return <main className="plugins-pane">
    <header className="plugins-header drag-region"><div className="plugins-header-left no-drag">
      {!sidebarOpen && <>{chrome === 'custom' && <WindowControls />}<button type="button" className="icon-button" onClick={onToggleSidebar} aria-label="Show sidebar" aria-expanded={false}><Icon name="panelLeft" size={18} /></button></>}
      <span className="plugins-header-icon"><Icon name="plug" size={17} /></span><strong>Plugins</strong>
    </div><div className="plugins-header-actions no-drag"><button type="button" className="icon-button" onClick={() => void loadOverview(true)} disabled={refreshing} aria-label="Refresh connected apps" title="Refresh connected apps"><Icon name="refresh" size={17} /></button><button type="button" className="plugins-header-settings" onClick={onOpenSettings}><Icon name="settings" size={15} /> Settings</button></div></header>

    <div className="plugins-scroll"><div className="plugins-content">
      <nav className="plugins-sections" aria-label="Plugin sections"><button type="button" className={section === 'apps' ? 'active' : ''} aria-current={section === 'apps' ? 'page' : undefined} onClick={() => setSection('apps')}><Icon name="plug" size={16} /> Apps</button><button type="button" className={section === 'skills' ? 'active' : ''} aria-current={section === 'skills' ? 'page' : undefined} onClick={() => { setSelected(null); setSection('skills'); }}><Icon name="file" size={16} /> Skills</button></nav>
      {section === 'skills' ? <SkillsSection /> : <>
      <div className="plugins-intro"><div className="plugins-eyebrow"><span /> CONNECTED WORKSPACE</div><h1>Give Ankita more<br /><em>to work with.</em></h1><p>Bring the apps you already use into the conversation. Connect once, then manage every account from here.</p></div>
      {error && <div className="plugins-alert" role="alert"><Icon name="alert" size={16} /><span>{error}</span><button type="button" onClick={() => setError('')} aria-label="Dismiss error"><Icon name="close" size={15} /></button></div>}
      {notice && <div className="plugins-notice" role="status"><Icon name="check" size={16} /><span>{notice}</span><button type="button" onClick={() => setNotice('')} aria-label="Dismiss notice"><Icon name="close" size={15} /></button></div>}

      {loading ? <div className="plugins-loading">Loading connected apps…</div> : !overview ? <div className="plugins-setup"><span className="plugins-setup-icon"><Icon name="alert" size={22} /></span><div><h2>Connected apps are unavailable</h2><p>Check the error above, then try again.</p><button type="button" className="settings-secondary" onClick={() => void loadOverview()}>Try again</button></div></div> : overview.mode === 'unavailable' ? <div className="plugins-setup"><span className="plugins-setup-icon"><Icon name="key" size={22} /></span><div><h2>Connect your Composio project</h2><p>Add a project key to browse the app catalog, authorize accounts, and give Ankita access to their tools.</p><button type="button" className="settings-primary" onClick={onOpenSettings}>Set up Composio <Icon name="arrowRight" size={15} /></button></div></div> : <>
        <div className="plugins-toolbar"><div className="plugins-tabs" role="tablist" aria-label="Plugin views"><button type="button" role="tab" aria-selected={tab === 'discover'} className={tab === 'discover' ? 'active' : ''} onClick={() => setTab('discover')}>Discover</button><button type="button" role="tab" aria-selected={tab === 'installed'} className={tab === 'installed' ? 'active' : ''} onClick={() => setTab('installed')}>Installed <span>{installedCount}</span></button></div><span className={`plugins-connection ${overview?.live ? 'live' : ''}`}><i />{overview?.live ? 'Connected' : 'Composio ready'}</span></div>
        {tab === 'discover' ? <>
          <label className="plugins-search"><Icon name="search" size={18} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search apps and tools" aria-label="Search plugins" /><kbd>{navigator.platform.includes('Mac') ? '⌘ K' : 'Ctrl K'}</kbd></label>
          {catalogBusy && !cards.length ? <div className="plugins-loading">Searching apps…</div> : <>
            {popular.length > 0 && <section className="plugins-section"><div className="plugins-section-head"><h2>Popular</h2><span>Start with the essentials</span></div><div className="plugin-grid">{popular.map(renderRow)}</div></section>}
            {remainder.length > 0 && <section className="plugins-section"><div className="plugins-section-head"><h2>{query ? `Results for “${query}”` : 'Explore all'}</h2><span>{query ? `${cards.length} found so far` : 'Browse the catalog'}</span></div><div className="plugin-grid">{remainder.map(renderRow)}</div></section>}
            {!shown.length && !catalogBusy && <div className="plugins-empty"><Icon name="search" size={22} /><h2>No apps found yet</h2><p>{cursor ? 'There are more catalog pages to search.' : query ? 'Try a different name or keyword.' : 'The catalog is empty right now. Try refreshing.'}</p></div>}
            {(visible < cards.length || cursor) && <button type="button" className="plugins-more" onClick={() => void loadMore()} disabled={catalogBusy}>{catalogBusy ? 'Loading…' : query ? 'Search more apps' : 'Show more apps'} <Icon name="chevron" size={15} /></button>}
          </>}
        </> : <section className="plugins-section installed"><div className="plugins-section-head"><h2>Your apps</h2><span>{installedCount} connected</span></div>{installed.length ? <div className="plugin-grid">{installed.map(([slug]) => renderRow(lookup(slug)))}</div> : <div className="plugins-empty"><Icon name="plug" size={23} /><h2>Nothing connected yet</h2><p>Find an app in Discover and connect an account to get started.</p><button type="button" className="settings-secondary" onClick={() => setTab('discover')}>Explore plugins</button></div>}</section>}
      </>}
      </>}
    </div></div>

    {detail && <div className="plugins-drawer-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setSelected(null); }}><section className="plugins-drawer" role="dialog" aria-modal="true" aria-labelledby="plugin-detail-title">
      <div className="plugins-drawer-top"><span>PLUGIN DETAILS</span><button type="button" className="icon-button" onClick={() => setSelected(null)} aria-label="Close plugin details"><Icon name="close" size={17} /></button></div>
      <div className="plugins-drawer-body"><PluginLogo slug={detail.slug} label={detail.label} /><h2 id="plugin-detail-title">{detail.label}</h2><p>{detail.blurb || 'Bring this app into your Ankita workspace.'}</p>
        <div className={`plugins-detail-status ${service?.connected ? 'connected' : ''}`}><i />{service?.connected ? 'Connected' : service?.pending || awaiting === detail.slug ? 'Waiting for authorization' : detail.noAuth ? 'Available without sign-in' : 'Not connected'}</div>
        {service?.accounts.length ? <div className="plugins-accounts"><h3>Connected accounts</h3>{service.accounts.map(account => <div className="plugins-account" key={account.id}><span><strong>{account.alias || account.id}</strong><small>{account.status.toLowerCase()}</small></span><button type="button" onClick={() => setConfirm({ slug: detail.slug, accountId: account.id, name: account.alias || account.id })}>Disconnect</button></div>)}</div> : null}
        {!detail.noAuth && !(service?.connected && !service.accounts.length) && <div className="plugins-connect-form"><h3>{service?.accounts.length ? 'Add another account' : 'Connect an account'}</h3><label htmlFor="plugin-alias">Account label <span>optional</span></label><input id="plugin-alias" value={alias} onChange={event => setAlias(event.target.value)} maxLength={64} placeholder="e.g. Work or Personal" /><button type="button" className="settings-primary" onClick={() => void connect(detail.slug)} disabled={acting === detail.slug}>{acting === detail.slug ? 'Opening…' : 'Connect in browser'} <Icon name="external" size={14} /></button></div>}
        {service?.accounts.length && service.accounts.length > 1 ? <button type="button" className="plugins-disconnect-all" onClick={() => setConfirm({ slug: detail.slug, name: detail.label })}>Disconnect all accounts</button> : null}
        {awaiting === detail.slug && <p className="plugins-awaiting">Waiting for authorization. You can return here after finishing in the browser.</p>}
      </div>
    </section></div>}
    {confirm && <div className="plugins-confirm-backdrop"><div className="plugins-confirm" role="alertdialog" aria-modal="true" aria-labelledby="plugins-confirm-title"><span className="plugins-confirm-icon"><Icon name="alert" size={20} /></span><h2 id="plugins-confirm-title">Disconnect {confirm.name}?</h2><p>Ankita will lose access to this {confirm.accountId ? 'account' : 'app and its accounts'}. You can reconnect it later.</p><div><button type="button" className="settings-secondary" onClick={() => setConfirm(null)}>Cancel</button><button type="button" className="button-danger" onClick={() => void disconnect()}>Disconnect</button></div></div></div>}
  </main>;
}
