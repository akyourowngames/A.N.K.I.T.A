// Approval view — extracted from Island.tsx (was inline JSX), matching the
// buildApproval card in Coucou's windows/src/views/views.ts
// (MIT License, (c) Louis Raille): who-row, exact command being authorised,
// stable Allow/Deny buttons (never rebuilt mid-click).

import { Card, PillBtn, WhoRow } from './Card';

export type ApprovalItem = {
  requestId: string;
  toolName: string;
  detail: string;
};

export function ApprovalView({
  items, answer, pendingId, error,
}: {
  items: ApprovalItem[];
  answer: (requestId: string, result: 'yes' | 'no' | 'always') => void;
  pendingId: string | null;
  error: string;
}) {
  const top = items[0];
  if (!top) return null;
  return (
    <div className="island-view island-approval-view">
      <Card wash="amber" className="island-approval-card">
        <div className="island-approval">
          <WhoRow color="var(--amber)" name={top.toolName} label="needs permission" />
          <pre className="island-code">{top.detail}</pre>
          {items.length > 1 && (
            <div className="island-quiet">+{items.length - 1} more waiting</div>
          )}
          <div className="island-actions">
            <PillBtn disabled={pendingId !== null} kind="secondary" kbd="N" onClick={() => answer(top.requestId, 'no')}>Deny</PillBtn>
            <PillBtn disabled={pendingId !== null} kind="secondary" onClick={() => answer(top.requestId, 'always')}>Always allow</PillBtn>
            <PillBtn disabled={pendingId !== null} kind="primary" kbd="Y" onClick={() => answer(top.requestId, 'yes')}>{pendingId === top.requestId ? 'Sending…' : 'Allow'}</PillBtn>
          </div>
          {error && <div className="island-inline-error" role="alert">{error}</div>}
        </div>
      </Card>
    </div>
  );
}
