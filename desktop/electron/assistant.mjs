import path from 'node:path';
import { AssistantTaskStore, ASSISTANT_TASK_DIRECTORY } from '../../src/assistant/tasks.mjs';
import { ProfileStore } from '../../src/memory/profile.mjs';
import { AssistantRoutineStore } from '../../src/assistant/routines.mjs';
import { ASSISTANT_ROUTINE_DIRECTORY } from '../../src/assistant/routine-policy.mjs';
import { DEFAULT_JOB_ALLOW } from '../../src/automation/job-policy.mjs';
import { PROFILE_FILE } from '../../src/core/config.mjs';
import { CHATGPT_BROWSER_PROVIDER } from '../shared/chatgpt-browser.mjs';
import { ASSISTANT_CHANGED, KNOWLEDGE_CHANGED, ASSISTANT_ROUTINES_CHANGED, ASSISTANT_LIST_LIMIT, MEMORY_TEXT_LIMIT, RESUMABLE_TASK_STATES } from '../shared/assistant.mjs';

const USER_MEMORY_SOURCE = 'desktop-memory-editor'; // Explicit user edits, distinct from inferred transcript facts.
const SNAPSHOT_LOCALE = 'en-CA'; // Stable day-key formatting; actual day follows the configured time zone.
const EXTERNAL_SOURCE_NOTICE = 'Calendar and inbox have not been checked. Ask in chat to check connected apps.';
const DEFAULT_BRIEFING_PROMPT = 'Give a short local daily briefing.';
const DEFAULT_BRIEFING_NAME = 'Daily briefing';
const RESTORE_WORKSPACE = 'Restore this conversation to its saved project and workspace before running saved work.';
function assertWorkspace(record, agent) {
  if ((record.projectId || null) !== (agent.projectId || null) || (record.workspacePath && record.workspacePath !== (agent.workspacePath || agent.cwd))) throw new Error(RESTORE_WORKSPACE);
}

export class DesktopAssistant {
  constructor(engine, { now = Date.now } = {}) {
    this.engine = engine; this.now = now;
    this.profileFile = path.join(path.dirname(engine.desktopSettings.file), path.basename(PROFILE_FILE));
    this.tasks = new AssistantTaskStore({ directory: path.join(path.dirname(engine.teammates.file), ASSISTANT_TASK_DIRECTORY), transform: engine.secretHistory.clean });
    this.tasks.recoverInterrupted();
    this.routines = new AssistantRoutineStore({ directory: path.join(path.dirname(engine.teammates.file), ASSISTANT_ROUTINE_DIRECTORY), transform: engine.secretHistory.clean });
  }
  context(ownerId, surface = 'desktop') {
    return { assistantTasks: this.tasks, assistantOwnerId: ownerId, assistantSurface: surface, profileFile: this.profileFile,
      onAssistantTask: task => this.engine.emit({ type: ASSISTANT_CHANGED, threadId: ownerId, taskId: task.id }) };
  }
  today() {
    const at = this.now(), owners = new Set(this.engine.listTeammates().map(item => item.id));
    const tasks = this.tasks.list().filter(task => owners.has(task.ownerId));
    const day = new Intl.DateTimeFormat(SNAPSHOT_LOCALE, { timeZone: this.engine.config?.timeZone, dateStyle: 'short' });
    const unfinished = tasks.filter(task => task.status !== 'completed').slice(0, ASSISTANT_LIST_LIMIT);
    const recent = tasks.filter(task => task.status === 'completed' && day.format(task.updatedAt) === day.format(at)).slice(0, ASSISTANT_LIST_LIMIT);
    const jobs = this.engine.schedule().list();
    const upcoming = jobs.filter(job => job.enabled && job.nextRunAt).sort((a, b) => a.nextRunAt.localeCompare(b.nextRunAt)).slice(0, ASSISTANT_LIST_LIMIT);
    const pending = jobs.flatMap(job => this.engine.schedule().pendingDeliveries(job.threadId)).filter((item, i, all) => all.findIndex(other => other.runId === item.runId) === i);
    const commitments = (this.engine.listProjects?.() || []).filter(project => !project.archived).flatMap(project => project.todos.filter(todo => !todo.done).map(todo => ({ ...todo, projectId: project.id, projectName: project.name }))).slice(0, ASSISTANT_LIST_LIMIT);
    return { at, timeZone: this.engine.config?.timeZone || Intl.DateTimeFormat().resolvedOptions().timeZone,
      unfinished, recent, upcoming, pending, commitments,
      briefing: `${unfinished.length} unfinished requests. ${recent.length} completed today. ${upcoming.length} upcoming scheduled tasks. ${pending.length} results waiting for delivery. ${EXTERNAL_SOURCE_NOTICE}`,
      externalSources: { status: 'not_checked', notice: EXTERNAL_SOURCE_NOTICE } };
  }
  async resume({ id, taskId, surface = 'desktop', attachments = null } = {}) {
    if (!this.engine.teammates.find(id)) throw new Error('This conversation is no longer available.');
    const task = this.tasks.get(taskId, { ownerId: id });
    if (!task || !RESUMABLE_TASK_STATES.includes(task.status)) throw new Error('This task cannot be continued now.');
    if (task.browserOperationId) return this.engine.resumeBrowser(id, task.browserOperationId, { assistantTaskId: task.id });
    if (this.engine.config?.provider === CHATGPT_BROWSER_PROVIDER || task.provider === CHATGPT_BROWSER_PROVIDER) throw new Error('This browser request has no confirmed native continuation. Open its conversation to review it before starting new work.');
    const agent = this.engine.agentFor(id);
    assertWorkspace(task, agent);
    return this.engine.send(id, 'Continue the unfinished saved request.', attachments, { surface, assistantTaskId: taskId });
  }
  resolve({ id, taskId, stepId, outcome, evidence } = {}) {
    if (!this.engine.teammates.find(id)) throw new Error('This conversation is no longer available.');
    const task = this.tasks.resolve(taskId, stepId, { ownerId: id, outcome, evidence });
    this.engine.emit({ type: ASSISTANT_CHANGED, threadId: id, taskId }); return task;
  }
  memoryList({ query = '' } = {}) {
    const needle = String(query).toLocaleLowerCase().trim();
    return new ProfileStore(this.profileFile).load().facts.filter(fact => !needle || `${fact.text} ${fact.kind}`.toLocaleLowerCase().includes(needle));
  }
  memorySave({ id, text, kind = 'fact', always, expectedUpdatedAt } = {}) {
    if (typeof text !== 'string' || !text.trim() || text.length > MEMORY_TEXT_LIMIT) throw new Error(`Memory must contain 1–${MEMORY_TEXT_LIMIT} characters.`);
    const store = new ProfileStore(this.profileFile).load();
    const source = { type: USER_MEMORY_SOURCE, at: new Date(this.now()).toISOString() };
    const safe = this.engine.secretHistory.clean({ text, kind, always, source, expectedUpdatedAt });
    const result = id ? store.update(id, safe) : store.add(safe);
    this.engine.emit({ type: KNOWLEDGE_CHANGED }); return result;
  }
  memoryForget({ id } = {}) {
    new ProfileStore(this.profileFile).load().forget(id);
    this.engine.emit({ type: KNOWLEDGE_CHANGED }); return true;
  }
  routineList() { return this.routines.list(); }
  async routineSave({ id, ownerId, sourceTaskId, name, template, parameters, expectedRevision } = {}) {
    if (!this.engine.teammates.find(ownerId)) throw new Error('Choose an available conversation for this routine.');
    const sourceTask = id ? undefined : this.tasks.get(sourceTaskId, { ownerId });
    const result = await this.routines.save({ id, ownerId, sourceTask, name, template, parameters, expectedRevision });
    this.engine.emit({ type: ASSISTANT_ROUTINES_CHANGED }); return result;
  }
  async routineRemove({ routineId, ownerId } = {}) {
    await this.routines.remove(routineId, { ownerId }); this.engine.emit({ type: ASSISTANT_ROUTINES_CHANGED }); return true;
  }
  async preparedRoutine({ routineId, ownerId, values } = {}) {
    if (!this.engine.teammates.find(ownerId)) throw new Error('This routine’s conversation is no longer available.');
    const prepared = await this.routines.prepare(routineId, { ownerId, values });
    if (prepared.missing.length) throw new Error(`Fill in the missing routine values: ${prepared.missing.join(', ')}.`);
    assertWorkspace(prepared.routine, this.engine.agentFor(ownerId)); return prepared;
  }
  async routineRun(input) {
    const prepared = await this.preparedRoutine(input), routine = prepared.routine;
    return this.engine.send(routine.ownerId, prepared.prompt, null, { assistantGoal: prepared.goal,
      assistantSourceTaskId: routine.sourceTaskId, assistantRoutineId: routine.id });
  }
  async routineSchedule(input) {
    const prepared = await this.preparedRoutine(input), routine = prepared.routine;
    // A schedule is a separately reviewed disabled draft; saving/running a reusable request never enables one.
    return this.engine.schedule().add({ threadId: routine.ownerId, projectId: routine.projectId, name: routine.name,
      prompt: prepared.prompt, cron: input.cron, enabled: false,
      allow: { ...DEFAULT_JOB_ALLOW, interact: false, login: false } }, { draft: true });
  }
  async briefingSchedule({ ownerId, cron, prompt = DEFAULT_BRIEFING_PROMPT } = {}) {
    if (!this.engine.teammates.find(ownerId)) throw new Error('Choose an available conversation for this briefing.');
    // Local-only draft: the run reads current saved facts and never claims an unqueried external source.
    return this.engine.schedule().add({ threadId: ownerId, name: DEFAULT_BRIEFING_NAME, kind: 'routine',
      assistantBriefing: true, prompt, cron, enabled: false,
      allow: { ...DEFAULT_JOB_ALLOW, interact: false, login: false } }, { draft: true });
  }
}
