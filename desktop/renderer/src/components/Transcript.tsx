import { useMemo } from 'react';
import type { ChatMessage, Routine, Teammate } from '../../../shared/wire';
import type { SubagentActivity } from '../../../shared/subagent-state.mjs';
import { buildTranscript } from '../lib/activity';
import { ActivityGroup } from './ActivityGroup';
import { EditSummaryCard } from './EditSummaryCard';
import { Message } from './Message';

export function Transcript({ messages, teammate, threadId, running, lastAssistantId, onOpenBrowserPlugins, jobs, onEditJob, subagents, onReview, onOpenSubagent, subagentOpen }: {
  messages: ChatMessage[]; teammate: Teammate; threadId: string; running: boolean; lastAssistantId?: string;
  onOpenBrowserPlugins?: () => void; jobs: Routine[]; onEditJob: (id: string) => void;
  subagents?: Record<string, SubagentActivity>; onReview: () => void;
  onOpenSubagent?: (key: string) => void; subagentOpen: boolean;
}) {
  const blocks = useMemo(() => buildTranscript(messages, running), [messages, running]);
  return <>{blocks.map(block => {
    if (block.kind === 'activity') return <ActivityGroup key={block.id} items={block.items} live={block.live} threadId={threadId} onOpenBrowserPlugins={onOpenBrowserPlugins} />;
    if (block.kind === 'edits') return <EditSummaryCard key={block.id} files={block.files} onReview={onReview} />;
    const streaming = running && block.message.role === 'assistant' && block.message.id === lastAssistantId && messages.at(-1)?.id === block.message.id;
    return <Message key={block.id} message={block.message} teammate={teammate} threadId={threadId} streaming={streaming} onOpenBrowserPlugins={onOpenBrowserPlugins} jobs={jobs} onEditJob={onEditJob} subagents={subagents} onOpenSubagent={onOpenSubagent} hideSubagents={subagentOpen} />;
  })}</>;
}
