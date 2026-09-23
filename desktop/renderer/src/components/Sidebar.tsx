import { useMemo } from 'react';
import type { Teammate } from '../../../shared/wire';
import { relativeTime } from '../lib/relative-time';
import { Icon } from './Icons';
import { WindowControls } from './WindowControls';

export function Sidebar({ teammates, selectedId, search, onSearch, onSelect, onCreate, onOpenSettings, onOpenPlugins, pluginsOpen, provider, model, phase, chrome, unread, toolsCount, width, onResize }: {
  teammates: Teammate[]; selectedId: string | null; search: string; onSearch: (value: string) => void;
  onSelect: (id: string) => void; onCreate: () => void; onOpenSettings: () => void; onOpenPlugins: () => void; pluginsOpen: boolean; provider: string; model: string; phase: string;
  chrome: string; unread: Record<string, boolean>; toolsCount: number; width: number; onResize: (width: number) => void;
}) {
  const shown = useMemo(() => teammates.filter(t => `${t.name} ${t.persona}`.toLowerCase().includes(search.toLowerCase())), [teammates, search]);
  const unreadCount = teammates.filter(t => unread[t.id] && t.id !== selectedId).length;

  const startResize = (event: React.MouseEvent) => {
    event.preventDefault();
    const move = (moveEvent: MouseEvent) => onResize(Math.min(440, Math.max(236, moveEvent.clientX)));
    const stop = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', stop);
      document.body.classList.remove('resizing');
    };
    document.body.classList.add('resizing');
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', stop);
  };

  return <aside className="sidebar" style={{ width, flexBasis: width }}>
    <div className="sidebar-top drag-region">
      {chrome === 'custom' ? <WindowControls /> : <span className="native-chrome-space" />}
      <button className="icon-button add-teammate no-drag" onClick={onCreate} title="New teammate" aria-label="New teammate"><Icon name="plus" size={19} /></button>
    </div>
    <div className="brand no-drag"><div className="brand-mark">a</div><div><strong>ankita</strong><small>Your thinking space</small></div></div>
    <label className="search-box no-drag"><Icon name="search" size={17} /><input placeholder="Find a teammate" value={search} onChange={event => onSearch(event.target.value)} aria-label="Find a teammate" /><kbd>{navigator.platform.includes('Mac') ? '⌘ K' : 'Ctrl K'}</kbd></label>
    <button type="button" className={`sidebar-plugins ${pluginsOpen ? 'active' : ''}`} onClick={onOpenPlugins} aria-current={pluginsOpen ? 'page' : undefined}><Icon name="plug" size={16} /><span>Plugins</span><Icon name="arrowRight" size={14} /></button>
    <div className="sidebar-section-title"><span>Teammates</span><span>{unreadCount ? <em className="unread-pill">{unreadCount} new</em> : teammates.length}</span></div>
    <nav className="teammate-list" aria-label="Teammates">
      {shown.length ? shown.map(teammate => <button key={teammate.id} className={`teammate-row ${!pluginsOpen && selectedId === teammate.id ? 'active' : ''}`} onClick={() => onSelect(teammate.id)}>
        <span className="teammate-avatar" style={{ '--avatar-color': teammate.color } as React.CSSProperties}>{teammate.emoji || teammate.name.slice(0, 1)}</span>
        <span className="teammate-copy">
          <span className="teammate-line"><strong>{teammate.name}</strong><time>{relativeTime(teammate.lastMessageAt)}</time></span>
          <span className="teammate-preview">{teammate.lastMessage || (teammate.persona ? teammate.persona : 'A fresh conversation')}</span>
        </span>
        {unread[teammate.id] && teammate.id !== selectedId ? <span className="unread-dot" aria-label="Unread reply" /> : null}
      </button>) : <div className="sidebar-empty">No teammates match “{search}”.</div>}
    </nav>
    <div className="sidebar-footer">
      <span className={`status-indicator ${phase === 'ready' ? 'live' : ''}`} />
      <div><strong>{phase === 'ready' ? 'Ready when you are' : phase === 'connecting-tools' ? 'Connecting tools' : phase === 'error' ? 'Something went wrong' : 'Starting Ankita'}</strong><small>{provider} · {model || 'Choosing a model'}{toolsCount ? ` · ${toolsCount} tool${toolsCount === 1 ? '' : 's'}` : ''}</small></div>
      <button type="button" className="icon-button sidebar-settings" onClick={onOpenSettings} title="Settings" aria-label="Open settings"><Icon name="settings" size={17} /></button>
    </div>
    <div className="sidebar-resizer" role="separator" aria-label="Resize sidebar" onMouseDown={startResize} />
  </aside>;
}
