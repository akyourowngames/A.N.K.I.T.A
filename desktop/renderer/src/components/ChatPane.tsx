import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ChatMessage, Model, Project, Teammate } from '../../../shared/wire';
import type { Usage } from '../state/store';
import { Composer } from './Composer';
import { Icon } from './Icons';
import { Message } from './Message';
import { WindowControls } from './WindowControls';
import { formatTokens } from '../lib/format';

export function ChatPane({ teammate, messages, running, models, projects, defaultModel, usage, chrome, sidebarOpen, reviewOpen, onToggleSidebar, onToggleReview, onProject, onOpenProjects, onSend, onStop, onModel, onEdit, onClear, onDelete }: {
  teammate: Teammate | null; messages: ChatMessage[]; running: boolean; models: Model[]; defaultModel: string;
  projects: Project[]; usage?: Usage; chrome: string; sidebarOpen: boolean; reviewOpen: boolean; onToggleSidebar: () => void; onToggleReview: () => void; onProject: (id: string | null) => void; onOpenProjects: () => void;
  onSend: (text: string, attachments?: { name: string; data: string; kind?: 'document'; images?: string[] }[]) => void; onStop: () => void; onModel: (id: string) => void;
  onEdit: () => void; onClear: () => void; onDelete: () => void;
}) {
  const [menu, setMenu] = useState(false);
  const [projectMenu, setProjectMenu] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const scroll = useRef<HTMLDivElement>(null);
  // A ref, not state: the follow decision must be read synchronously by the
  // layout effect, or a streaming delta arriving right after the user scrolls
  // up still sees the previous "at bottom" value and yanks the view back down.
  const stick = useRef(true);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    const element = scroll.current;
    if (!element) return;
    element.scrollTo({ top: element.scrollHeight, behavior });
    stick.current = true;
    setAtBottom(true);
  }, []);

  // Follow only while parked at the bottom; reading history is never interrupted.
  useLayoutEffect(() => {
    if (!stick.current) return;
    const element = scroll.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [messages, running]);

  useLayoutEffect(() => { setMenu(false); setProjectMenu(false); stick.current = true; setAtBottom(true); const element = scroll.current; if (element) element.scrollTop = element.scrollHeight; }, [teammate?.id]);

  const onScroll = () => {
    const element = scroll.current;
    if (!element) return;
    const near = element.scrollHeight - element.scrollTop - element.clientHeight < 90;
    stick.current = near;
    setAtBottom(near);
  };
  const jump = () => scrollToBottom('smooth');

  if (!teammate) return <main className="chat-pane">
    {!sidebarOpen && <div className="chat-header drag-region standalone"><div className="no-drag header-left">{chrome === 'custom' && <WindowControls />}<button className="icon-button" onClick={onToggleSidebar} aria-label="Show sidebar" title="Show sidebar (Ctrl+B)" aria-expanded={false}><Icon name="panelLeft" size={18} /></button></div></div>}
    <div className="blank-workspace"><div className="empty-monogram">a.</div><h1>Your workspace is ready.</h1><p>Create a teammate to begin.</p></div>
  </main>;

  const lastAssistant = [...messages].reverse().find(message => message.role === 'assistant')?.id;
  const showThinking = running && (!messages.length || messages.at(-1)?.role !== 'assistant');
  const tokens = usage ? usage.prompt_tokens + usage.completion_tokens : 0;
  const assignedProject = projects.find(project => project.id === teammate.projectId);

  return <main className="chat-pane">
    <header className="chat-header drag-region">
      <div className="header-left no-drag">
        {!sidebarOpen && <>{chrome === 'custom' && <WindowControls />}<button className="icon-button header-sidebar-toggle" onClick={onToggleSidebar} aria-label="Show sidebar" title="Show sidebar (Ctrl+B)" aria-expanded={false}><Icon name="panelLeft" size={18} /></button></>}
        <div className="header-identity"><span className="header-avatar" style={{ '--avatar-color': teammate.color } as React.CSSProperties}>{teammate.emoji || '✦'}</span><div><h2>{teammate.name}</h2><span>{teammate.persona || 'A conversation with room to think'}</span></div></div>
      </div>
      <div className="header-actions no-drag">
        <div className="project-picker"><button className="project-picker-button" onClick={() => setProjectMenu(!projectMenu)} aria-expanded={projectMenu} title="Choose this teammate's project"><Icon name="folder" size={15} /><span>{assignedProject?.name || 'No project'}</span><Icon name="chevron" size={13} /></button>{projectMenu && <div className="project-picker-menu"><span>Work in</span><button className={!teammate.projectId ? 'active' : ''} disabled={running} onClick={() => { onProject(null); setProjectMenu(false); }}>No project</button>{projects.filter(project => !project.archived).map(project => <button key={project.id} className={teammate.projectId === project.id ? 'active' : ''} disabled={running} onClick={() => { onProject(project.id); setProjectMenu(false); }}><strong>{project.name}</strong><small>{project.path || project.summary || 'Project context'}</small></button>)}<button className="project-picker-manage" onClick={() => { setProjectMenu(false); onOpenProjects(); }}>Manage projects <Icon name="arrowRight" size={14} /></button></div>}</div>
        {tokens > 0 && <span className="usage-chip" title="Tokens used in this conversation">{formatTokens(tokens)} tokens{usage && usage.estimated_cost > 0 ? ` · $${usage.estimated_cost.toFixed(4)}` : ''}</span>}
        <button className={`icon-button review-toggle ${reviewOpen ? 'active' : ''}`} onClick={onToggleReview} aria-label="Review changes, artifacts and runs" aria-pressed={reviewOpen} title="Work review"><Icon name="code" size={18} /></button>
        <div className="menu-wrap"><button className="icon-button header-more" aria-label="Conversation options" aria-expanded={menu} onClick={() => setMenu(!menu)}><Icon name="more" size={19} /></button>{menu && <div className="header-menu" role="menu"><button onClick={() => { setMenu(false); onEdit(); }}><Icon name="edit" size={16} /> Edit teammate</button><button onClick={() => { setMenu(false); onClear(); }}><Icon name="panel" size={16} /> Clear conversation</button><span className="menu-divider" /><button className="danger" onClick={() => { setMenu(false); onDelete(); }}><Icon name="trash" size={16} /> Delete teammate</button></div>}</div>
      </div>
    </header>
    <div className="chat-scroll" ref={scroll} onScroll={onScroll} aria-label={`${teammate.name} conversation`}><div className="transcript">
       {!messages.length && !running ? <div className="welcome"><div className="welcome-emblem"><span>{teammate.emoji || '✦'}</span></div><h1>Good things start<br />with a conversation.</h1><p>{teammate.name} is here to help you think, make, and move forward. What’s on your mind?</p><div className="welcome-rule" /><div className="welcome-prompts"><span>Try asking</span><button onClick={() => onSend('Help me make a clear plan for what I’m working on.')}>Make a plan <span>↗</span></button><button onClick={() => onSend('Review my current project and suggest the next step.')}>Find the next step <span>↗</span></button></div></div> : messages.map(message => <Message key={message.id} message={message} teammate={teammate} threadId={teammate.id} streaming={running && message.id === lastAssistant && messages.at(-1)?.id === message.id} />)}
      {showThinking && <div className="thinking-row"><span className="message-avatar" style={{ '--avatar-color': teammate.color } as React.CSSProperties}>{teammate.emoji || '✦'}</span><span className="thinking-dots"><i /><i /><i /></span><span>{teammate.name} is thinking</span></div>}
      <div />
    </div></div>
    {!atBottom && <button className="jump-to-bottom" onClick={jump} aria-label="Jump to latest"><Icon name="chevron" size={17} /><span>Latest</span></button>}
    <Composer threadId={teammate.id} name={teammate.name} messages={messages} running={running} models={models} model={teammate.model || defaultModel} onModel={onModel} onSend={onSend} onStop={onStop} />
  </main>;
}
