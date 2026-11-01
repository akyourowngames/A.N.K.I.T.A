import { useCallback, useEffect, useMemo, useState } from 'react';
import type { DesktopMcpInstallResult, DesktopMcpOverview, DesktopMcpServer, McpCandidate, McpSearchResult } from '../../../shared/wire';
import { Icon } from './Icons';
import { cleanErrorMessage } from '../../../shared/error-notices.mjs';

const QUERY_MAX = 100; // Matches the main-process search limit.
const SEARCH_DEBOUNCE_MS = 350;
const ARG_PLACEHOLDER = 'One argument per line, e.g.\n-y\n@modelcontextprotocol/server-filesystem\nC:/work';

type EnvDraft = Record<string, string>;

function statusOf(server: DesktopMcpServer) {
  if (server.connected) return { label: 'Running', tone: 'live' };
  if (!server.enabled) return { label: 'Disabled', tone: 'off' };
  if (!server.approved) return { label: 'Needs approval', tone: 'pending' };
  return { label: 'Ready', tone: 'ready' };
}

function commandLine(server: { command: string; args: string[] }) {
  return [server.command, ...server.args].filter(Boolean).join(' ');
}

function parseArgs(raw: string) {
  return raw.split('\n').map(line => line.trim()).filter(Boolean);
}

function parseEnvLines(raw: string) {
  const env: EnvDraft = {};
  for (const line of raw.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const at = trimmed.indexOf('=');
    if (at <= 0) throw new Error(`Use KEY=VALUE for each environment line (got "${trimmed}")`);
    env[trimmed.slice(0, at).trim()] = trimmed.slice(at + 1);
  }
  return env;
}

export function McpSection({ toolsRevision }: { toolsRevision: number }) {
  const [servers, setServers] = useState<DesktopMcpServer[] | null>(null);
  const [query, setQuery] = useState('');
  const [candidates, setCandidates] = useState<McpCandidate[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchedFor, setSearchedFor] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [installTarget, setInstallTarget] = useState<McpCandidate | null>(null);
  const [envDraft, setEnvDraft] = useState<EnvDraft>({});
  const [startTarget, setStartTarget] = useState<DesktopMcpServer | null>(null);
  const [removeTarget, setRemoveTarget] = useState<DesktopMcpServer | null>(null);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualName, setManualName] = useState('');
  const [manualCommand, setManualCommand] = useState('');
  const [manualArgs, setManualArgs] = useState('');
  const [manualEnv, setManualEnv] = useState('');

  const load = useCallback(async () => {
    try {
      const result = await window.ankita.invoke<DesktopMcpOverview>('mcpOverview');
      setServers(result.servers);
    } catch (cause) { setError(cleanErrorMessage(cause)); }
  }, []);

  useEffect(() => { void load(); }, [load, toolsRevision]);

  useEffect(() => {
    const wanted = query.trim();
    if (!wanted) { setCandidates(null); setSearchedFor(''); setSearching(false); return; }
    let active = true;
    const timer = window.setTimeout(async () => {
      setSearching(true); setError('');
      try {
        const result = await window.ankita.invoke<McpSearchResult>('mcpSearch', { query: wanted });
        if (active && wanted === query.trim()) { setCandidates(result.candidates); setSearchedFor(wanted); }
      } catch (cause) { if (active) setError(cleanErrorMessage(cause)); }
      finally { if (active) setSearching(false); }
    }, SEARCH_DEBOUNCE_MS);
    return () => { active = false; window.clearTimeout(timer); };
  }, [query]);

  useEffect(() => {
    if (!installTarget && !startTarget && !removeTarget) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setInstallTarget(null); setStartTarget(null); setRemoveTarget(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [installTarget, startTarget, removeTarget]);

  const installed = useMemo(() => servers || [], [servers]);
  const running = installed.filter(server => server.connected).length;
  const needingApproval = installed.filter(server => server.enabled && !server.approved && !server.connected).length;
  const missingRequired = (candidate: McpCandidate) =>
    candidate.env.filter(entry => entry.required && !entry.hasDefault && !envDraft[entry.name]);

  const install = async (candidate: McpCandidate, env: EnvDraft) => {
    if (busy) return;
    setBusy('install'); setError(''); setNotice('');
    try {
      const result = await window.ankita.invoke<DesktopMcpInstallResult>('mcpInstallRegistry', {
        registryName: candidate.registryName, version: candidate.version, env,
      });
      setInstallTarget(null); setEnvDraft({});
      setNotice(`${result.record.name} was added. Press Start to run it.`);
      await load();
    } catch (cause) { setError(cleanErrorMessage(cause)); }
    finally { setBusy(null); }
  };

  const chooseInstall = (candidate: McpCandidate) => {
    const defaults: EnvDraft = {};
    for (const entry of candidate.env) if (entry.hasDefault) defaults[entry.name] = '';
    setEnvDraft(defaults);
    if (candidate.env.some(entry => entry.required && !entry.hasDefault)) setInstallTarget(candidate);
    else void install(candidate, defaults);
  };

  const addManual = async () => {
    if (busy) return;
    setBusy('manual'); setError(''); setNotice('');
    try {
      const result = await window.ankita.invoke<DesktopMcpInstallResult>('mcpInstallManual', {
        name: manualName.trim(), command: manualCommand.trim(), args: parseArgs(manualArgs), env: parseEnvLines(manualEnv),
      });
      setNotice(`${result.record.name} was added. Press Start to run it.`);
      setManualName(''); setManualCommand(''); setManualArgs(''); setManualEnv(''); setManualOpen(false);
      await load();
    } catch (cause) { setError(cleanErrorMessage(cause)); }
    finally { setBusy(null); }
  };

  const toggle = async (server: DesktopMcpServer) => {
    if (busy) return;
    setBusy(server.id); setError('');
    try { setServers((await window.ankita.invoke<DesktopMcpOverview>('mcpSetEnabled', { id: server.id, enabled: !server.enabled })).servers); }
    catch (cause) { setError(cleanErrorMessage(cause)); }
    finally { setBusy(null); }
  };

  const start = async (server: DesktopMcpServer) => {
    if (busy) return;
    setBusy(server.id); setError(''); setStartTarget(null); setNotice('');
    try {
      setServers((await window.ankita.invoke<DesktopMcpOverview>('mcpStart', { id: server.id })).servers);
      setNotice(`${server.name} is running. Its tools are available in chat.`);
    } catch (cause) { setError(cleanErrorMessage(cause)); await load(); }
    finally { setBusy(null); }
  };

  const stop = async (server: DesktopMcpServer) => {
    if (busy) return;
    setBusy(server.id); setError('');
    try { setServers((await window.ankita.invoke<DesktopMcpOverview>('mcpStop', { id: server.id })).servers); }
    catch (cause) { setError(cleanErrorMessage(cause)); }
    finally { setBusy(null); }
  };

  const remove = async (server: DesktopMcpServer) => {
    if (busy) return;
    setBusy(server.id); setError(''); setRemoveTarget(null);
    try {
      setServers((await window.ankita.invoke<DesktopMcpOverview>('mcpRemove', { id: server.id })).servers);
      setNotice(`${server.name} was removed.`);
    } catch (cause) { setError(cleanErrorMessage(cause)); }
    finally { setBusy(null); }
  };

  const refresh = async () => {
    if (busy) return;
    setBusy('refresh'); setError('');
    try { setServers((await window.ankita.invoke<DesktopMcpOverview>('mcpRefresh')).servers); await load(); }
    catch (cause) { setError(cleanErrorMessage(cause)); }
    finally { setBusy(null); }
  };

  const installable = candidates?.filter(candidate => candidate.usable) || [];
  const remoteOnly = candidates?.filter(candidate => !candidate.usable) || [];

  return <>
    <div className="plugins-intro mcp-intro">
      <div className="plugins-eyebrow"><span /> EXTERNAL TOOLS</div>
      <h1>Give Ankita<br /><em>more tools.</em></h1>
      <p>MCP servers plug outside apps into your chats. Find one in the official registry or add a command yourself. Nothing runs until you approve exactly what will start.</p>
    </div>

    {error && <div className="plugins-alert" role="alert"><Icon name="alert" size={16} /><span>{error}</span><button type="button" onClick={() => setError('')} aria-label="Dismiss error"><Icon name="close" size={15} /></button></div>}
    {notice && <div className="plugins-notice" role="status"><Icon name="check" size={16} /><span>{notice}</span><button type="button" onClick={() => setNotice('')} aria-label="Dismiss notice"><Icon name="close" size={15} /></button></div>}

    <div className="mcp-stats" role="list" aria-label="MCP status">
      <div className="mcp-stat" role="listitem"><span className="mcp-stat-icon"><Icon name="server" size={16} /></span><div><strong>{installed.length}</strong><small>configured</small></div></div>
      <div className={`mcp-stat ${running ? 'live' : ''}`} role="listitem"><span className="mcp-stat-icon"><Icon name="power" size={16} /></span><div><strong>{running}</strong><small>running</small></div></div>
      <div className={`mcp-stat ${needingApproval ? 'pending' : ''}`} role="listitem"><span className="mcp-stat-icon"><Icon name="shield" size={16} /></span><div><strong>{needingApproval}</strong><small>awaiting approval</small></div></div>
      <button type="button" className="mcp-stat-action" onClick={() => void refresh()} disabled={busy !== null} title="Reconnect every approved, enabled server"><Icon name="refresh" size={14} /> Reconnect all</button>
    </div>

    <section className="plugins-section mcp-section">
      <div className="plugins-section-head"><h2>Your servers</h2><span>{installed.length ? `${running} of ${installed.length} running` : 'Nothing configured yet'}</span></div>
      {servers === null ? <div className="plugins-loading">Loading MCP servers…</div> : installed.length === 0
        ? <div className="plugins-empty"><Icon name="server" size={22} /><h2>No MCP servers yet</h2><p>Search the registry below, or add one with a command.</p></div>
        : <div className="mcp-grid">{installed.map(server => {
          const status = statusOf(server);
          return <article className={`mcp-card ${server.connected ? 'running' : ''}`} key={server.id}>
            <header>
              <span className="mcp-card-mark"><Icon name="server" size={18} /></span>
              <div className="mcp-card-title"><strong>{server.name}</strong><small>{server.source || `local · ${server.args.length} arg${server.args.length === 1 ? '' : 's'}`}</small></div>
              <span className={`mcp-status ${status.tone}`}><i />{status.label}</span>
            </header>
            <pre className="mcp-card-command" title={commandLine(server)}>{commandLine(server)}</pre>
            {server.tools.length > 0 && <p className="mcp-card-tools">{server.tools.length} tool{server.tools.length === 1 ? '' : 's'} available</p>}
            {server.lastError && <p className="mcp-card-error"><Icon name="alert" size={13} />{server.lastError}</p>}
            <footer>
              {server.connected
                ? <button type="button" className="mcp-btn" onClick={() => void stop(server)} disabled={busy !== null}><Icon name="stopSquare" size={13} /> Stop</button>
                : <button type="button" className="mcp-btn primary" onClick={() => setStartTarget(server)} disabled={busy !== null || !server.enabled}><Icon name="play" size={13} /> Start</button>}
              <label className="mcp-switch" title={server.enabled ? 'Disable' : 'Enable'}>
                <input type="checkbox" checked={server.enabled} onChange={() => void toggle(server)} disabled={busy !== null} aria-label={`${server.enabled ? 'Disable' : 'Enable'} ${server.name}`} />
                <span />
              </label>
              <button type="button" className="mcp-icon-btn" onClick={() => setRemoveTarget(server)} aria-label={`Remove ${server.name}`} title="Remove"><Icon name="trash" size={15} /></button>
            </footer>
          </article>;
        })}</div>}
    </section>

    <section className="plugins-section mcp-section">
      <div className="plugins-section-head"><h2>Discover servers</h2><span>Official MCP registry</span></div>
      <label className="plugins-search mcp-search"><Icon name="search" size={18} /><input value={query} onChange={event => setQuery(event.target.value)} maxLength={QUERY_MAX} placeholder="Search playwright, postgres, figma, filesystem…" aria-label="Search MCP servers" />{query && <button type="button" className="mcp-search-clear" onClick={() => setQuery('')} aria-label="Clear search"><Icon name="close" size={13} /></button>}</label>

      {searching && <div className="mcp-search-state"><span className="mcp-spinner" />Searching the registry…</div>}
      {!searching && candidates && !candidates.length && <div className="plugins-empty"><Icon name="search" size={22} /><h2>Nothing found</h2><p>No registry server matches “{searchedFor}”. Try a broader word.</p></div>}

      {!searching && installable.length > 0 && <div className="mcp-grid">
        {installable.map(candidate => <article className="mcp-card candidate" key={`${candidate.registryName}@${candidate.version}`}>
          <header>
            <span className="mcp-card-mark"><Icon name="cube" size={18} /></span>
            <div className="mcp-card-title"><strong>{candidate.title || candidate.registryName}</strong><small>{candidate.registryName}</small></div>
            <span className="mcp-version">v{candidate.version}</span>
          </header>
          <p className="mcp-card-blurb">{candidate.description}</p>
          <pre className="mcp-card-command" title={commandLine(candidate)}>{commandLine(candidate)}</pre>
          {candidate.env.filter(entry => entry.required).length > 0 && <p className="mcp-card-tools">Needs {candidate.env.filter(entry => entry.required).map(entry => entry.name).join(', ')}</p>}
          <footer>
            <button type="button" className="mcp-btn primary" onClick={() => chooseInstall(candidate)} disabled={busy !== null} aria-label={`Add ${candidate.title || candidate.registryName}`}><Icon name="plus" size={13} /> Add</button>
          </footer>
        </article>)}
      </div>}

      {!searching && remoteOnly.length > 0 && <details className="mcp-remote">
        <summary><Icon name="globe" size={14} /> {remoteOnly.length} remote-only server{remoteOnly.length === 1 ? '' : 's'} Ankita cannot launch</summary>
        <ul>{remoteOnly.map(candidate => <li key={`${candidate.registryName}@${candidate.version}`}><strong>{candidate.title || candidate.registryName}</strong><small>{candidate.reason}</small></li>)}</ul>
      </details>}

      {!query.trim() && <button type="button" className={`mcp-manual-toggle ${manualOpen ? 'open' : ''}`} onClick={() => setManualOpen(open => !open)}><Icon name="terminal" size={14} /> {manualOpen ? 'Hide manual setup' : 'Add a server manually'}<Icon name="chevron" size={14} /></button>}
      {manualOpen && <div className="mcp-manual">
        <div className="mcp-manual-grid">
          <label htmlFor="mcp-name"><span>Name <em>optional</em></span><input id="mcp-name" value={manualName} onChange={event => setManualName(event.target.value)} maxLength={60} placeholder="files" /></label>
          <label htmlFor="mcp-command"><span>Command</span><input id="mcp-command" value={manualCommand} onChange={event => setManualCommand(event.target.value)} maxLength={200} placeholder="npx" /></label>
          <label className="wide" htmlFor="mcp-args"><span>Arguments <em>one per line</em></span><textarea id="mcp-args" value={manualArgs} onChange={event => setManualArgs(event.target.value)} rows={3} placeholder={ARG_PLACEHOLDER} /></label>
          <label className="wide" htmlFor="mcp-env"><span>Environment <em>KEY=VALUE, one per line</em></span><textarea id="mcp-env" value={manualEnv} onChange={event => setManualEnv(event.target.value)} rows={2} placeholder="API_KEY=…" /></label>
        </div>
        <div className="mcp-manual-actions">
          <button type="button" className="settings-secondary" onClick={() => setManualOpen(false)}>Cancel</button>
          <button type="button" className="settings-primary" onClick={() => void addManual()} disabled={busy !== null || !manualCommand.trim()}>{busy === 'manual' ? 'Adding…' : 'Add server'} <Icon name="plus" size={14} /></button>
        </div>
      </div>}
    </section>

    {installTarget && <div className="plugins-drawer-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setInstallTarget(null); }}><section className="plugins-drawer" role="dialog" aria-modal="true" aria-labelledby="mcp-install-title">
      <div className="plugins-drawer-top"><span>ADD SERVER</span><button type="button" className="icon-button" onClick={() => setInstallTarget(null)} aria-label="Close"><Icon name="close" size={17} /></button></div>
      <div className="plugins-drawer-body">
        <span className="mcp-drawer-mark"><Icon name="cube" size={26} /></span>
        <h2 id="mcp-install-title">{installTarget.title || installTarget.registryName}</h2>
        <p>{installTarget.description}</p>
        <div className="mcp-command"><h3>Exact command</h3><pre>{commandLine(installTarget)}</pre></div>
        <div className="plugins-connect-form">
          {installTarget.env.map(entry => <div key={entry.name} className="mcp-env-field">
            <label htmlFor={`mcp-env-${entry.name}`}>{entry.name}{entry.required ? '' : <span> optional</span>}</label>
            {entry.description && <small>{entry.description}</small>}
            <input id={`mcp-env-${entry.name}`} type={entry.secret ? 'password' : 'text'} value={envDraft[entry.name] ?? ''} onChange={event => setEnvDraft(draft => ({ ...draft, [entry.name]: event.target.value }))} autoComplete="off" spellCheck={false} />
          </div>)}
          <button type="button" className="settings-primary" onClick={() => void install(installTarget, envDraft)} disabled={busy !== null || missingRequired(installTarget).length > 0}>{busy === 'install' ? 'Adding…' : 'Add server'} <Icon name="plus" size={14} /></button>
          <p className="mcp-help">Adding only records the command. Starting it asks you to confirm exactly what will run.</p>
        </div>
      </div>
    </section></div>}

    {startTarget && <div className="plugins-confirm-backdrop"><div className="plugins-confirm mcp-confirm" role="alertdialog" aria-modal="true" aria-labelledby="mcp-start-title"><span className="plugins-confirm-icon mcp-confirm-icon"><Icon name="shield" size={20} /></span><h2 id="mcp-start-title">Start {startTarget.name}?</h2><p>This runs third-party code on your machine and makes its tools callable. Approval is remembered for this exact command.</p><pre className="mcp-command-preview">{commandLine(startTarget)}</pre><div><button type="button" className="settings-secondary" onClick={() => setStartTarget(null)}>Cancel</button><button type="button" className="settings-primary" onClick={() => void start(startTarget)} disabled={busy !== null}>{busy === startTarget.id ? 'Starting…' : 'Start server'}</button></div></div></div>}

    {removeTarget && <div className="plugins-confirm-backdrop"><div className="plugins-confirm mcp-confirm" role="alertdialog" aria-modal="true" aria-labelledby="mcp-remove-title"><span className="plugins-confirm-icon"><Icon name="alert" size={20} /></span><h2 id="mcp-remove-title">Remove {removeTarget.name}?</h2><p>Its tools will no longer be offered. You can add it again later.</p><div><button type="button" className="settings-secondary" onClick={() => setRemoveTarget(null)}>Cancel</button><button type="button" className="button-danger" onClick={() => void remove(removeTarget)} disabled={busy !== null}>Remove</button></div></div></div>}
  </>;
}
