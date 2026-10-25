import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { SubagentActivity } from '../../../shared/subagent-state.mjs';
import { formatDuration, formatTokens } from '../lib/format';
import { subagentStatusLabel, subagentTokens, subagentTone, subagentTypeLabel } from '../lib/subagent';
import { Icon } from './Icons';
import { SubagentTools } from './SubagentTools';

const ELAPSED_TICK_MS = 1000; // ms — live elapsed time refreshes once a second
const FOLLOW_THRESHOLD_PX = 48; // px — keep following while this close to the end

export function SubagentPanel({ activities, focus, visible, onFocus, onClose, onStop }: {
  activities: Record<string, SubagentActivity>;
  focus: string | null;
  visible: boolean;
  onFocus: (key: string) => void;
  onClose: () => void;
  onStop?: () => void;
}) {
  const activity = focus ? activities[focus] : null;
  const running = activity?.status === 'running';
  const tone = activity ? subagentTone(activity.status) : 'idle';
  const tokens = activity ? subagentTokens(activity) : 0;
  const report = activity?.text.trim() || '';
  const entries = Object.entries(activities);
  const ordered = [...entries].sort((a, b) => Number(b[1].status === 'running') - Number(a[1].status === 'running'));
  const scroll = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!running || !visible) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), ELAPSED_TICK_MS);
    return () => window.clearInterval(timer);
  }, [running, visible]);

  useLayoutEffect(() => {
    const element = scroll.current;
    if (!element || !stick.current) return;
    element.scrollTop = element.scrollHeight;
  }, [activity?.text, activity?.tools.length, activity?.status]);

  useEffect(() => {
    stick.current = true;
    const element = scroll.current;
    if (element) element.scrollTop = running ? element.scrollHeight : 0;
  }, [focus, visible]);

  const onScroll = () => {
    const element = scroll.current;
    if (!element) return;
    stick.current = element.scrollHeight - element.scrollTop - element.clientHeight < FOLLOW_THRESHOLD_PX;
  };

  const elapsed = activity ? (running ? Math.max(0, now - activity.startedAt) : activity.durationMs) : 0;

  return <aside className={`subagent-panel ${visible ? 'is-open' : 'is-closed'}`} aria-label="Live sub-agent work" aria-hidden={!visible} inert={!visible}>
    {activity && <>
      <div className="subagent-panel-top">
        <span className="subagent-panel-glyph"><Icon name="cube" size={16} /></span>
        <div className="subagent-panel-heading">
          <span className="subagent-panel-eyebrow">{subagentTypeLabel(activity.subagentType)}</span>
          <strong title={activity.description}>{activity.description || 'Sub-agent'}</strong>
        </div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="Close sub-agent panel"><Icon name="close" size={16} /></button>
      </div>
      <div className={`subagent-panel-status ${tone}`}>
        <span className="subagent-panel-state">{running && <span className="tool-spinner" />}<strong>{subagentStatusLabel(activity.status)}</strong></span>
        <span className="subagent-panel-facts">
          {elapsed > 0 && <span>{running ? 'Elapsed' : 'Took'} {formatDuration(elapsed)}</span>}
          {tokens > 0 && <span>{formatTokens(tokens)} tokens</span>}
          <span>Depth {activity.depth}</span>
          {activity.tools.length > 0 && <span>{activity.tools.length} tool {activity.tools.length === 1 ? 'call' : 'calls'}</span>}
        </span>
        {running && onStop && <button type="button" className="subagent-panel-stop" onClick={onStop} title="Stop the parent turn and its sub-agents"><Icon name="stop" size={12} />Stop</button>}
      </div>
      {ordered.length > 1 && <div className="subagent-panel-switcher" role="tablist" aria-label="Sub-agents">
        {ordered.map(([key, item]) => <button key={key} type="button" role="tab" aria-selected={key === focus} className={`${key === focus ? 'active' : ''} ${subagentTone(item.status)}`} onClick={() => onFocus(key)} title={`${subagentTypeLabel(item.subagentType)} · ${item.description}`}>
          <i />
          <span>{item.description || subagentTypeLabel(item.subagentType)}</span>
          {item.status === 'running' && <small>Working</small>}
        </button>)}
      </div>}
      <div className="subagent-panel-scroll" ref={scroll} onScroll={onScroll}>
        <section className="subagent-panel-section">
          <div className="subagent-panel-section-head">
            <span>{running ? 'Live output' : 'Output'}</span>
            {running && <small>Following</small>}
          </div>
          {report
            ? <pre className="subagent-panel-output">{report}{running && <span className="stream-caret" />}</pre>
            : running
              ? <div className="subagent-panel-waiting"><span className="thinking-dots"><i /><i /><i /></span>Waiting for the first output…</div>
              : <p className="subagent-panel-quiet">No output was recorded.</p>}
        </section>
        {!running && activity.summary && activity.summary !== report && <section className="subagent-panel-section">
          <div className="subagent-panel-section-head"><span>Summary</span></div>
          <pre className="subagent-panel-summary">{activity.summary}</pre>
        </section>}
        {activity.tools.length > 0 && <section className="subagent-panel-section">
          <div className="subagent-panel-section-head"><span>Tool calls</span><small>{activity.tools.length}</small></div>
          <SubagentTools tools={activity.tools} />
        </section>}
        {activity.prompt && <details className="subagent-panel-brief">
          <summary>Task brief</summary>
          <pre>{activity.prompt}</pre>
        </details>}
        {activity.error && <p className="subagent-error">{activity.error}</p>}
        {activity.transcript && <p className="subagent-transcript" title={activity.transcript}>Transcript saved: {activity.transcript}</p>}
      </div>
      <div className="subagent-panel-foot"><Icon name="shield" size={13} /><span>Isolated child session</span></div>
    </>}
  </aside>;
}
