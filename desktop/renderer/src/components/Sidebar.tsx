import { useMemo } from 'react';
import type { Teammate } from '../../../shared/wire';
import { relativeTime } from '../lib/relative-time';
import { Icon } from './Icons';
import { WindowControls } from './WindowControls';
import { TeammateAvatar } from './TeammateAvatar';
import { sidebarWidth } from '../../../shared/desktop-layout.mjs';

export function Sidebar({ teammates, selectedId, search, onSearch, onSelect, onCreate, onOpenSettings, onOpenPlugins, onOpenProjects, onOpenChat, pluginsOpen, projectsOpen, provider, model, phase, chrome, unread, toolsCount, width, collapsed, onCollapse, onResize }: {
  teammates: Teammate[]; selectedId: string | null; search: string; onSearch: (value: string) => void;
  onSelect: (id: string) => void; onCreate: () => void; onOpenSettings: () => void; onOpenPlugins: () => void; onOpenProjects: () => void; onOpenChat: () => void; pluginsOpen: boolean; projectsOpen: boolean; provider: string; model: string; phase: string;
  chrome: string; unread: Record<string, boolean>; toolsCount: number; width: number; collapsed: boolean; onCollapse: () => void; onResize: (width: number) => void;
}) {
  const shown = useMemo(() => teammates.filter(t => `${t.name} ${t.persona}`.toLowerCase().includes(search.toLowerCase())), [teammates, search]);
  const unreadCount = teammates.filter(t => unread[t.id] && t.id !== selectedId).length;

  const startResize = (event: React.MouseEvent) => {
    event.preventDefault();
    const move = (moveEvent: MouseEvent) => onResize(sidebarWidth(moveEvent.clientX));
    const stop = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', stop);
      document.body.classList.remove('resizing');
    };
    document.body.classList.add('resizing');
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', stop);
  };

  return <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`} style={{ width: collapsed ? 0 : width, flexBasis: collapsed ? 0 : width, ['--sidebar-expanded-width' as string]: `${width}px` }} aria-hidden={collapsed} inert={collapsed}>
    <div className="sidebar-content">
    <div className="sidebar-top drag-region">
      {chrome === 'custom' ? <WindowControls /> : <span className="native-chrome-space" />}
      <span className="desktop-wordmark">Ankita</span>
      <div className="sidebar-top-actions no-drag"><button className="icon-button" onClick={onCollapse} title="Collapse sidebar (Ctrl+B)" aria-label="Collapse sidebar"><Icon name="panelLeft" size={17} /></button></div>
    </div>
    <div className="sidebar-workspace">
    <nav className="workspace-rail no-drag" aria-label="Workspace navigation">
      <TeammateAvatar className="rail-mascot" />
      <button type="button" className={`rail-button ${!pluginsOpen && !projectsOpen ? 'active' : ''}`} onClick={onOpenChat} aria-label="Conversations" aria-current={!pluginsOpen && !projectsOpen ? 'page' : undefined} title="Conversations"><Icon name="chat" size={20} /><span>Chat</span>{unreadCount > 0 && <i className="rail-unread" />}</button>
      <button type="button" className={`rail-button ${projectsOpen ? 'active' : ''}`} onClick={onOpenProjects} aria-label="Projects" aria-current={projectsOpen ? 'page' : undefined} title="Projects"><Icon name="folder" size={20} /><span>Projects</span></button>
      <button type="button" className={`rail-button ${pluginsOpen ? 'active' : ''}`} onClick={onOpenPlugins} aria-label="Plugins" aria-current={pluginsOpen ? 'page' : undefined} title="Apps and skills"><Icon name="plug" size={20} /><span>Plugins</span></button>
      <button type="button" className="rail-button rail-create" onClick={onCreate} aria-label="New teammate" title="New teammate"><Icon name="plus" size={20} /><span>New</span></button>
      <div className="rail-teammates" role="group" aria-label="Switch teammate">{teammates.map(teammate => <button type="button" key={teammate.id} aria-label={teammate.name} title={teammate.name} aria-pressed={!pluginsOpen && !projectsOpen && selectedId === teammate.id} onClick={() => onSelect(teammate.id)}><TeammateAvatar id={teammate.id} color={teammate.color} />{unread[teammate.id] && teammate.id !== selectedId && <i className="rail-unread" />}</button>)}</div>
      <button type="button" className="rail-button rail-settings" onClick={onOpenSettings} aria-label="Open settings" title="Settings"><Icon name="settings" size={20} /><span>Settings</span></button>
    </nav>
    <div className="sidebar-roster">
    <div className="roster-heading"><div><strong>Your team</strong><span>{teammates.length} teammates</span></div><button className="icon-button add-teammate" onClick={onCreate} title="New teammate" aria-label="New teammate"><Icon name="plus" size={18} /></button></div>
    <label className="search-box no-drag"><Icon name="search" size={17} /><input placeholder="Find a teammate" value={search} onChange={event => onSearch(event.target.value)} aria-label="Find a teammate" /></label>
    <div className="sidebar-section-title"><span>Conversations</span>{unreadCount > 0 && <em className="unread-pill">{unreadCount} new</em>}</div>
    <nav className="teammate-list" aria-label="Teammates">
      {shown.length ? shown.map(teammate => <button key={teammate.id} aria-label={teammate.name} title={teammate.name} aria-current={!pluginsOpen && !projectsOpen && selectedId === teammate.id ? 'page' : undefined} className={`teammate-row ${!pluginsOpen && !projectsOpen && selectedId === teammate.id ? 'active' : ''}`} onClick={() => onSelect(teammate.id)}>
        <TeammateAvatar id={teammate.id} color={teammate.color} />
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
    </div>
    </div></div>
    </div>
    <div className="sidebar-resizer" role="separator" aria-label="Resize sidebar" onMouseDown={startResize} />
  </aside>;
}
