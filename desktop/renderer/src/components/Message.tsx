import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ChatMessage, Teammate } from '../../../shared/wire';
import { ToolCallCard } from './ToolCallCard';
import { ThinkingPanel } from './ThinkingPanel';
import { CopyButton } from './CopyButton';

export function Message({ message, teammate, streaming }: { message: ChatMessage; teammate: Teammate; streaming: boolean }) {
  if (message.role === 'tool') return <ToolCallCard message={message} />;
  if (message.role === 'user') return <div className="message user-message"><div className="user-bubble">{message.content}</div></div>;
  const thinking = Boolean(message.reasoning?.trim()) && streaming && !message.content;
  return <div className="message assistant-message">
    <span className="message-avatar" style={{ '--avatar-color': teammate.color } as React.CSSProperties}>{teammate.emoji || '✦'}</span>
    <div className="assistant-content">
      <span className="assistant-name">{teammate.name}</span>
      {message.reasoning ? <ThinkingPanel reasoning={message.reasoning} streaming={thinking} /> : null}
      <div className="markdown-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
          a: ({ href, children }) => <a href={href} onClick={event => { event.preventDefault(); if (href) void window.ankita.openExternal(href); }}>{children}</a>,
        }}>{message.content}</ReactMarkdown>{streaming && <span className="stream-caret" aria-hidden="true" />}
      </div>
      {!streaming && message.content && <div className="message-actions"><CopyButton text={message.content} /></div>}
    </div>
  </div>;
}
