// Compact chat uses the same ANKITA thread and attachment processing as the desktop.
import { Suspense, lazy, useLayoutEffect, useRef } from 'react';
import { Card } from './Card';
import { Icon } from './icons';
import { TurnCard } from './TurnCard';
import { ToolStep } from './ToolStep';
import type { IslandChat } from './useIslandChat';

const IslandMarkdown = lazy(() => import('./Markdown').then(module => ({ default: module.IslandMarkdown })));
const FOLLOW_DISTANCE_PX = 48; // Pixels from the log bottom; history reading must not jump.

export function Prompt({ chat, onAttach }: { chat: IslandChat; onAttach: () => void }) {
  const { log, thinking, sending, loading, error, input, setInput, submit, stop, teammateId, teammateName } = chat;
  const logRef = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  useLayoutEffect(() => {
    if (follow.current && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log, thinking]);
  useLayoutEffect(() => {
    follow.current = true;
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [teammateId]);
  const lastEntry = log.at(-1);
  const showTyping = thinking && (!lastEntry || lastEntry.kind === 'tool' || lastEntry.role !== 'assistant');
  return <div className="island-view island-prompt">
    <Card wash="indigo">
      <div className="island-chat-body">
        <div className="island-chat-heading">
          <label>Chat with <select aria-label="Chat teammate" value={teammateId || ''} disabled={loading || !chat.teammates.length}
            onChange={event => chat.selectTeammate(event.target.value)}>
            {chat.teammates.map(teammate => <option value={teammate.id} key={teammate.id}>{teammate.name}</option>)}
          </select></label>
          <span>{thinking ? 'Working on it' : 'Same conversation as your desktop'}</span>
        </div>
        <div className="island-chat-log" ref={logRef} role="log" aria-label="Conversation"
          onScroll={() => { const el = logRef.current; if (el) follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < FOLLOW_DISTANCE_PX; }}>
          {log.map(entry => {
            if (entry.kind === 'tool') return <ToolStep key={entry.id} tool={entry} />;
            const markdown = <Suspense fallback={<>{entry.content}</>}>
              <IslandMarkdown content={entry.content} streaming={entry.streaming} teammateId={teammateId} />
            </Suspense>;
            return entry.role === 'user'
              ? <div key={entry.id} className="chat-row user"><div className="bubble">{entry.content}
                  {entry.attachments?.map(file => <span className="island-bubble-file" key={file.name}><Icon name="plus" size={10} />{file.name}</span>)}
                </div></div>
              : <div key={entry.id} className="chat-row"><div className={'reply' + (entry.streaming ? ' streaming' : '') + (entry.job ? ' has-job' : '')}>
                  {entry.job ? <TurnCard name={entry.job.name} status={entry.job.status} at={entry.job.at}>{markdown}</TurnCard> : markdown}
                </div></div>;
          })}
          {showTyping && <div className="chat-row"><div className="typing" role="status" aria-label="Thinking"><i /><i /><i /></div></div>}
          {log.length === 0 && !thinking && <div className="island-chat-empty"><strong>A little space to think.</strong><span>Ask {teammateName} a question, or drop a file here.</span></div>}
        </div>
        {!!chat.attachments.length && <div className="island-attachments">{chat.attachments.map((file, index) =>
          <span className="island-file-chip" key={file.name + index}>
            {file.preview && <img src={file.preview} alt="" />}
            <span title={file.name}>{file.name}</span>
            <button aria-label={'Remove ' + file.name} disabled={sending || chat.reading} onClick={() => chat.removeFile(index)}><Icon name="xmark" size={10} /></button>
          </span>)}</div>}
        {chat.reading && <div className="island-quiet" role="status">Reading files…</div>}
        {error && <div className="island-inline-error" role="alert">{error}</div>}
        <div className="chat-bar">
          <button className="island-tab" aria-label="Choose attachment" disabled={chat.reading || sending || !teammateId} onClick={onAttach}><Icon name="plus" size={14} /></button>
          <textarea className="chat-input" rows={1} aria-label="Message"
            placeholder={teammateId ? 'Ask ' + teammateName + ' anything…' : 'Open Ankita to create a teammate.'}
            value={input} disabled={sending || loading || !teammateId}
            onChange={event => setInput(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); }
              if (event.key !== 'Escape') event.stopPropagation();
            }} />
          {thinking
            ? <button className="send-btn stop-btn" aria-label="Stop reply" title="Stop reply" onClick={() => void stop()}><span /></button>
            : <button className="send-btn" aria-label="Send" title="Send" disabled={sending || chat.reading || !teammateId || (!input.trim() && !chat.attachments.length)} onClick={() => void submit()}><Icon name="arrowUp" size={13} /></button>}
        </div>
        <div className="island-chat-hint">Enter to send<span>Shift + Enter for a new line</span></div>
      </div>
    </Card>
  </div>;
}
