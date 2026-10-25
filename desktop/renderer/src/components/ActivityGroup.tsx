import { useId, useState } from 'react';
import type { ActivityItem } from '../lib/activity';
import { Icon } from './Icons';
import { ToolCallCard } from './ToolCallCard';

type ThoughtItem = Extract<ActivityItem, { kind: 'thought' }>;

function ThoughtRow({ item }: { item: ThoughtItem }) {
  const [open, setOpen] = useState(false);
  const preview = item.text.replace(/\s+/g, ' ').trim();
  return <div className="activity-thought">
    <button type="button" className="activity-row" onClick={() => setOpen(!open)} aria-expanded={open}>
      <span className="activity-glyph thought"><Icon name="sparkle" size={13} /></span>
      <span className="activity-label">Thought</span>
      <span className="activity-thought-text">{preview}</span>
    </button>
    {open && <div className="activity-thought-body">{item.text}</div>}
  </div>;
}

/**
 * One compact block for the work between a prompt and its answer. Rows keep
 * every step visible without letting long tool loops push the answer away.
 */
export function ActivityGroup({ items, live, threadId, onOpenBrowserPlugins }: {
  items: ActivityItem[]; live: boolean; threadId: string; onOpenBrowserPlugins?: () => void;
}) {
  const [open, setOpen] = useState(true);
  const listId = useId();
  const toolCount = items.filter(item => item.kind === 'tool').length;
  const failed = items.filter(item => item.kind === 'tool' && item.message.isError).length;
  const thoughts = items.length - toolCount;
  const label = toolCount
    ? `${live ? 'Running' : 'Ran'} ${toolCount} tool${toolCount === 1 ? '' : 's'}`
    : thoughts > 1 ? `Thought ${thoughts} steps` : 'Thought for a moment';
  return <div className={`activity-group ${failed ? 'has-failure' : ''}`}>
    <button type="button" className="activity-group-header" aria-expanded={open} aria-controls={listId} onClick={() => setOpen(!open)}>
      <span className={`activity-group-chevron ${open ? 'open' : ''}`}><Icon name="chevron" size={14} /></span>
      <span className="activity-group-title">{label}</span>
      {failed > 0 && <span className="activity-group-failure">{failed} failed</span>}
      {live && <span className="tool-spinner" aria-hidden="true" />}
    </button>
    {open && <div className="activity-list" id={listId}>
      {items.map(item => item.kind === 'thought'
        ? <ThoughtRow key={item.id} item={item} />
        : <ToolCallCard key={item.id} message={item.message} threadId={threadId} onOpenBrowserPlugins={onOpenBrowserPlugins} variant="row" />)}
    </div>}
  </div>;
}
