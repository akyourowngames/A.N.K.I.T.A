import { useEffect, useState } from 'react';
import type { ChatMessage } from '../../../shared/wire';
import { Icon } from './Icons';
import { CopyButton } from './CopyButton';
import { formatDuration, humanizeTool, summarizeArgs } from '../lib/format';

type ToolMessage = Extract<ChatMessage, { role: 'tool' }>;

export function ToolCallCard({ message }: { message: ToolMessage }) {
  const [open, setOpen] = useState(message.isError);
  useEffect(() => { if (message.isError) setOpen(true); }, [message.isError]);

  const running = !message.result && !message.isError;
  const title = humanizeTool(message.name);
  const hint = summarizeArgs(message.args);
  const duration = message.startedAt && message.endedAt ? formatDuration(message.endedAt - message.startedAt) : '';
  const input = typeof message.args === 'string' ? message.args : JSON.stringify(message.args, null, 2);

  return <div className={`tool-card ${message.isError ? 'failed' : ''} ${running ? 'running' : ''}`}>
    <button type="button" className="tool-card-header" onClick={() => setOpen(!open)} aria-expanded={open}>
      <span className="tool-glyph">{running ? <span className="tool-spinner" /> : <Icon name={message.isError ? 'alert' : 'check'} size={15} />}</span>
      <span className="tool-card-title">{title}</span>
      {hint && <span className="tool-card-hint">{hint}</span>}
      <span className="tool-card-state">{message.isError ? 'Needs attention' : running ? 'Running' : duration || 'Completed'}</span>
      <span className={`tool-card-chevron ${open ? 'open' : ''}`}><Icon name="chevron" size={16} /></span>
    </button>
    {open && <div className="tool-card-body">
      <div className="tool-card-toolbar"><span className="tool-section-label">Input</span><CopyButton text={input} compact /></div>
      <pre>{input}</pre>
      <div className="tool-card-toolbar"><span className="tool-section-label">Result</span>{message.result && <CopyButton text={message.result} compact />}</div>
      <pre>{message.result || (running ? 'Waiting for the tool…' : '(no output)')}</pre>
    </div>}
  </div>;
}
