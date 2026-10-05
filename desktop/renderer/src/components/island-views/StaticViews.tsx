// Static island views — React ports of buildEmpty/buildNote/buildError/
// buildFinished/buildConfused in Coucou's windows/src/views/views.ts
// (MIT License, (c) Louis Raille).

import { Card, PillBtn, WhoRow } from './Card';

export function EmptyView({ onAsk }: { onAsk: () => void }) {
  return (
    <div className="island-view">
      <Card wash={null}>
        <div className="island-stack-row">
          <div className="island-stack-col">
            <div className="island-title">Nothing running right now.</div>
            <div className="island-sub">Jobs and approvals appear here.</div>
          </div>
          <div className="grow" />
          <PillBtn kind="primary" onClick={onAsk}>Ask Ankita</PillBtn>
        </div>
      </Card>
    </div>
  );
}

export function NoteView({ message }: { message: string }) {
  return (
    <div className="island-view">
      <Card wash={null}>
        <div className="island-stack-pad">
          <div className="island-title">{message}</div>
        </div>
      </Card>
    </div>
  );
}

export function ErrorView({ who, detail, onRetry }: { who: string; detail: string; onRetry: () => void }) {
  return (
    <div className="island-view">
      <Card wash="red">
        <div className="island-approval">
          <WhoRow color="#F4505E" name={who} label="stopped on an error" />
          <div className="island-title">Workflow stopped.</div>
          <div className="island-detail">{detail || 'No detail available.'}</div>
          <div className="island-actions">
            <PillBtn kind="primary" onClick={onRetry}>Retry</PillBtn>
          </div>
        </div>
      </Card>
    </div>
  );
}

export function FinishedView({ who, detail, onOpen, onOk }: { who: string; detail: string; onOpen: () => void; onOk: () => void }) {
  return (
    <div className="island-view">
      <Card wash="green">
        <div className="island-approval">
          <WhoRow color="#34D399" name={who} label="finished" />
          <div className="island-title">{detail || 'Session finished'}</div>
          <div className="island-actions">
            <PillBtn kind="primary" onClick={onOpen}>Open Ankita</PillBtn>
            <PillBtn kind="secondary" onClick={onOk}>OK</PillBtn>
          </div>
        </div>
      </Card>
    </div>
  );
}

export function ConfusedView() {
  return (
    <div className="island-view">
      <Card wash="pink">
        <div className="island-stack-pad">
          <div className="island-title">Too many hits at once.</div>
          <div className="island-sub">Give me a sec — back to work in three seconds.</div>
        </div>
      </Card>
    </div>
  );
}
