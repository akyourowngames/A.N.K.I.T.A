import { useEffect, useRef, useState } from 'react';
import type { ChatMessage, Model, Teammate } from '../../../shared/wire';
import type { Usage } from '../state/store';
import { Composer } from './Composer';
import { Icon } from './Icons';
import { Message } from './Message';
import { WindowControls } from './WindowControls';
import { formatTokens } from '../lib/format';

export function ChatPane({ teammate, messages, running, models, defaultModel, usage, chrome, sidebarOpen, onToggleSidebar, onSend, onStop, onModel, onEdit, onClear, onDelete }: {
  teammate: Teammate | null; messages: ChatMessage[]; running: boolean; models: Model[]; defaultModel: string;
  usage?: Usage; chrome: string; sidebarOpen: boolean; onToggleSidebar: () => void;
  onSend: (text: string) => void; onStop: () => void; onModel: (id: string) => void;
  onEdit: () => void; onClear: () => void; onDelete: () => void;
}) {
  const [menu, setMenu] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const bottom = useRef<HTMLDivElement>(null);
  const scroll = useRef<HTMLDivElement>(null);

  useEffect(() => { if (atBottom) bottom.current?.scrollIntoView({ behavior: running ? 'instant' : 'smooth', block: 'end' }); }, [messages, running, atBottom]);
  useEffect(() => { setMenu(false); setAtBottom(true); }, [teammate?.id]);

  const onScroll = () => {
    const element = scroll.current;
    if (!element) return;
    setAtBottom(element.scrollHeight - element.scrollTop - element.clientHeight < 90);
  };
  const jump = () => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); setAtBottom(true); };

  if (!teammate) return <main className="chat-pane">
    {!sidebarOpen && <div className="chat-header drag-region standalone"><div className="no-drag header-left">{chrome === 'custom' && <WindowControls />}<button className="icon-button" onClick={onToggleSidebar} aria-label="Show sidebar" title="Show sidebar"><Icon name="panelLeft" size={18} /></button></div></div>}
    <div className="blank-workspace"><div className="empty-monogram">a.</div><h1>Your workspace is ready.</h1><p>Create a teammate to begin.</p></div>
  </main>;

  const lastAssistant = [...messages].reverse().find(message => message.role === 'assistant')?.id;
  const showThinking = running && (!messages.length || messages.at(-1)?.role !== 'assistant');
  const tokens = usage ? usage.prompt_tokens + usage.completion_tokens : 0;

  return <main className="chat-pane">
    <header className="chat-header drag-region">
      <div className="header-left no-drag">
        {!sidebarOpen && <>
          {chrome === 'custom' && <WindowControls />}
          <button className="icon-button" onClick={onToggleSidebar} aria-label="Show sidebar" title="Show sidebar"><Icon name="panelLeft" size={18} /></button>
        </>}
        <div className="header-identity"><span className="header-avatar" style={{ '--avatar-color': teammate.color } as React.CSSProperties}>{teammate.emoji || '✦'}</span><div><h2>{teammate.name}</h2><span>{teammate.persona || 'A conversation with room to think'}</span></div></div>
      </div>
      <div className="header-actions no-drag">
        {tokens > 0 && <span className="usage-chip" title="Tokens used in this conversation">{formatTokens(tokens)} tokens{usage && usage.estimated_cost > 0 ? ` · $${usage.estimated_cost.toFixed(4)}` : ''}</span>}
        <div className="menu-wrap"><button className="icon-button header-more" aria-label="Conversation options" aria-expanded={menu} onClick={() => setMenu(!menu)}><Icon name="more" size={19} /></button>{menu && <div className="header-menu" role="menu"><button onClick={() => { setMenu(false); onEdit(); }}><Icon name="edit" size={16} /> Edit teammate</button><button onClick={() => { setMenu(false); onClear(); }}><Icon name="panel" size={16} /> Clear conversation</button><span className="menu-divider" /><button className="danger" onClick={() => { setMenu(false); onDelete(); }}><Icon name="trash" size={16} /> Delete teammate</button></div>}</div>
      </div>
    </header>
    <div className="chat-scroll" ref={scroll} onScroll={onScroll} aria-label={`${teammate.name} conversation`}><div className="transcript">
      {!messages.length && !running ? <div className="welcome"><div className="welcome-emblem"><span>{teammate.emoji || '✦'}</span></div><h1>Good things start<br />with a conversation.</h1><p>{teammate.name} is here to help you think, make, and move forward. What’s on your mind?</p><div className="welcome-rule" /><div className="welcome-prompts"><span>Try asking</span><button onClick={() => onSend('Help me make a clear plan for what I’m working on.')}>Make a plan <span>↗</span></button><button onClick={() => onSend('Review my current project and suggest the next step.')}>Find the next step <span>↗</span></button></div></div> : messages.map(message => <Message key={message.id} message={message} teammate={teammate} streaming={running && message.id === lastAssistant && messages.at(-1)?.id === message.id} />)}
      {showThinking && <div className="thinking-row"><span className="message-avatar" style={{ '--avatar-color': teammate.color } as React.CSSProperties}>{teammate.emoji || '✦'}</span><span className="thinking-dots"><i /><i /><i /></span><span>{teammate.name} is thinking</span></div>}
      <div ref={bottom} />
    </div></div>
    {!atBottom && <button className="jump-to-bottom" onClick={jump} aria-label="Jump to latest"><Icon name="chevron" size={17} /><span>Latest</span></button>}
    <Composer threadId={teammate.id} name={teammate.name} running={running} models={models} model={teammate.model || defaultModel} onModel={onModel} onSend={onSend} onStop={onStop} />
  </main>;
}
