import { useEffect, useRef, useState } from 'react';
import type { BrowserSessionView } from '../../../shared/wire';
import { Icon } from './Icons';
import { browserNotice, browserNeedsConnection, browserPageFailed, browserNoticeIsRecoverable } from '../../../../src/integrations/browser-errors.mjs';
import { BROWSER_PHASE_TITLES, BROWSER_PREVIEW_POLL, publicBrowserView } from '../../../shared/browser-progress.mjs';
import { BROWSER_DIALOG_LIMITS } from '../../../../tools/browser/dialogs.mjs';

function domain(url: string) { try { return new URL(url).hostname; } catch { return url || 'New tab'; } }

export function BrowserRunCard({ view, onOpen }: { view: BrowserSessionView; onOpen: () => void }) {
  const active = view.tabs.find(tab => tab.active) || view.tabs[0];
  return <section className="browser-run-card" aria-label="Browser run">
    <div className="browser-run-card-top"><span className="browser-run-globe"><Icon name="browser" size={19} /></span><div><strong>{active ? domain(active.url) : 'Browser'}</strong><small>{view.status === 'takeover' ? 'You are in control' : view.progress?.label || (view.status === 'working' ? view.step : view.status === 'error' ? 'Needs attention' : 'Browser ready')}</small></div><span className={`browser-run-indicator ${view.status} ${view.progress?.recoverable ? browserNoticeIsRecoverable(view.notice) ? 'recovering' : 'needs-attention' : ''}`} /></div>
    <button type="button" className="browser-run-preview" onClick={onOpen} aria-label="Open browser stage">{view.screenshot ? <img src={view.screenshot} alt={`Live view of ${active ? domain(active.url) : 'browser'}`} /> : <span>{view.status === 'error' ? 'Preview unavailable' : 'Loading preview…'}</span>}</button>
    <div className="browser-run-card-bottom"><span>{active ? domain(active.url) : 'Waiting for a page'}</span><button type="button" onClick={onOpen}>Open browser <Icon name="arrowRight" size={14} /></button></div>
  </section>;
}

export function BrowserStage({ view: sharedView, visible, onView, onStop, onOpenSetup, scope }: { view: BrowserSessionView | null; visible: boolean; onView: (view: BrowserSessionView) => void; onStop: () => void; onOpenSetup?: () => void; scope?: string | null }) {
  const [liveView, setLiveView] = useState(sharedView);
  useEffect(() => { setLiveView(previous => sharedView ? { ...sharedView, screenshot: sharedView.screenshot || (sharedView.mode === previous?.mode && !['stopped', 'idle'].includes(sharedView.status) && !browserNeedsConnection(sharedView.notice) && !browserPageFailed(sharedView.notice) ? previous?.screenshot || null : null) } : null); }, [sharedView]);
  useEffect(() => {
    // External mode (raw MCP browser tools) has no session to poll: the panel
    // opens for awareness, not for live pixels.
    if (!visible || !sharedView?.mode || sharedView.mode === 'external') return;
    let active = true, timer: number, publishedAt = 0;
    const poll = async () => {
      const started = performance.now();
      let delay: number = BROWSER_PREVIEW_POLL.active;
      try {
        const next = await window.ankita.invoke<BrowserSessionView>('browserSessionView', { scope });
        if (!active) return;
        setLiveView(previous => ({ ...next, screenshot: next.screenshot || (next.mode === previous?.mode && !['stopped', 'idle'].includes(next.status) && !browserNeedsConnection(next.notice) && !browserPageFailed(next.notice) ? previous?.screenshot || null : null) }));
        // Share an occasional chat thumbnail; live frames only render this pane.
        if (started - publishedAt > BROWSER_PREVIEW_POLL.thumbnail) { onView(publicBrowserView(next)); publishedAt = started; }
        if (next.backgrounded) delay = BROWSER_PREVIEW_POLL.hidden;
        else if (['stopped', 'idle'].includes(next.status) || browserNeedsConnection(next.notice)) delay = BROWSER_PREVIEW_POLL.idle;
      } catch { delay = BROWSER_PREVIEW_POLL.failed; }
      finally { if (active) timer = window.setTimeout(() => void poll(), Math.max(0, (document.hidden ? BROWSER_PREVIEW_POLL.hidden : delay) - (performance.now() - started))); }
    };
    void poll();
    return () => { active = false; window.clearTimeout(timer); };
  }, [visible, sharedView?.mode, onView, scope]);
  useEffect(() => { setLiveView(sharedView); }, [scope]); // A routine's private dialog/input state never follows another selected scope.
  const view = liveView?.mode === sharedView?.mode ? liveView : sharedView;
  const [error, setError] = useState('');
  const [promptText, setPromptText] = useState('');
  const [deciding, setDeciding] = useState(false);
  useEffect(() => { setPromptText(''); }, [view?.dialog?.id]);
  const viewport = useRef<HTMLDivElement>(null);
  const active = view?.tabs.find(tab => tab.active) || view?.tabs[0];
  const takeover = view?.status === 'takeover';
  const notice = error ? browserNotice(error) : view?.notice || (view?.status === 'error' ? browserNotice(view.step) : null);
  const failed = Boolean(notice);
  const recoverable = browserNoticeIsRecoverable(notice);
  const needsAttention = failed && !recoverable;
  const connectionRequired = browserNeedsConnection(notice);
  const status = takeover ? 'Your control' : needsAttention ? 'Needs attention' : recoverable ? notice?.kind === 'reference' ? 'Checking controls' : 'Updating preview' : view?.progress ? BROWSER_PHASE_TITLES[view.progress.phase] : view?.status === 'stopped' ? 'Stopped' : view?.status === 'working' ? 'Working' : active ? 'Ready' : 'Idle';
  const failure = notice?.message || '';
  const invoke = async (action: string, payload?: object) => {
    try { const next = await window.ankita.invoke<BrowserSessionView>(action, { ...payload, scope }); setError(''); if (next && typeof next === 'object') { setLiveView(next); onView(publicBrowserView(next)); } }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  };
  const decideDialog = async (decision: 'accept' | 'dismiss') => {
    const id = view?.dialog?.id;
    if (!id || deciding) return;
    setDeciding(true);
    try {
      if (!takeover) await window.ankita.invoke('browserSessionTakeover', { enabled: true, scope });
      const next = await window.ankita.invoke<BrowserSessionView>('browserSessionDialog', { id, decision, scope, ...(decision === 'accept' && view?.dialog?.type === 'prompt' ? { prompt_text: promptText } : {}) });
      setPromptText(''); setError(''); setLiveView(next); onView(publicBrowserView(next));
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setDeciding(false); }
  };
  const sendInput = (payload: object) => { void window.ankita.invoke('browserSessionInput', { ...payload, scope }).catch(cause => setError(cause instanceof Error ? cause.message : String(cause))); };
  const clickViewport = (event: React.MouseEvent<HTMLImageElement>) => {
    if (!takeover || view?.mode !== 'isolated') return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.round((event.clientX - rect.left) / rect.width * 1280);
    const y = Math.round((event.clientY - rect.top) / rect.height * 800);
    sendInput({ kind: 'click', x, y });
    viewport.current?.focus();
  };
  const keyViewport = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!takeover) return;
    if (event.key === 'Escape') { event.preventDefault(); void invoke('browserSessionTakeover', { enabled: false }); return; }
    if (view?.mode !== 'isolated') return;
    event.preventDefault();
    if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) sendInput({ kind: 'text', text: event.key });
    else sendInput({ kind: 'key', key: `${event.ctrlKey ? 'Control+' : ''}${event.shiftKey ? 'Shift+' : ''}${event.altKey ? 'Alt+' : ''}${event.metaKey ? 'Meta+' : ''}${event.key}` });
  };
  return <aside className={`browser-stage ${visible ? 'is-open' : 'is-closed'}`} aria-label="Live browser" aria-hidden={!visible} inert={!visible}>
    <header className="browser-stage-header"><div className="browser-stage-identity"><Icon name="browser" size={19} /><div><strong>Live browser</strong><span>{view?.mode === 'local' ? 'Chrome' : view?.mode === 'external' ? 'External' : 'Chromium'}</span></div></div><div className="browser-stage-header-actions"><button type="button" className="browser-stage-stop" onClick={onStop}><Icon name="stop" size={11} /> Stop</button><button type="button" className="icon-button" onClick={onStop} aria-label="Close and stop browser"><Icon name="close" size={16} /></button></div></header>
    {Boolean(view?.tabs.length) && <div className="browser-stage-tabs" role="tablist" aria-label="Browser tabs">{view?.tabs.map(tab => <button type="button" role="tab" key={tab.id} aria-selected={tab.active} className={tab.active ? 'active' : ''} onClick={() => void invoke('browserSessionSelectTab', { tab: tab.id })}><Icon name="globe" size={12} /><span>{tab.title || domain(tab.url)}</span></button>)}</div>}
    <div className="browser-stage-address"><Icon name={active?.url.startsWith('https:') ? 'lock' : 'globe'} size={12} /><input readOnly aria-label="Current browser URL" value={active?.url || ''} placeholder="No page open" /><span className={`browser-stage-status ${needsAttention ? 'error' : ''}`}><i />{status}</span></div>
    <div className={`browser-stage-progress ${view?.progress?.phase || 'idle'} ${needsAttention ? 'error' : ''}`} role="status" aria-live="polite" aria-atomic="true"><i aria-hidden="true" /><span>{view?.progress?.label || 'Waiting for a page'}</span>{view?.progress?.total && view.progress.total > 1 ? <small aria-label="Completed browser steps">{view.progress.completed} / {view.progress.total}</small> : null}</div>
    {view?.dialog && <section className="browser-stage-dialog" aria-label="Page dialog"><span className="browser-stage-dialog-source">This website asks</span><p>{view.dialog.message || 'The page needs your decision.'}</p>{view.dialog.type === 'prompt' && <input aria-label="Reply to page prompt" value={promptText} maxLength={BROWSER_DIALOG_LIMITS.prompt} onChange={event => setPromptText(event.target.value)} autoComplete="off" />}<div><button type="button" disabled={deciding || !view.dialog.id} onClick={() => void decideDialog('dismiss')}>Dismiss</button><button type="button" disabled={deciding || !view.dialog.id} onClick={() => void decideDialog('accept')}>{deciding ? 'Handling…' : view.dialog.type === 'alert' ? 'OK' : 'Continue'}</button></div><small>You stay in control until you hand back.</small></section>}
    <div className={`browser-stage-body ${!view?.screenshot ? 'empty' : ''}`}><div className={`browser-stage-viewport ${takeover && view?.mode === 'isolated' ? 'interactive' : ''}`} ref={viewport} tabIndex={takeover ? 0 : -1} onKeyDown={keyViewport} onPaste={event => { if (takeover && view?.mode === 'isolated') { event.preventDefault(); sendInput({ kind: 'text', text: event.clipboardData.getData('text').slice(0, 1000) }); } }} onWheel={event => { if (takeover && view?.mode === 'isolated') sendInput({ kind: 'scroll', deltaY: event.deltaY }); }}>
      {view?.screenshot ? <img src={view.screenshot} alt={`Live browser page at ${active?.url || 'new tab'}`} onClick={clickViewport} draggable={false} /> : <div className="browser-stage-empty"><Icon name={failure ? 'alert' : 'browser'} size={28} /><h2>{connectionRequired ? 'Browser unavailable' : failure ? 'Page needs attention' : view?.mode === 'external' ? 'External browser tool' : active ? 'Loading preview' : 'No page open'}</h2><p>{failure || (view?.mode === 'external' ? 'Driven by an MCP browser server outside the live session. Use the built-in browser tool for a live preview here.' : active ? 'The page preview will appear here.' : 'Ask Ankita to open a website. You can watch it here and take control when needed.')}</p>{connectionRequired && onOpenSetup && <button type="button" className="browser-stage-setup" onClick={onOpenSetup}>Browser settings <Icon name="arrowRight" size={14} /></button>}</div>}
    </div>{view?.screenshot && failure && <div className={`browser-stage-error ${recoverable ? 'is-recovering' : ''}`} role={recoverable ? 'status' : 'alert'}><Icon name={recoverable ? 'browser' : 'alert'} size={14} /><span>{failure}</span></div>}</div>
    <footer className="browser-stage-footer"><div><strong>{takeover ? 'You are in control' : connectionRequired ? 'Connection required' : active ? 'Shared browser' : 'Browser preview'}</strong><span>{takeover ? view?.mode === 'local' ? 'Use Chrome, then hand back.' : 'Click or type in the page. Esc to hand back.' : connectionRequired ? 'Open browser settings to reconnect.' : active ? view?.status === 'working' ? view.step : 'Take control to sign in or finish a step.' : 'The page stays in view while Ankita works.'}</span></div><button type="button" className={takeover ? 'handback' : ''} disabled={!active || connectionRequired} onClick={() => void invoke('browserSessionTakeover', { enabled: !takeover })}><Icon name={takeover ? 'arrowRight' : 'user'} size={14} />{takeover ? 'Hand back' : 'Take control'}</button></footer>
  </aside>;
}
