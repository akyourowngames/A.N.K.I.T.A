import { useId, useMemo, useState } from 'react';
import type { ChatMessage } from '../../../shared/wire';
import { todoProgress } from '../../../shared/todo-progress.mjs';
import { Icon } from './Icons';

const STATUS_TEXT = { pending: 'Pending', in_progress: 'In progress', completed: 'Completed', cancelled: 'Cancelled' };

export function TodoProgress({ messages }: { messages: ChatMessage[] }) {
  const [expanded, setExpanded] = useState(false);
  const listId = useId();
  const todos = useMemo(() => todoProgress(messages), [messages]);
  if (!todos.length) return null;

  const completed = todos.filter(item => item.status === 'completed').length;
  const active = todos.find(item => item.status === 'in_progress');
  const next = active || todos.find(item => item.status === 'pending');
  const detail = next ? next.activeForm : completed === todos.length ? 'All steps complete' : 'No active steps';
  const count = `${completed} of ${todos.length} complete`;

  return <section className={`todo-progress${expanded ? ' expanded' : ''}`} aria-label="Agent checklist">
    <button type="button" className="todo-progress-toggle" aria-expanded={expanded} aria-controls={listId}
      aria-label={`Agent checklist, ${count}. ${detail}. ${expanded ? 'Collapse' : 'Expand'} steps`}
      onClick={() => setExpanded(value => !value)}>
      <span className="todo-progress-symbol" aria-hidden="true"><Icon name="check" size={13} stroke={2.2} /></span>
      <span className="todo-progress-heading">Plan</span>
      <span className="todo-progress-count">{count}</span>
      <span className="todo-progress-detail" title={detail}>{detail}</span>
      <span className="todo-progress-meter" aria-hidden="true"><span style={{ width: `${completed / todos.length * 100}%` }} /></span>
      <span className="todo-progress-chevron" aria-hidden="true"><Icon name="chevron" size={15} /></span>
    </button>
    <span className="sr-only" role="status">{count}. {detail}</span>
    <ol id={listId} className="todo-progress-list" hidden={!expanded}>
      {todos.map((item, index) => <li key={item.id} className={`todo-progress-item ${item.status}`}>
        <span className="todo-progress-index" aria-hidden="true">{item.status === 'completed' ? <Icon name="check" size={13} stroke={2.3} /> : String(index + 1).padStart(2, '0')}</span>
        <span className="todo-progress-content">{item.content}</span>
        <span className="todo-progress-status">{STATUS_TEXT[item.status]}</span>
      </li>)}
    </ol>
  </section>;
}
