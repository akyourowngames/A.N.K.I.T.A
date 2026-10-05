// Coucou's focus card and a plain teammate list, backed by ANKITA activity.
import { Card, Dot } from './Card';
import { Ticker, type TickerStep } from './Ticker';
import type { IslandTool } from '../../../../shared/island-state.mjs';

export type ActivityItem = {
  id: string; name: string; color: string; running: boolean; needsApproval: boolean;
  label: string; steps: string[]; tools: IslandTool[]; threadId?: string; routineId?: string;
};
const MAX_VISIBLE_TEAMMATES = 4; // Agents; a two-by-two panel stays bounded regardless of saved jobs or name lengths.
const FACE_VARIANTS = ['round', 'peek', 'sleepy', 'bright']; // Four mascot expressions distinguish the visible teammate avatars.
export function Overview({ activities, selectedId, onFocus, onAsk, onStop, onCaptureDrag, onCaptureEnd }: {
  activities: ActivityItem[]; selectedId: string | null; onFocus: (id: string) => void;
  onAsk: (id?: string) => void; onStop: (item: ActivityItem) => void;
  onCaptureDrag?: (event: React.DragEvent, id: string) => void; onCaptureEnd?: (event: React.DragEvent) => void;
}) {
  const focus = activities.find(item => item.id === selectedId) || activities.find(item => item.running) || activities[0];
  const teammates = activities.filter(item => item.threadId && !item.routineId).slice(0, MAX_VISIBLE_TEAMMATES);
  const steps: TickerStep[] = focus?.tools.length ? focus.tools.map(tool => ({ id: tool.id, text: tool.detail, state: tool.state }))
    : (focus?.steps || []).map((text, index, list) => ({ id: focus!.id + ':' + index, text, state: focus!.running && index === list.length - 1 ? 'running' : 'ok' }));
  return <div className="island-view island-overview">
    <Card wash={null} className="island-overview-left">
      {focus ? <>
        <div className="island-who"><Dot color={focus.color} /><span className="name" title={focus.name}>{focus.name}</span><span className="tool">{focus.label}</span></div>
        <div className="island-activity-steps" role="log" aria-label="Live tool activity">
          {steps.length ? <Ticker steps={steps} key={focus.id} />
            : <div className="island-quiet">{focus.running ? 'Thinking about the next step…' : 'Ready when you are.'}</div>}
        </div>
        <div className="island-activity-actions">
          {focus.threadId && <button className="island-text-button" onClick={() => onAsk(focus.threadId)}>Open conversation</button>}
          {focus.running && <button className="island-text-button" onClick={() => onStop(focus)}>Stop</button>}
        </div>
      </> : <div className="island-quiet">Create a teammate in Ankita to get started.</div>}
    </Card>
    {teammates.length > 0 && <div className="island-overview-right">
      <span className="island-section-label">Your teammates</span>
      <div className="island-pills" role="group" aria-label="Teammates">{teammates.map((item, index) =>
        <button key={item.id} className={'island-pill' + (focus?.id === item.id ? ' on' : '') + (item.running ? ' running' : '')}
          title={item.name} aria-label={'Focus ' + item.name} aria-pressed={focus?.id === item.id} onClick={() => onFocus(item.id)}
          draggable onDragStart={event => onCaptureDrag?.(event, item.id)} onDragEnd={onCaptureEnd}
          style={{ '--agent-color': item.color } as React.CSSProperties}>
          <span className="island-mini-face" data-face={FACE_VARIANTS[index]}><i /><i /></span><span className="lbl">{item.name}</span>
          {item.needsApproval && <span className="island-pill-attention" aria-label="Needs approval">!</span>}
        </button>)}</div>
    </div>}
  </div>;
}
