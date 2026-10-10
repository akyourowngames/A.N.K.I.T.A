import fs from 'node:fs';
import path from 'node:path';
import { randomUUID, createHash } from 'node:crypto';
import { BROWSER_OPERATIONS } from '../../tools/browser/operations.mjs';
import { normalizeSchedule } from '../../src/automation/cron.mjs';
import { HEARTBEAT_QUIET, JOB_MUTABLE_FIELDS, JOB_EXECUTION_COMPLETE, JOB_EXECUTION_POLICIES, normalizeRoutine } from '../../src/automation/job-policy.mjs';
import { redactValue } from '../../src/security/secret-scrubber.mjs';
import { RoutineStore } from '../../src/automation/routines.mjs';
import { Daemon } from '../../src/automation/daemon.mjs';
import { isLogOnlyTemplate } from '../../src/automation/templates.mjs';
import { cronFire, describeCron } from '../../src/automation/cron.mjs';
import { CONFIG_DIR, STATE_FILE, SESSIONS_DIR } from '../../src/core/config.mjs';
import { SchedulerOwnership } from '../../src/automation/scheduler-ownership.mjs';
import { writeTextFile } from '../../tools/shared/_shared.mjs';
import { approval as browserDescription } from '../../tools/browser/browser.mjs';
import { normalizeBrowserArgs } from '../../tools/browser/pending.mjs';
import { browserNotice } from '../../src/integrations/browser-errors.mjs';
import { CHROME_MCP_ID } from '../../src/integrations/browser-plugins.mjs';
import { APPROVAL_TIMEOUT_MS, CATCH_UP_WINDOW_MS, JOB_HISTORY_KEEP, JOB_PROOF_MAX_BYTES, JOB_SUMMARY_MAX_CHARS, MAX_CONCURRENT_JOBS, MAX_ROUTINE_SITES, SCHEDULER_LOCK_FILENAME, SCHEDULER_TICK_MS, JOB_BROWSER_DIRECTORY } from '../../src/automation/job-policy.mjs';

const MINUTE_MS = 60_000; // Clock conversion; schedules and wall budgets use minutes.
const DRAIN_MS = 10_000; // Bounded main-process shutdown.
const JOB_TOOLS = new Set(['browser', 'find_tools', 'write_todos', 'web_search', 'web_fetch', 'scrape', 'recall', 'remember', 'composio', 'project_memory', 'schedule', 'schedule_status']); // Task data/tools only; no shell or external browser MCP bypass.
const READ_ACTIONS = new Set(Object.entries(BROWSER_OPERATIONS).filter(([, operation]) => !operation.approval).map(([action]) => action)); // Routine read permission includes browsing navigation/status/cancellation; interactions retain separate approval.
const MUTABLE_FIELDS = new Set(JOB_MUTABLE_FIELDS);
const FAILURE_TEXT = 'Browser step failed; execution stopped without retry. Review the last proof before running again.';
const INCOMPLETE_JOB_TEXT = 'Job stopped before completion because the worker could not make further progress. Review the last proof; no task retry was made.';
const REQUEST_KEY_LIMIT = 256; // Characters in a durable creation identifier, not task text.
function dayAt(now, timeZone) { return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(now); }
function siteRule(url, rule) {
  try {
    const target = new URL(url);
    const value = rule.includes('://') ? rule : `https://${rule}`;
    const permitted = new URL(value);
    if (target.origin !== permitted.origin) return false;
    const suffix = permitted.pathname.endsWith('*');
    const pathname = suffix ? permitted.pathname.slice(0, -1) : permitted.pathname;
    return suffix ? target.pathname.startsWith(pathname) : target.pathname === pathname;
  } catch { return false; }
}
function safeOrigin(url) { try { return new URL(url).origin; } catch { return ''; } }
function proofUrl(url) { try { const value = new URL(url); value.username = ''; value.password = ''; value.search = ''; value.hash = ''; return value.href; } catch { return null; } }
function jobError(message, status = 'error') { return Object.assign(new Error(message), { jobStatus: status }); }

/** Main-process adapter around the existing Daemon dispatch, chain and drain. */
export class DesktopScheduler {
  constructor({ engine, file = STATE_FILE, sessionsDir = SESSIONS_DIR, now = () => new Date(), tickMs = SCHEDULER_TICK_MS, approvalTimeoutMs = APPROVAL_TIMEOUT_MS, ownership = null, requireOwnership = false } = {}) {
    this.requireOwnership = requireOwnership;
    Object.assign(this, { engine, now, tickMs, approvalTimeoutMs });
    this.transform = engine.secretHistory?.clean || redactValue;
    this.store = new RoutineStore(file, { transform: this.transform }).load(); this.directory = path.join(sessionsDir, JOB_BROWSER_DIRECTORY);
    this.profileDirectory = path.join(path.dirname(file), 'browser', JOB_BROWSER_DIRECTORY);
    this.timeZone = engine.config?.timeZone || Intl.DateTimeFormat().resolvedOptions().timeZone;
    dayAt(now(), this.timeZone); // Reject an invalid timezone before any work can fire.
    this.runs = new Map(); this.approvals = new Map(); this.nominal = new Map(); this.foregroundAvailable = true;
    this.ownership = ownership || new SchedulerOwnership(path.join(path.dirname(file), SCHEDULER_LOCK_FILENAME));
    const adapter = Object.create(this.store);
    adapter.load = () => this.store.load();
    adapter.dueRoutines = date => this.due(date);
    adapter.claimRoutine = (id, at) => this.store.updateRoutine(id, { lastRun: at, lastFireAt: this.nominal.get(id)?.toISOString(), runAt: null });
    this.daemon = new Daemon({ store: adapter, config: engine.config || {}, client: engine.client, maxConcurrent: MAX_CONCURRENT_JOBS,
      now, tickMs, routinesOnly: true, routineExecutor: routine => this.execute(routine), routineSettled: () => this.changed(), log: () => {} });
  }
  changed() { this.engine.emit({ type: 'schedule-changed', jobs: this.list() }); }
  owner(routine) {
    const owners = this.engine.teammates.list();
    const found = owners.find(item => item.id === routine.threadId);
    return { owner: found || [...owners].sort((a, b) => String(b.updatedAt || '').localeCompare(String(a.updatedAt || '')))[0], ownerMissing: !found };
  }
  validateOwner(threadId) { if (!this.engine.teammates.find(threadId)) throw new Error('Teammate not found'); }
  validatePermissions(allow) {
    if (allow?.sites && (!Array.isArray(allow.sites) || allow.sites.length > MAX_ROUTINE_SITES || allow.sites.some(site => !safeOrigin(site.includes('://') ? site : `https://${site}`)))) throw new Error('Enter valid site URLs within the routine site limit');
    if (allow?.mode && allow.mode !== 'isolated') throw new Error('Background jobs use isolated Chromium. Use Chrome for foreground browsing.');
  }
  validateLimits(input) {
    if (input.projectId !== undefined) this.engine.validateJobProject?.(input.projectId);
    const limits = [input.timeoutMs, ...Object.values(input.budget || {})].filter(value => value !== undefined);
    if (limits.some(value => !Number.isFinite(value) || value <= 0)) throw new Error('Execution timeout and daily budgets must be positive numbers');
    for (const [key, values] of Object.entries({ kind: ['routine', 'heartbeat'], browserPolicy: ['autonomous', 'scoped'], executionPolicy: JOB_EXECUTION_POLICIES })) if (input[key] !== undefined && !values.includes(input[key])) throw new Error(`Invalid ${key}`);
    if (input.requestKey !== undefined && (typeof input.requestKey !== 'string' || !input.requestKey.trim() || input.requestKey.length > REQUEST_KEY_LIMIT)) throw new Error('Invalid creation request key');
  }
  add(input, { draft = false } = {}) {
    this.validateOwner(input.threadId); this.validatePermissions(input.allow); this.validateLimits(input);
    const definition = normalizeRoutine(input);
    const fingerprint = createHash('sha256').update(JSON.stringify([...MUTABLE_FIELDS].sort().map(key => [key, key === 'cron' ? normalizeSchedule(input.cron) : key === 'enabled' ? input.enabled !== false : definition[key]]))).digest('hex');
    if (input.requestKey) {
      const prior = this.store.load().routines.find(r => r.threadId === input.threadId && r.requestKey === input.requestKey);
      if (prior) { if (prior.creationFingerprint !== fingerprint) throw new Error('Creation request key belongs to a different task'); return this.list().find(r => r.id === prior.id); }
    }
    input = { ...Object.fromEntries(Object.entries(input).filter(([key]) => MUTABLE_FIELDS.has(key) || key === 'requestKey')), creationFingerprint: fingerprint };
    const routine = this.store.addRoutine({ ...input, channel: 'desktop', enabled: draft ? false : input.enabled !== false });
    this.store.updateRoutine(routine.id, { createdAt: this.now().toISOString(), draft });
    this.changed(); if (draft) this.engine.emit({ type: 'routine-draft', threadId: routine.threadId, routineId: routine.id });
    return this.list().find(item => item.id === routine.id);
  }
  update(id, patch) {
    if (patch.threadId !== undefined) this.validateOwner(patch.threadId);
    this.validatePermissions(patch.allow); this.validateLimits(patch);
    const permitted = Object.fromEntries(Object.entries(patch).filter(([key]) => MUTABLE_FIELDS.has(key)));
    if (permitted.enabled === true) permitted.pausedReason = null;
    const result = this.store.updateRoutine(id, { ...permitted, draft: false, draftPatch: null });
    if (!result) throw new Error('Routine not found'); this.changed(); return this.list().find(item => item.id === result.id);
  }
  remove(id) {
    id = this.store.load().findRoutine(id)?.id || id;
    if (this.daemon.runningRoutines.has(id)) throw new Error('Stop the running job before removing it');
    const result = this.store.removeRoutine(id); this.changed(); return result;
  }
  proposeUpdate(id, patch) {
    if (!this.store.load().findRoutine(id)) throw new Error('Routine not found');
    if (patch.threadId !== undefined) this.validateOwner(patch.threadId);
    this.validatePermissions(patch.allow); this.validateLimits(patch);
    this.store.updateRoutine(id, { draftPatch: Object.fromEntries(Object.entries(patch).filter(([key]) => MUTABLE_FIELDS.has(key))) });
    this.reviewRun(id); this.changed();
  }
  reviewRun(id) { const r = this.store.load().findRoutine(id); if (!r) throw new Error('Routine not found'); this.engine.emit({ type: 'routine-draft', routineId: r.id, threadId: this.owner(r).owner?.id }); }
  enable(id, enabled) { return this.update(id, { enabled }); }
  pauseAll() { for (const r of this.store.load().routines) this.store.updateRoutine(r.id, { enabled: false }); this.changed(); return this.list(); }
  list(threadId = null) {
    this.store.load();
    return this.store.routines.map(routine => {
      const run = this.runs.get(routine.id), ownership = this.owner(routine);
      const next = routine.enabled ? cronFire(routine.cron, this.now(), this.timeZone) : null;
      return { ...routine, ownerMissing: ownership.ownerMissing, deliveryThreadId: ownership.owner?.id || null,
        cronLabel: describeCron(routine.cron), timeZone: this.timeZone, nextRunAt: next?.toISOString() || null, nextRunIn: next ? Math.max(0, next - this.now()) : null,
        running: this.daemon.runningRoutines.has(routine.id), step: run?.step || 0, scope: run?.scope || null,
        needsApproval: Boolean(routine.pendingApproval), ...(!run ? {} : { activeRunId: run.runId }) };
    }).filter(r => !threadId || r.threadId === threadId || (r.ownerMissing && r.deliveryThreadId === threadId));
  }
  status(threadId = null) { return this.list(threadId); }
  due(date) {
    const due = [];
    for (const routine of this.store.routines) {
      const day = dayAt(date, this.timeZone);
      if (routine.spend.day !== day) this.store.updateRoutine(routine.id, { spend: { day, runs: 0, tokens: 0, minutes: 0 } });
      const fire = routine.runAt ? new Date(routine.runAt) : routine.enabled ? cronFire(routine.cron, date, this.timeZone, -1) : null;
      if (!fire || fire > date || !Number.isFinite(fire.getTime())) continue;
      const previous = Date.parse(routine.lastFireAt || routine.lastRun || routine.createdAt || '');
      if (!routine.runAt && Number.isFinite(previous) && fire.getTime() <= previous) continue;
      if (routine.kind === 'heartbeat' && this.engine.turns?.has(this.owner(routine).owner?.id)) {
        this.store.updateRoutine(routine.id, { lastFireAt: fire.toISOString(), runAt: null, lastStatus: 'skipped-busy', lastSummary: 'Heartbeat skipped while teammate is replying.' });
        this.changed(); continue;
      }
      if (this.daemon.runningRoutines.has(routine.id)) {
        this.store.updateRoutine(routine.id, { lastFireAt: fire.toISOString(), runAt: null, lastStatus: 'skipped-busy', lastSummary: 'Next fire skipped: previous run is still active.' });
        const pending = this.runs.get(routine.id)?.pendingRequest;
        if (pending) this.respondApproval(pending, 'superseded');
        this.changed(); continue;
      }
      this.nominal.set(routine.id, fire);
      if (date - fire > CATCH_UP_WINDOW_MS) {
        this.store.updateRoutine(routine.id, { lastFireAt: fire.toISOString(), runAt: null, lastStatus: 'missed', lastSummary: `Missed ${fire.toISOString()} run; outside catch-up window.` });
        if (!isLogOnlyTemplate(routine)) this.engine.emit({ type: 'routine-failed', routineId: routine.id, threadId: this.owner(routine).owner?.id, status: 'missed' }); this.changed(); continue;
      }
      due.push(this.store.findRoutine(routine.id));
    }
    return due;
  }
  async runNow(id) {
    id = this.store.load().findRoutine(id)?.id || id;
    if (this.requireOwnership && !this.started) throw new Error('Scheduler ownership is unavailable. Stop the other scheduler before running jobs.');
    if (this.daemon.stopping) throw new Error('Scheduler is stopped');
    if (this.daemon.runningRoutines.has(id)) return { notice: 'already running — watch it live' };
    const routine = this.store.load().findRoutine(id); if (!routine) throw new Error('Routine not found');
    this.store.updateRoutine(id, { runAt: this.now().toISOString() }); await this.tick(); return { queued: true };
  }
  async tick() {
    if (this.started && !this.ownership.heartbeat()) { await this.stop(); this.engine.emit({ type: 'scheduler-stopped', message: 'Scheduler ownership handed over. Jobs paused in this desktop process.' }); return; }
    await this.daemon.tickOnce(); await this.retryDeliveries();
  }
  async start() {
    if (this.started) return;
    if (this.starting) return this.starting;
    this.starting = this.startOwned();
    try { await this.starting; } finally { this.starting = null; }
  }
  async startOwned() {
    await this.ownership.acquire(); this.started = true;
    // A process restart cannot resume a potentially submitted browser mutation.
    for (const r of this.store.load().routines) if (r.pendingApproval || r.activeRunId) this.store.updateRoutine(r.id, { pendingApproval: null, activeRunId: null, lastStatus: 'interrupted', lastSummary: 'App stopped during the last run. Review proof before running again.' });
    this.loop = (async () => { while (!this.daemon.stopping) { try { await this.tick(); } catch (error) { this.engine.emit({ type: 'scheduler-error', message: error.message }); } if (!this.daemon.stopping) await this.daemon.pause(this.tickMs); } })();
  }
  drain() { return this.daemon.drain(DRAIN_MS); }
  async stop() {
    this.daemon.stop(); for (const run of this.runs.values()) run.fail?.(jobError('Job stopped on application quit.', 'stopped'));
    for (const id of [...this.approvals.keys()]) this.respondApproval(id, 'no');
    await this.drain(); this.ownership.release(); this.started = false;
  }
  stopRun(id) { id = this.store.load().findRoutine(id)?.id || id; const run = this.runs.get(id); run?.fail?.(jobError('Job stopped by user.', 'stopped')); return Boolean(run); }
  async authorize(run, raw, context) {
    const args = normalizeBrowserArgs(raw), routine = this.store.load().findRoutine(run.routineId);
    if (!routine || !run.active) throw jobError('Job is no longer active', 'stopped');
    const budget = run.elapsed && this.budgetLeg(routine, run);
    if (budget) throw jobError(`Daily ${budget} budget reached`, 'stopped-budget');
    if (context.mode !== routine.allow.mode) throw jobError('Browser mode is outside routine permission');
    if (!routine.headless && !this.foregroundAvailable) throw jobError('A visible browser needs the unlocked desktop', 'skipped-needs-foreground');
    if (context.mode === 'local' && !this.foregroundAvailable) throw jobError('My Chrome needs the unlocked desktop', 'skipped-needs-foreground');
    if (context.mode === 'local' && !this.engine.mcp?.has?.(CHROME_MCP_ID)) throw jobError('Connect and approve My Chrome in desktop first', 'skipped-needs-foreground');
    if (routine.browserPolicy === 'autonomous') return true;
    const category = args.action === 'login' ? 'login' : READ_ACTIONS.has(args.action) ? 'read' : 'interact';
    const url = context.url, origin = safeOrigin(url);
    const siteAllowed = !url || url === 'about:blank' || routine.allow.sites.some(rule => siteRule(url, rule)) || run.grants.has(`site:${origin}`);
    if (siteAllowed && routine.allow[category]) return true;
    if (routine.onNewRequest === 'deny') throw jobError('Routine permission denied this browser step', 'denied');
    if (!this.foregroundAvailable) throw jobError('New permission requires the unlocked desktop', 'skipped-needs-foreground');
    if (run.pendingRequest) throw jobError('Another permission is already pending');
    const detail = `${browserDescription(args)}${origin ? ` on ${origin}` : ''}`;
    let requestId, expiryTimer;
    run.pauseTimer?.();
    const wait = this.engine.approvals.request(run.threadId, 'browser', detail, { routineId: routine.id, runId: run.runId, expiresAt: new Date(Date.now() + this.approvalTimeoutMs).toISOString(),
      onRegistered: id => {
        requestId = id; run.pendingRequest = id;
        this.approvals.set(id, { run, category, origin, routineId: routine.id });
        this.store.updateRoutine(routine.id, { pendingApproval: { requestId: id, routineId: routine.id, runId: run.runId, tool: 'browser', redactedDetail: detail, expiresAt: new Date(Date.now() + this.approvalTimeoutMs).toISOString() } });
        expiryTimer = setTimeout(() => this.respondApproval(id, 'expired'), this.approvalTimeoutMs);
      } });
    this.changed();
    try {
      const ok = await wait;
      if (!ok) throw jobError(run.approvalOutcome === 'expired' ? 'Run skipped: no approval within deadline.' : 'Run skipped: permission declined or superseded.', run.approvalOutcome === 'expired' ? 'skipped-no-approval' : run.approvalOutcome === 'superseded' ? 'superseded' : 'denied');
      run.grants.add(`site:${origin}`); return true;
    } finally {
      clearTimeout(expiryTimer); this.approvals.delete(requestId); run.pendingRequest = null;
      this.store.updateRoutine(routine.id, { pendingApproval: null }); run.resumeTimer?.(); this.changed();
    }
  }
  respondApproval(id, answer) {
    const pending = this.approvals.get(id); if (!pending) return false;
    pending.run.approvalOutcome = answer;
    pending.run.audit?.push({ approval: answer, category: pending.category, origin: pending.origin, at: this.now().toISOString() });
    if (answer === 'always') {
      const routine = this.store.load().findRoutine(pending.routineId);
      if (!routine) return false;
      const sites = [...routine.allow.sites];
      if (pending.origin && !sites.some(rule => siteRule(`${pending.origin}/`, rule))) sites.push(`${pending.origin}/*`);
      if (sites.length > MAX_ROUTINE_SITES) throw new Error('Routine site permission limit reached');
      this.store.updateRoutine(routine.id, { allow: { ...routine.allow, [pending.category]: true, sites } });
    }
    this.engine.emit({ type: 'routine-approval-ended', requestId: id, routineId: pending.routineId, threadId: pending.run.threadId, outcome: answer });
    return this.engine.approvals.respond(id, answer);
  }
  budgetLeg(routine, run) {
    if (routine.executionPolicy === JOB_EXECUTION_COMPLETE) return null;
    const spend = routine.spend;
    if (spend.runs >= routine.budget.maxRunsPerDay) return 'runs';
    if (spend.tokens + run.tokens >= routine.budget.maxTokensPerDay) return 'tokens';
    if (spend.minutes + run.elapsed() / MINUTE_MS >= routine.budget.maxMinutesPerDay) return 'minutes';
    return null;
  }
  async execute(dispatched) {
    const routine = this.store.load().findRoutine(dispatched.id); if (!routine) return;
    const started = this.now(), nominal = this.nominal.get(routine.id) || started;
    const run = { routineId: routine.id, runId: randomUUID(), scope: `job:${routine.id}`, threadId: this.owner(routine).owner?.id, step: 0, grants: new Set(), active: true, tokens: 0, audit: [], status: 'ok' };
    this.runs.set(routine.id, run);
    const header = `[Scheduled run: ${JSON.stringify(routine.name)} · run #${routine.runs + 1} · nominal ${nominal.toISOString()} · ${this.timeZone} · actual ${started.toISOString()} · ${Math.max(0, Math.floor((started - nominal) / MINUTE_MS))}m late · attempt 1]`;
    const scope = this.engine.browserManager.createScope(run.scope, { profile: path.join(this.profileDirectory, routine.id), mode: routine.allow.mode, headless: routine.headless, independentPreview: true });
    const config = { ...this.engine.config, agentName: this.owner(routine).owner?.name || this.engine.config.agentName, backgroundJob: true, backgroundExecutionPolicy: routine.executionPolicy, systemExtra: [this.owner(routine).owner?.persona || '', ...(routine.kind === 'heartbeat' ? [this.engine.config.briefingPrompt || '', routine.lastNotifiedSummary ? `Previous useful heartbeat update: ${routine.lastNotifiedSummary}` : ''] : [])].filter(Boolean).join('\n'), autoApprove: true, memoryConsolidation: false };
    let timer, activeSince = Date.now(), elapsed = 0, summary = '', proof = null, worker, failure, rejectRun;
    run.elapsed = () => elapsed + (activeSince === null ? 0 : Date.now() - activeSince);
    run.pauseTimer = () => { elapsed = run.elapsed(); activeSince = null; clearTimeout(timer); };
    run.resumeTimer = () => {
      if (!run.active) return;
      activeSince = Date.now(); clearTimeout(timer);
      const current = this.store.load().findRoutine(routine.id) || routine;
      if (current.executionPolicy === JOB_EXECUTION_COMPLETE) return;
      const budgetRemaining = (current.budget.maxMinutesPerDay - current.spend.minutes) * MINUTE_MS - elapsed;
      const timeoutRemaining = routine.timeoutMs - elapsed, budgetFirst = budgetRemaining <= timeoutRemaining;
      timer = setTimeout(() => run.fail(budgetFirst ? jobError('Daily minutes budget reached', 'stopped-budget') : jobError('Job execution timed out; no retry was made.', 'timeout')), Math.max(0, Math.min(budgetRemaining, timeoutRemaining)));
    };
    run.fail = error => { if (failure) return; failure = error; worker?.cancel(); scope.cancel(); rejectRun?.(error); };
    const limited = new Promise((_, reject) => { rejectRun = reject; }); limited.catch(() => {});
    run.resumeTimer();
    this.store.updateRoutine(routine.id, { activeRunId: run.runId });
    this.engine.emit({ type: 'routine-run-start', routineId: routine.id, threadId: run.threadId, runId: run.runId, scope: run.scope }); this.changed();
    try {
      if (routine.allow.mode !== 'isolated') throw jobError('Background jobs use isolated Chromium. Change this job browser in its settings before running.', 'skipped-needs-foreground');
      const leg = this.budgetLeg(routine, run); if (leg) throw jobError(`Daily ${leg} budget reached`, 'stopped-budget');
      worker = new this.engine.AgentClass({ client: this.engine.client, tool: this.engine.tool, mcp: this.engine.mcp, config,
        ...this.engine.contextForJob?.(routine),
        browserManager: scope, browserThreadId: run.scope, skillsEnabled: false, deferTools: false,
        allowedTools: JOB_TOOLS, toolContext: { backgroundJob: true,
          requireForeground: reason => run.fail(jobError(reason, 'skipped-needs-foreground')),
          onBrowserError: error => { const notice = browserNotice(error); run.audit.push({ error: notice.kind, message: notice.message, at: this.now().toISOString() }); if (error.name === 'BrowserReferenceError') run.referenceRecovery = true; else run.fail(error.jobStatus ? error : jobError(FAILURE_TEXT)); },
          authorizeBrowser: async (args, context) => { try { return await this.authorize(run, args, context); } catch (error) { run.fail(error); throw error; } },
          authorizeNavigation: async url => { try { return await this.authorize(run, { action: 'open', url }, { url, mode: routine.allow.mode }); } catch (error) { run.fail(error); throw error; } },
          authorizeRequest: async ({ url, method }) => { try { return await this.authorize(run, { action: ['GET', 'HEAD', 'OPTIONS'].includes(method) ? 'read' : 'act', op: method }, { url, mode: routine.allow.mode }); } catch (error) { run.fail(error); throw error; } },
        }, confirm: async () => false, print: () => {}, write: () => {} });
      worker.model = this.engine.teammates.find(routine.threadId)?.model || this.engine.model;
      // Desktop availability is separate from permission; runtime policy asks
      // for login permission before the credential service reads the vault.
      worker.browserCredentialAllowed = true;
      const previous = routine.lastSuccessfulResult || (routine.lastReceipt?.status === 'ok' ? { text: routine.lastReceipt.text, at: routine.lastReceipt.at } : null);
      const priorContext = previous ? `\n[Previous successful result at ${previous.at}; historical context, never a substitute for a fresh observation]\n${previous.text}\n` : '\n[No previous successful result is recorded for this task.]\n';
      summary = await Promise.race([worker.send(`${header}${priorContext}\n${routine.prompt}`, {
        onToolCall: call => {
          if (call.function.name !== 'browser') return;
          let args; try { args = JSON.parse(call.function.arguments || '{}'); } catch { args = {}; }
          const step = browserDescription(args); run.audit.push({ step: ++run.step, tool: 'browser', detail: step, at: this.now().toISOString() });
          this.engine.emit({ type: 'routine-run-step', routineId: routine.id, threadId: run.threadId, runId: run.runId, step: run.step, detail: step });
        },
        onToolResult: (call, result) => {
          if (/(?:^|\n)(?:\d+\. )?Error(?: while running|:)/i.test(String(result))) { run.audit.push({ tool: call.function.name, error: FAILURE_TEXT, at: this.now().toISOString() }); if (!run.referenceRecovery) run.fail(jobError(FAILURE_TEXT)); }
          run.referenceRecovery = false;
          const current = this.store.load().findRoutine(routine.id);
          const exceeded = current && this.budgetLeg(current, run); if (exceeded) run.fail(jobError(`Daily ${exceeded} budget reached`, 'stopped-budget'));
        },
        onUsage: usage => { run.tokens += Number(usage.total_tokens) || (Number(usage.prompt_tokens) || 0) + (Number(usage.completion_tokens) || 0); const current = this.store.load().findRoutine(routine.id); const leg = current && this.budgetLeg(current, run); if (leg) run.fail(jobError(`Daily ${leg} budget reached`, 'stopped-budget')); },
      }), limited]);
      if (failure) throw failure;
      if (worker.terminationReason) throw jobError(INCOMPLETE_JOB_TEXT);
      const exceeded = this.budgetLeg(this.store.load().findRoutine(routine.id), run); if (exceeded) throw jobError(`Daily ${exceeded} budget reached`, 'stopped-budget');
      summary = String(summary || 'Job finished without a summary.').slice(0, JOB_SUMMARY_MAX_CHARS);
      if (routine.kind === 'heartbeat' && summary.trim() === HEARTBEAT_QUIET) { run.status = 'quiet'; summary = ''; }
    } catch (error) { run.status = error.jobStatus || 'error'; summary = error.jobStatus ? error.message : 'Job failed; no automatic retry was made. Review the last browser proof.'; }
    finally {
      run.active = false; run.pauseTimer();
      if (run.pendingRequest) this.respondApproval(run.pendingRequest, 'no');
      try {
        const view = await scope.view({ automation: true }); const tab = view.tabs?.find(item => item.active) || view.tabs?.[0];
        proof = { url: proofUrl(tab?.url), screenshot: typeof view.screenshot === 'string' && Buffer.byteLength(view.screenshot) <= JOB_PROOF_MAX_BYTES ? view.screenshot : null };
      } catch {}
      try { await this.engine.browserManager.closeScope(run.scope); }
      catch { run.status = 'error'; summary = 'Browser cleanup failed. Execution stopped; review the last proof before running again.'; }
      const current = this.store.load().findRoutine(routine.id);
      if (current) {
        if (routine.enabled && !current.enabled && run.status === 'ok') run.status = 'disabled-mid-run';
        const budget = run.status === 'stopped-budget';
        this.store.updateRoutine(routine.id, { activeRunId: null, pendingApproval: null, lastRun: started.toISOString(), lastStatus: run.status, lastSummary: summary, runs: current.runs + 1,
          spend: { day: dayAt(this.now(), this.timeZone), runs: current.spend.runs + 1, tokens: current.spend.tokens + run.tokens, minutes: current.spend.minutes + elapsed / MINUTE_MS },
          ...(routine.kind === 'heartbeat' && run.status === 'ok' ? { lastNotifiedSummary: summary } : {}),
          ...(run.status === 'ok' ? { lastSuccessfulResult: { text: summary, at: this.now().toISOString() } } : {}),
          ...(budget ? { enabled: false, pausedReason: 'budget' } : {}) });
      }
      const owner = this.owner(routine);
      const receipt = { runId: run.runId, routineId: routine.id, name: routine.name, threadId: owner.owner?.id || null, ownerMissing: owner.ownerMissing, status: run.status,
        templateId: routine.templateId, channel: routine.channel,
        text: `${summary}${started - nominal >= MINUTE_MS ? ` Ran ${Math.floor((started - nominal) / MINUTE_MS)}m late.` : ''}`, proof, at: this.now().toISOString(), nominalAt: nominal.toISOString(), delivered: run.status === 'quiet' };
      this.writeRun(run, { ...receipt, header, audit: run.audit, tokens: run.tokens, activeMs: elapsed });
      this.store.updateRoutine(routine.id, { lastReceipt: receipt });
      if (run.status !== 'quiet') await this.deliver(receipt);
      this.runs.delete(routine.id); this.engine.emit({ type: 'routine-run-end', routineId: routine.id, threadId: receipt.threadId, runId: run.runId, status: run.status });
      if (!isLogOnlyTemplate(routine) && !['ok', 'quiet', 'disabled-mid-run'].includes(run.status)) this.engine.emit({ type: 'routine-failed', ...receipt });
      this.changed(); this.prune(routine.id);
    }
  }
  writeRun(run, data) { fs.mkdirSync(this.directory, { recursive: true }); writeTextFile(path.join(this.directory, `${run.routineId}-${run.runId}.json`), JSON.stringify(this.transform(data), null, 2), '\n'); }
  async deliver(receipt) {
    const routine = this.store.load().findRoutine(receipt.routineId);
    if (isLogOnlyTemplate(receipt) || isLogOnlyTemplate(routine)) {
      const file = path.join(this.directory, `${receipt.routineId}-${receipt.runId}.json`);
      const saved = JSON.parse(fs.readFileSync(file, 'utf8'));
      this.writeRun(receipt, { ...saved, delivered: true });
      if (routine?.lastReceipt?.runId === receipt.runId) this.store.updateRoutine(routine.id, { lastReceipt: { ...receipt, delivered: true } });
      return;
    }
    const owner = this.owner(routine || receipt);
    receipt = { ...receipt, threadId: owner.owner?.id || null, ownerMissing: owner.ownerMissing };
    try {
      if (receipt.threadId && await this.engine.deliverRoutine(receipt)) {
        const file = path.join(this.directory, `${receipt.routineId}-${receipt.runId}.json`);
        const saved = JSON.parse(fs.readFileSync(file, 'utf8')); this.writeRun(receipt, { ...saved, ...receipt, delivered: true });
        this.store.updateRoutine(receipt.routineId, { lastReceipt: { ...receipt, delivered: true } });
      }
    } catch { this.engine.emit({ type: 'routine-queued', routineId: receipt.routineId, threadId: receipt.threadId, runId: receipt.runId }); }
  }
  async retryDeliveries() {
    if (!fs.existsSync(this.directory)) return;
    for (const name of fs.readdirSync(this.directory).filter(file => file.endsWith('.json'))) {
      try { const receipt = JSON.parse(fs.readFileSync(path.join(this.directory, name), 'utf8')); if (!receipt.delivered && receipt.runId) await this.deliver(receipt); } catch {}
    }
  }
  prune(id) {
    const files = fs.readdirSync(this.directory).filter(name => name.startsWith(`${id}-`) && name.endsWith('.json'))
      .map(name => ({ name, data: JSON.parse(fs.readFileSync(path.join(this.directory, name), 'utf8')) }))
      .filter(file => file.data.delivered).sort((a, b) => b.data.at.localeCompare(a.data.at));
    for (const file of files.slice(JOB_HISTORY_KEEP)) fs.unlinkSync(path.join(this.directory, file.name));
  }
}
