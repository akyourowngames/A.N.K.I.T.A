import { useState } from 'react';
import type { SubagentActivity } from '../../../shared/subagent-state.mjs';
import { formatDuration, formatTokens } from '../lib/format';
import { SUBAGENT_FAILED_STATES, subagentStatusLabel, subagentTail, subagentTokens, subagentTypeLabel } from '../lib/subagent';
import { Icon } from './Icons';
import { SubagentTools } from './SubagentTools';

const PREVIEW_CHARS = 240; // Characters; enough to see motion in the collapsed card.

export function SubagentCard({ activity, onOpen }: { activity: SubagentActivity; onOpen?: () => void }) {
  const [open, setOpen] = useState(false);
  const running = activity.status === 'running';
  const failed = SUBAGENT_FAILED_STATES.has(activity.status);
  const status = subagentStatusLabel(activity.status);
  const tokens = subagentTokens(activity);
  const report = activity.text.trim();

  return <div className={`subagent-card ${running ? 'running' : ''} ${failed ? 'failed' : ''}`}>
    <button type="button" className="subagent-card-header" onClick={() => setOpen(!open)} aria-expanded={open}>
      <span className="subagent-glyph"><Icon name="cube" size={15} /></span>
      <span className="subagent-title">
        <strong>{subagentTypeLabel(activity.subagentType)}</strong>
        <span>{activity.description}</span>
      </span>
      <span className="subagent-state">{running && <span className="tool-spinner" />}{status}{activity.durationMs > 0 ? ` · ${formatDuration(activity.durationMs)}` : ''}</span>
      <span className={`tool-card-chevron ${open ? 'open' : ''}`}><Icon name="chevron" size={16} /></span>
    </button>
    {running && report && !open && <pre className="subagent-preview">{subagentTail(activity.text, PREVIEW_CHARS)}</pre>}
    {open && <div className="subagent-body">
      <div className="subagent-meta">
        <span>Depth {activity.depth}</span>
        {tokens > 0 && <span>{formatTokens(tokens)} tokens</span>}
        {activity.tools.length > 0 && <span>{activity.tools.length} tool {activity.tools.length === 1 ? 'call' : 'calls'}</span>}
      </div>
      {activity.prompt && <section>
        <span className="tool-section-label">Brief</span>
        <pre>{activity.prompt}</pre>
      </section>}
      {report && <section>
        <span className="tool-section-label">{running ? 'Live output' : 'Output'}</span>
        <pre>{report}</pre>
      </section>}
      {activity.summary && (!report || activity.status !== 'completed') && <section>
        <span className="tool-section-label">Summary</span>
        <pre>{activity.summary}</pre>
      </section>}
      {activity.tools.length > 0 && <section>
        <span className="tool-section-label">Tool calls</span>
        <SubagentTools tools={activity.tools} />
      </section>}
      {activity.error && <p className="subagent-error">{activity.error}</p>}
      {activity.transcript && <p className="subagent-transcript" title={activity.transcript}>Transcript saved: {activity.transcript}</p>}
    </div>}
    {onOpen && <div className="subagent-card-actions">
      <button type="button" className="subagent-open-panel" onClick={onOpen} title="Follow this sub-agent in the side panel">
        <Icon name="panel" size={14} />
        {running ? 'Watch live' : 'Open in side panel'}
      </button>
    </div>}
  </div>;
}
