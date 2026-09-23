import { useEffect, useState } from 'react';
import { Icon } from './Icons';

/**
 * The model's reasoning, kept out of the way. It opens while the answer is
 * still being written (so the wait has something to show) and folds up once
 * real content arrives, leaving a single line the user can reopen.
 */
export function ThinkingPanel({ reasoning, streaming }: { reasoning: string; streaming: boolean }) {
  const [open, setOpen] = useState(streaming);
  useEffect(() => { if (streaming) setOpen(true); }, [streaming]);
  if (!reasoning.trim()) return null;
  return <div className={`thinking-panel ${streaming ? 'live' : ''}`}>
    <button type="button" className="thinking-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
      <span className="thinking-glyph"><Icon name="sparkle" size={13} /></span>
      <span className="thinking-label">{streaming ? 'Thinking' : 'Thought process'}</span>
      <span className={`tool-card-chevron ${open ? 'open' : ''}`}><Icon name="chevron" size={15} /></span>
    </button>
    {open && <div className="thinking-body" role="region" aria-label="Model reasoning">{reasoning}</div>}
  </div>;
}
