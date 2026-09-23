import { useEffect, useState } from 'react';
import type { WorkspaceDiff, WorkspaceSnapshot } from '../../../shared/wire';
import { Icon } from './Icons';
import { CopyButton } from './CopyButton';

type Tab = 'changes' | 'artifacts' | 'runs';

function DiffLines({ text }: { text: string }) {
  let before = 0, after = 0;
  return <div className="review-diff" role="region" aria-label="File diff">{text.split('\n').map((line, index) => {
    if (line.startsWith('@@')) {
      const match = /@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(line);
      if (match) { before = Number(match[1]); after = Number(match[2]); }
      return <div key={index} className="diff-line hunk"><span /><span /><code>{line}</code></div>;
    }
    if (line.startsWith('diff ') || line.startsWith('index ') || line.startsWith('---') || line.startsWith('+++')) return <div key={index} className="diff-line meta"><span /><span /><code>{line}</code></div>;
    const removed = line.startsWith('-');
    const added = line.startsWith('+');
    const ordinary = !removed && !added && line.startsWith(' ');
    const left = removed || ordinary ? before++ : null;
    const right = added || ordinary ? after++ : null;
    return <div key={index} className={`diff-line ${added ? 'added' : removed ? 'removed' : ''}`}><span>{left}</span><span>{right}</span><code>{line}</code></div>;
  })}</div>;
}

export function WorkspacePanel({ threadId, revision, visible, onClose }: { threadId: string; revision: number; visible: boolean; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>('changes');
  const [snapshot, setSnapshot] = useState<WorkspaceSnapshot | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [diff, setDiff] = useState<WorkspaceDiff | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    const next = await window.ankita.invoke<WorkspaceSnapshot>('workspaceSnapshot', { id: threadId });
    setSnapshot(next);
    if (selected && next.files.some(file => file.path === selected)) setDiff(await window.ankita.invoke<WorkspaceDiff>('workspaceDiff', { id: threadId, path: selected }));
    else if (selected) { setSelected(null); setDiff(null); }
    setError('');
  };
  useEffect(() => { setSnapshot(null); setSelected(null); setDiff(null); }, [threadId]);
  useEffect(() => {
    if (!visible) return;
    let active = true, pending = false;
    const poll = async () => {
      if (pending) return;
      pending = true;
      try {
        const next = await window.ankita.invoke<WorkspaceSnapshot>('workspaceSnapshot', { id: threadId });
        if (!active) return;
        setSnapshot(next);
        if (selected && next.files.some(file => file.path === selected)) {
          const nextDiff = await window.ankita.invoke<WorkspaceDiff>('workspaceDiff', { id: threadId, path: selected });
          if (active) setDiff(nextDiff);
        } else if (selected) { setSelected(null); setDiff(null); }
        if (active) setError('');
      } catch (err) { if (active) setError(err instanceof Error ? err.message : String(err)); }
      finally { pending = false; }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1500);
    return () => { active = false; window.clearInterval(timer); };
  }, [threadId, revision, selected, visible]);

  const stop = async (jobId: string) => {
    setBusy(true);
    try { await window.ankita.invoke('stopWorkspaceJob', { id: threadId, jobId }); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  };
  const showFile = (file: string) => void window.ankita.invoke('showWorkspaceFile', { id: threadId, path: file }).catch(err => setError(err.message));
  const activeJobs = snapshot?.jobs.filter(job => job.state === 'running' || job.state === 'stopping').length || 0;

  return <aside className={`review-panel ${visible ? 'is-open' : 'is-closed'}`} aria-label="Changes, artifacts and runs" aria-hidden={!visible} inert={!visible}>
    <div className="review-top"><div><strong>Work review</strong><span>{snapshot?.cwd || 'Loading workspace'}</span></div><button className="icon-button" onClick={onClose} aria-label="Close work review"><Icon name="close" size={16} /></button></div>
    <div className="review-tabs" role="tablist" aria-label="Work review sections">
      {([['changes', 'Changes', snapshot?.files.length || 0], ['artifacts', 'Artifacts', snapshot?.artifacts.length || 0], ['runs', 'Runs', activeJobs]] as const).map(([id, label, count]) => <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{label}<span>{count}</span></button>)}
    </div>
    {error && <div className="review-error" role="alert">{error}</div>}
    <div className="review-body">
      {tab === 'changes' && <>
        <div className="review-section-head"><span>Working tree</span><button onClick={() => void refresh().catch(err => setError(err.message))} title="Refresh changes" aria-label="Refresh changes"><Icon name="refresh" size={14} /></button></div>
        {!snapshot ? <p className="review-empty">Reading Git changes…</p> : !snapshot.files.length ? <p className="review-empty">No Git changes in this workspace yet. File edits will appear here.</p> : <div className="review-file-list">{snapshot.files.map(file => <button key={file.path} className={selected === file.path ? 'active' : ''} onClick={() => { setSelected(file.path); setDiff(null); }}><span className={`review-status ${file.untracked ? 'new' : file.status.includes('D') ? 'deleted' : ''}`}>{file.untracked ? 'U' : file.status.includes('D') ? 'D' : file.status.includes('A') ? 'A' : 'M'}</span><span title={file.path}>{file.path}</span></button>)}</div>}
        {selected && <div className="review-preview"><div className="review-preview-head"><strong title={selected}>{selected}</strong><div><button onClick={() => showFile(selected)} aria-label={`Show ${selected} in folder`} title="Show in folder"><Icon name="external" size={14} /></button>{diff?.diff && <CopyButton text={diff.diff} compact />}</div></div>{!diff ? <p className="review-empty">Loading diff…</p> : diff.diff ? <><DiffLines text={diff.diff} />{diff.truncated && <p className="review-empty">Diff preview truncated. Open the file for the full content.</p>}</> : <p className="review-empty">{diff.message || 'No text diff is available for this file.'}</p>}</div>}
      </>}
      {tab === 'artifacts' && <><div className="review-section-head"><span>Files created or edited in this conversation</span></div>{!snapshot?.artifacts.length ? <p className="review-empty">Files produced by tools will appear here. Git changes are listed separately.</p> : <div className="review-artifacts">{snapshot.artifacts.map(artifact => <div key={artifact.path}><Icon name="file" size={17} /><span title={artifact.path}><strong>{artifact.name}</strong><small>{artifact.path}</small></span><button onClick={() => showFile(artifact.path)} title="Show in folder" aria-label={`Show ${artifact.name} in folder`}><Icon name="external" size={15} /></button><CopyButton text={artifact.path} compact /></div>)}</div>}</>}
      {tab === 'runs' && <><div className="review-section-head"><span>Command jobs</span><button onClick={() => void refresh()} title="Refresh jobs" aria-label="Refresh jobs"><Icon name="refresh" size={14} /></button></div>{!snapshot?.jobs.length ? <p className="review-empty">Long running commands will appear here with their latest output.</p> : <div className="review-jobs">{snapshot.jobs.map(job => <section key={job.id} className="review-job"><div><span className={`review-job-state ${job.state}`} /> <strong>Job {job.id}</strong><span>{job.state}{job.exit_code !== null ? ` · exit ${job.exit_code}` : ''}</span></div><code>{job.command}</code>{job.output && <pre>{job.output}</pre>}{(job.state === 'running' || job.state === 'stopping') && <button disabled={busy} onClick={() => void stop(job.id)}><Icon name="stop" size={13} /> Stop job</button>}</section>)}</div>}</>}
    </div>
  </aside>;
}
