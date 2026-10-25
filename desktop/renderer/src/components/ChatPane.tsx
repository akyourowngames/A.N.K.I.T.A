import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { BrowserSessionView, ChatMessage, Model, Project, Teammate, Routine } from '../../../shared/wire';
import type { SubagentActivity } from '../../../shared/subagent-state.mjs';
import type { Usage } from '../state/store';
import { Composer } from './Composer';
import { Icon } from './Icons';
import { Transcript } from './Transcript';
import { WindowControls } from './WindowControls';
import { formatTokens } from '../lib/format';
import { BrowserRunCard } from './BrowserStage';
import { JobApprovalCard } from './JobCard';
import { CompanionStatus } from './CompanionStatus';
import { BrowserHelperSetup } from './BrowserHelperSetup';
import { TeammateAvatar } from './TeammateAvatar';
import { jobNeedsAttention, jobStatusSummary } from '../lib/jobs';
import { COMPOSE_EVENT } from '../../../shared/desktop-layout.mjs';
import { CHATGPT_BROWSER_PROVIDER, chatgptHasPendingReply } from '../../../shared/chatgpt-browser.mjs';
import { useChatGptConnection } from './useChatGptConnection';

const STARTERS = [
  { icon: 'check', label: 'Plan the next step', text: 'Help me plan the next step for what I’m working on.' },
  { icon: 'folder', label: 'Review the project', text: 'Review my current project and suggest what to improve.' },
  { icon: 'chat', label: 'Explore an idea', text: 'Help me explore an idea: ' },
]; // User-editable draft starters; none starts a model request.

export function ChatPane({ teammate, messages, running, models, projects, defaultModel, provider, usage, loadedSkills, chrome, sidebarOpen, reviewOpen, browserRun, onToggleSidebar, onToggleReview, onOpenBrowser, onOpenBrowserPlugins, onProject, onOpenProjects, onSend, onStop, onModel, onEdit, onCreate, onClear, onDelete, jobs, onEditJob, onCommand, commandsRevision, subagents, subagentOpen, onToggleSubagent, onOpenSubagent }: {
  jobs: Routine[]; onEditJob: (id?: string) => void;
  teammate: Teammate | null; messages: ChatMessage[]; running: boolean; models: Model[]; defaultModel: string; provider?: string;
  projects: Project[]; usage?: Usage; chrome: string; sidebarOpen: boolean; reviewOpen: boolean; onToggleSidebar: () => void; onToggleReview: () => void; onProject: (id: string | null) => void; onOpenProjects: () => void;
  loadedSkills?: string[];
  subagents?: Record<string, SubagentActivity>; subagentOpen: boolean; onToggleSubagent: () => void; onOpenSubagent: (key: string) => void;
  commandsRevision: number; onCommand: (command: string) => void;
  browserRun?: BrowserSessionView | null; onOpenBrowser: () => void; onOpenBrowserPlugins?: () => void;
  onSend: (text: string, attachments?: { name: string; data: string; kind?: 'document'; images?: string[] }[]) => void; onStop: () => void; onModel: (id: string) => void;
  onEdit: () => void; onCreate: () => void; onClear: () => void; onDelete: () => void;
}) {
  const chatgpt = useChatGptConnection(provider === CHATGPT_BROWSER_PROVIDER);
  const [menu, setMenu] = useState(false);
  const [projectMenu, setProjectMenu] = useState(false);
  const [helperOpen, setHelperOpen] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const scroll = useRef<HTMLDivElement>(null);
  // A ref, not state: the follow decision must be read synchronously by the
  // layout effect, or a streaming delta arriving right after the user scrolls
  // up still sees the previous "at bottom" value and yanks the view back down.
  const stick = useRef(true);
  const pendingJobs = jobs.filter(job => job.pendingApproval);
  const pendingJobIds = pendingJobs.map(job => job.pendingApproval?.requestId).join(',');

  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    const element = scroll.current;
    if (!element) return;
    element.scrollTo({ top: element.scrollHeight, behavior });
    stick.current = true;
    setAtBottom(true);
  }, []);

  // Follow only while parked at the bottom; reading history is never interrupted.
  useLayoutEffect(() => {
    if (!stick.current) return;
    const element = scroll.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [messages, running, pendingJobIds]);

  useLayoutEffect(() => { setMenu(false); setProjectMenu(false); stick.current = true; setAtBottom(true); const element = scroll.current; if (element) element.scrollTop = element.scrollHeight; }, [teammate?.id]);

  useEffect(() => {
    if (!helperOpen) return;
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') setHelperOpen(false); };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [helperOpen]);

  const onScroll = () => {
    const element = scroll.current;
    if (!element) return;
    const near = element.scrollHeight - element.scrollTop - element.clientHeight < 90;
    stick.current = near;
    setAtBottom(near);
  };
  const jump = () => scrollToBottom('smooth');

  if (!teammate) return <main className="chat-pane">
    {!sidebarOpen && <div className="chat-header drag-region standalone"><div className="no-drag header-left">{chrome === 'custom' && <WindowControls />}<button className="icon-button" onClick={onToggleSidebar} aria-label="Show sidebar" title="Show sidebar (Ctrl+B)" aria-expanded={false}><Icon name="panelLeft" size={18} /></button></div></div>}
    <div className="blank-workspace"><TeammateAvatar className="welcome-face" /><h1>Meet your first teammate.</h1><p>Give them a name and something to work on.</p><button className="button-primary" onClick={onCreate}><Icon name="plus" size={16} /> Create teammate</button></div>
  </main>;

  const lastAssistant = [...messages].reverse().find(message => message.role === 'assistant')?.id;
  const tail = messages.at(-1);
  const showThinking = running && (!tail || (tail.role === 'assistant' && !tail.content.trim() && !tail.reasoning?.trim()));
  const subagentList = Object.values(subagents || {});
  const subagentWorking = subagentList.filter(activity => activity.status === 'running').length;
  const subagentLabel = subagentWorking ? `${subagentWorking} agent${subagentWorking === 1 ? '' : 's'} working` : `${subagentList.length} sub-agent${subagentList.length === 1 ? '' : 's'}`;
  const tokens = usage ? usage.prompt_tokens + usage.completion_tokens : 0;
  const jobTone = jobs.some(jobNeedsAttention) ? 'attention' : jobs.some(job => job.running) ? 'running' : '';
  const jobChip = `${jobs.length} ${jobs.length === 1 ? 'job' : 'jobs'} · ${jobStatusSummary(jobs)}`;
  const jobChipTitle = jobs.length ? `Scheduled jobs · ${jobChip}` : 'Schedule a task';
  const assignedProject = projects.find(project => project.id === teammate.projectId);
  const instructions = loadedSkills?.length ? `Instructions loaded: ${loadedSkills.join(', ')}` : null; // Display actual request inclusion supplied by the engine; absent receipts retain the persona subtitle.
  const needsReplyCheck = provider === CHATGPT_BROWSER_PROVIDER && (chatgptHasPendingReply(chatgpt) || Boolean(chatgpt?.blockedReason));

  return <main className="chat-pane">
    <header className="chat-header drag-region">
      <div className="header-left no-drag">
        {!sidebarOpen && <>{chrome === 'custom' && <WindowControls />}<button className="icon-button header-sidebar-toggle" onClick={onToggleSidebar} aria-label="Show sidebar" title="Show sidebar (Ctrl+B)" aria-expanded={false}><Icon name="panelLeft" size={18} /></button></>}
        <div className="header-identity"><CompanionStatus messages={messages} running={running} teammate={teammate} /><div className="header-copy"><div className="header-name-line"><h2 title={teammate.name}>{teammate.name}</h2></div><p title={instructions || teammate.persona} role={instructions ? 'status' : undefined}>{instructions || teammate.persona || 'Your teammate'}</p></div></div>
      </div>
      <div className="header-actions no-drag">
        <button className="icon-button palette-launcher" onClick={() => window.dispatchEvent(new Event('ankita:palette'))} aria-label="Open command palette" title="Commands, skills and tasks (Ctrl+K)"><Icon name="search" size={16} /></button>
        <div className="menu-wrap"><button className="icon-button header-more" aria-label="Conversation options" aria-expanded={menu} onClick={() => setMenu(!menu)}><Icon name="more" size={19} /></button>{menu && <div className="header-menu" role="menu"><button onClick={() => { setMenu(false); onEdit(); }}><Icon name="edit" size={16} /> Edit teammate</button><button onClick={() => { setMenu(false); onClear(); }}><Icon name="panel" size={16} /> Clear conversation</button><button onClick={() => { setMenu(false); setHelperOpen(true); }}><Icon name="browser" size={16} /> Browser helper</button><span className="menu-divider" /><button className="danger" onClick={() => { setMenu(false); onDelete(); }}><Icon name="trash" size={16} /> Delete teammate</button></div>}</div>
      </div>
    </header>
    <div className="chat-context-bar">
      <div className="project-picker"><button className="project-picker-button" onClick={() => setProjectMenu(!projectMenu)} aria-expanded={projectMenu} title="Choose this teammate's project"><Icon name="folder" size={15} /><span>{assignedProject?.name || 'Choose project'}</span><Icon name="chevron" size={13} /></button>{projectMenu && <div className="project-picker-menu"><span>Work in</span><button className={!teammate.projectId ? 'active' : ''} disabled={running} onClick={() => { onProject(null); setProjectMenu(false); }}>No project</button>{projects.filter(project => !project.archived).map(project => <button key={project.id} className={teammate.projectId === project.id ? 'active' : ''} disabled={running} onClick={() => { onProject(project.id); setProjectMenu(false); }}><strong>{project.name}</strong><small>{project.path || project.summary || 'Project context'}</small></button>)}<button className="project-picker-manage" onClick={() => { setProjectMenu(false); onOpenProjects(); }}>Manage projects <Icon name="arrowRight" size={14} /></button></div>}</div>
      <div className="context-actions">
        {tokens > 0 && <span className="usage-chip" title="Tokens used in this conversation">{formatTokens(tokens)} tokens{usage && usage.estimated_cost > 0 ? ` · $${usage.estimated_cost.toFixed(4)}` : ''}</span>}
        <button className={`jobs-header-chip ${jobTone}`} onClick={() => onEditJob()} aria-label="Scheduled jobs" title={jobChipTitle}><Icon name="clock" size={14} />{jobTone && <i className="jobs-live-dot" aria-hidden="true" />}<span>{jobs.length ? jobChip : 'Schedule'}</span></button>
        {subagentList.length > 0 && <button className={`context-review-button subagent-toggle ${subagentOpen ? 'active' : ''}`} onClick={onToggleSubagent} aria-label="Sub-agent activity" aria-pressed={subagentOpen} title="Watch sub-agents work"><Icon name="cube" size={15} />{subagentWorking > 0 && <i className="subagent-live-dot" />}<span>{subagentLabel}</span></button>}
        <button className={`context-review-button review-toggle ${reviewOpen ? 'active' : ''}`} onClick={onToggleReview} aria-label="Review changes, artifacts and runs" aria-pressed={reviewOpen} title="Work review"><Icon name="panel" size={15} /><span>Work review</span></button>
      </div>
    </div>
    <div className="chat-scroll" ref={scroll} onScroll={onScroll} aria-label={`${teammate.name} conversation`}><div className="transcript">
       {!messages.length && !running && !pendingJobs.length ? <div className="welcome"><TeammateAvatar id={teammate.id} color={teammate.color} className="welcome-face" /><h1>What are we working on?</h1><p>Talk it through with {teammate.name}, or drop a file on their mascot.</p><div className="welcome-prompts">{STARTERS.map(starter => <button key={starter.label} onClick={() => window.dispatchEvent(new CustomEvent(COMPOSE_EVENT, { detail: { text: starter.text, append: true } }))}><Icon name={starter.icon} size={16} /><span>{starter.label}</span></button>)}</div></div> : <Transcript messages={messages} teammate={teammate} threadId={teammate.id} running={running} lastAssistantId={lastAssistant} onOpenBrowserPlugins={onOpenBrowserPlugins} jobs={jobs} onEditJob={onEditJob} subagents={subagents} onReview={onToggleReview} onOpenSubagent={onOpenSubagent} subagentOpen={subagentOpen} />}
      {showThinking && <div className="thinking-row"><TeammateAvatar id={teammate.id} color={teammate.color} className="message-avatar" /><span className="thinking-dots"><i /><i /><i /></span><span>{teammate.name} is thinking</span></div>}
      {browserRun?.mode && browserRun.tabs.length > 0 && <BrowserRunCard view={browserRun} onOpen={onOpenBrowser} />}
      {jobs.filter(job => job.pendingApproval).map(job => <JobApprovalCard key={job.id} job={job} onEdit={onEditJob} />)}
      <div />
    </div></div>
    {!atBottom && <button className="jump-to-bottom" onClick={jump} aria-label="Jump to latest"><Icon name="chevron" size={17} /><span>Latest</span></button>}
    <Composer threadId={teammate.id} name={teammate.name} messages={messages} running={running} sendDisabled={needsReplyCheck} models={models} model={teammate.model || defaultModel} provider={provider} projects={projects} projectId={teammate.projectId} commandsRevision={commandsRevision} onProject={onProject} onCommand={onCommand} onModel={onModel} onSend={onSend} onStop={onStop} />
    {helperOpen && <div className="modal-backdrop no-drag" onClick={event => { if (event.target === event.currentTarget) setHelperOpen(false); }}>
      <div className="helper-dialog" role="dialog" aria-modal="true" aria-labelledby="browser-helper-title">
        <div className="helper-dialog-head"><h2 id="browser-helper-title">Browser helper</h2><button type="button" className="icon-button" aria-label="Close browser helper" autoFocus onClick={() => setHelperOpen(false)}><Icon name="close" size={16} /></button></div>
        <BrowserHelperSetup />
      </div>
    </div>}
  </main>;
}
