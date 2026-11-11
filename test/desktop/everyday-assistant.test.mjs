import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'everyday-assistant-'));
process.env.CONFIG_DIR = path.join(directory, 'defaults');
test.after(() => fs.rmSync(directory, { recursive: true, force: true }));
const { DesktopEngine } = await import('../../desktop/electron/engine.mjs');
const { Agent } = await import('../../src/core/agent.mjs');
const actions = await import('../../desktop/shared/assistant.mjs').catch(() => ({}));
const dispatcher = await import('../../desktop/electron/assistant-actions.mjs').catch(() => ({}));

async function fixture(t) {
  const profile = fs.mkdtempSync(path.join(directory, 'host-')), events = [];
  const options = { teammateFile: path.join(profile, 'teammates.json'), settingsFile: path.join(profile, 'settings.json'),
    sessionsDir: path.join(profile, 'sessions'), projectsFile: path.join(profile, 'projects.json'),
    channelsFile: path.join(profile, 'channels.json'), credentialFile: path.join(profile, 'credentials.json'),
    composioFile: path.join(profile, 'composio.json'), composioGrantsFile: path.join(profile, 'grants.json'),
    config: { provider: 'kilo', model: 'fixture-model', tools: true, autoApprove: true, contextWindow: 131072, maxTokens: 1000, memoryRecallChars: 0, memoryConsolidation: false },
    bootstrap: async () => ({ client: {}, models: [{ id: 'fixture-model' }], model: 'fixture-model', provider: { name: 'kilo' } }),
    mcp: { reconcile: async () => {}, summaries: () => [], specs: () => [], alwaysOnIds: () => [], closeAll: async () => {} },
    AgentClass: Agent, emit: event => events.push(event) };
  const engine = new DesktopEngine(options); await engine.init();
  t.after(() => engine.close());
  return { engine, options, events, profile, id: engine.listTeammates()[0].id };
}

test('desktop send creates a durable task and the Today action returns real local work without asking a model', async t => {
  const h = await fixture(t), agent = h.engine.agentFor(h.id); let calls = 0;
  agent.streamTurn = async () => { calls++; return { content: 'Here is the requested plan.', toolCalls: [] }; };
  await h.engine.send(h.id, 'Plan my next steps.'); await h.engine.waitForTurn(h.id);
  assert.ok(actions.ASSISTANT_ACTIONS?.today, 'Today has an IPC contract');
  const today = await dispatcher.runAssistantAction({ engine: h.engine, action: actions.ASSISTANT_ACTIONS.today });
  assert.equal(calls, 1, 'opening Today consumes no extra generation');
  assert.equal(today.recent[0].goal, 'Plan my next steps.');
  assert.equal(today.recent[0].ownerId, h.id);
  assert.equal(today.externalSources.status, 'not_checked');
  assert.deepEqual(today.memories, []);
  assert.deepEqual(today.routines, []);
  assert.match(today.briefing, /not been checked/i);
  assert.ok(h.events.some(event => event.type === 'assistant-task-changed'));
  const restored = new DesktopEngine(h.options); await restored.init(); t.after(() => restored.close());
  assert.equal(restored.assistant().tasks.get(today.recent[0].id).reply, 'Here is the requested plan.');
});

test('a visible recovery action preserves the original goal and rejects another conversation', async t => {
  const h = await fixture(t), service = h.engine.assistant();
  const task = service.tasks.create({ ownerId: h.id, goal: 'Finish the saved plan.' });
  service.tasks.start(task.id); service.tasks.finish(task.id, { status: 'interrupted' });
  const agent = h.engine.agentFor(h.id);
  agent.streamTurn = async () => { assert.ok(agent.messages.some(message => String(message.content).includes(task.goal))); return { content: 'Plan finished.', toolCalls: [] }; };
  await assert.rejects(dispatcher.runAssistantAction({ engine: h.engine, action: actions.ASSISTANT_ACTIONS.resume, payload: { id: 'other-conversation', taskId: task.id } }), /conversation|teammate/i);
  await dispatcher.runAssistantAction({ engine: h.engine, action: actions.ASSISTANT_ACTIONS.resume, payload: { id: h.id, taskId: task.id } });
  await h.engine.waitForTurn(h.id);
  assert.equal(service.tasks.get(task.id).status, 'completed'); assert.equal(service.tasks.get(task.id).attempt, 2);
});

test('memory edits and forgetting use the same personal profile supplied to typed and voice workers', async t => {
  const h = await fixture(t), service = h.engine.assistant();
  const fact = await dispatcher.runAssistantAction({ engine: h.engine, action: actions.ASSISTANT_ACTIONS.memorySave,
    payload: { text: 'My current goal is to learn guitar.', kind: 'goal', always: true } });
  const agent = h.engine.agentFor(h.id);
  assert.equal(agent.toolContext.profileFile, service.profileFile);
  assert.equal(h.engine.captureVoiceContext(h.id).toolContext.profileFile, service.profileFile);
  assert.equal(h.engine.captureVoiceContext(h.id).toolContext.assistantOwnerId, h.id);
  const edited = await dispatcher.runAssistantAction({ engine: h.engine, action: actions.ASSISTANT_ACTIONS.memorySave,
    payload: { id: fact.id, text: 'My current goal is to learn piano.', expectedUpdatedAt: fact.updatedAt } });
  assert.match(edited.text, /piano/); assert.ok(edited.source);
  let found = await dispatcher.runAssistantAction({ engine: h.engine, action: actions.ASSISTANT_ACTIONS.memoryList, payload: { query: 'piano' } });
  assert.equal(found.length, 1);
  await dispatcher.runAssistantAction({ engine: h.engine, action: actions.ASSISTANT_ACTIONS.memoryForget, payload: { id: fact.id } });
  found = await dispatcher.runAssistantAction({ engine: h.engine, action: actions.ASSISTANT_ACTIONS.memoryList });
  assert.equal(found.length, 0);
});

test('the next typed and voice requests read edited knowledge, with no stale deleted fact', async t => {
  const h = await fixture(t), service = h.engine.assistant();
  h.engine.config.memoryRecallChars = 1600; h.engine.config.embeddings = false;
  const fact = service.memorySave({ text: 'My personal goal is to learn piano.', kind: 'goal' });
  const parent = h.engine.agentFor(h.id);
  parent.streamTurn = async () => { assert.match(parent.memoryContext?.result || '', /learn piano/); return { content: 'Your goal is to learn piano.', toolCalls: [] }; };
  await h.engine.send(h.id, 'What is my personal goal?'); await h.engine.waitForTurn(h.id);
  service.memorySave({ id: fact.id, text: 'My personal goal is to learn violin.', kind: 'goal' });
  const { runVoiceWorker } = await import('../../src/core/voice-worker.mjs');
  class KnowledgeAgent extends Agent { async streamTurn() {
    assert.match(this.memoryContext?.result || '', /learn violin/);
    assert.doesNotMatch(this.memoryContext?.result || '', /learn piano/);
    return { content: 'Your current goal is to learn violin.', toolCalls: [] };
  } }
  const entry = { id: 'voice-knowledge', ownerId: h.id, transcript: 'What is my personal goal?', context: h.engine.captureVoiceContext(h.id) };
  await runVoiceWorker(entry, { observer: {}, signal: new AbortController().signal,
    controlTool: { name: 'voice_jobs', parameters: { type: 'object' }, run: () => '[]', readOnly: true, needsApproval: false } },
  { AgentClass: KnowledgeAgent, onWorker: worker => { worker.toolContext.responsePolicy = null; } });
});

test('project context can be corrected or forgotten by its current reference and Today lists actual commitments', async t => {
  const h = await fixture(t), project = h.engine.createProject({ name: 'A personal project' });
  h.engine.assignProject(h.id, project.id);
  h.engine.addProjectTodo(project.id, 'Finish the current draft.');
  h.engine.addProjectRecord(project.id, 'decision', 'Use the old plan.');
  const original = h.engine.listProjects().find(item => item.id === project.id).decisions[0];
  const agent = h.engine.agentFor(h.id);
  await dispatcher.runAssistantAction({ engine: h.engine, action: actions.ASSISTANT_ACTIONS.projectSave,
    payload: { projectId: project.id, kind: 'decision', ref: original.ref, text: 'Use the corrected plan.' } });
  assert.match(agent.project, /corrected plan/); assert.doesNotMatch(agent.project, /old plan/);
  await assert.rejects(dispatcher.runAssistantAction({ engine: h.engine, action: actions.ASSISTANT_ACTIONS.projectSave,
    payload: { projectId: project.id, kind: 'decision', ref: original.ref, text: 'A stale overwrite.' } }), /changed|found/i);
  const current = h.engine.listProjects().find(item => item.id === project.id).decisions[0];
  assert.ok(current.source); assert.ok(current.previousSource);
  const today = h.engine.assistant().today(); assert.equal(today.commitments[0].text, 'Finish the current draft.');
  await dispatcher.runAssistantAction({ engine: h.engine, action: actions.ASSISTANT_ACTIONS.projectForget,
    payload: { projectId: project.id, kind: 'decision', ref: current.ref } });
  assert.doesNotMatch(h.engine.captureVoiceContext(h.id).project, /corrected plan|old plan/);
});

test('teach once runs parameterized work through normal approvals and scheduling stays a separate disabled draft', async t => {
  const h = await fixture(t), agent = h.engine.agentFor(h.id); agent.setProject('', null, h.profile);
  let round = 0;
  agent.streamTurn = async () => ++round === 1 ? { content: '', toolCalls: [{ id: 'source-note', function: { name: 'write_file', arguments: JSON.stringify({ path: 'source-note.txt', content: 'Original successful note.' }) } }] } : { content: 'The source note is saved.', toolCalls: [] };
  await h.engine.send(h.id, 'Save the source note.'); await h.engine.waitForTurn(h.id);
  const source = h.engine.assistant().tasks.list({ ownerId: h.id })[0];
  const routine = await dispatcher.runAssistantAction({ engine: h.engine, action: actions.ASSISTANT_ACTIONS.routineSave,
    payload: { ownerId: h.id, sourceTaskId: source.id, name: 'Project note', template: 'Save {{topic}} to {{filename}}.', parameters: [{ name: 'filename', defaultValue: 'routine-note.txt' }] } });
  assert.equal(h.engine.schedule().list().length, 0);
  agent.autoApprove = false; let approve = false, approvals = 0;
  const off = h.engine.onEvent(event => { if (event.type === 'approval-request') { approvals++; h.engine.respondApproval(event.requestId, approve ? 'yes' : 'no'); } }); t.after(off);
  for (const allowed of [false, true]) {
    approve = allowed; round = 0;
    agent.streamTurn = async () => {
      if (++round === 1) {
        assert.ok(agent.messages.some(message => String(message.content).includes('Save Routines are useful. to routine-note.txt.')));
        return { content: '', toolCalls: [{ id: `routine-save-${allowed}`, function: { name: 'write_file', arguments: JSON.stringify({ path: 'routine-note.txt', content: 'Routines are useful.' }) } }] };
      }
      return { content: allowed ? 'Saved the routine note.' : 'Permission was denied.', toolCalls: [] };
    };
    await dispatcher.runAssistantAction({ engine: h.engine, action: actions.ASSISTANT_ACTIONS.routineRun, payload: { ownerId: h.id, routineId: routine.id, values: { topic: 'Routines are useful.' } } });
    await h.engine.waitForTurn(h.id);
    assert.equal(fs.existsSync(path.join(h.profile, 'routine-note.txt')), allowed);
  }
  assert.equal(approvals, 2);
  const run = h.engine.assistant().tasks.list({ ownerId: h.id }).find(item => item.routineId === routine.id && item.status === 'completed');
  assert.equal(run.sourceTaskId, source.id); assert.match(run.goal, /^Save Routines are useful/);
  const scheduled = await dispatcher.runAssistantAction({ engine: h.engine, action: actions.ASSISTANT_ACTIONS.routineSchedule,
    payload: { ownerId: h.id, routineId: routine.id, values: { topic: 'Routines are useful.' }, cron: 'weekdays 09:00' } });
  assert.equal(scheduled.enabled, false); assert.equal(scheduled.draft, true);
});

test('opt-in daily briefing creates an editable paused draft and reads fresh local facts when executed', async t => {
  const h = await fixture(t);
  assert.ok(actions.ASSISTANT_ACTIONS.briefingSchedule);
  const job = await dispatcher.runAssistantAction({ engine: h.engine, action: actions.ASSISTANT_ACTIONS.briefingSchedule,
    payload: { ownerId: h.id, cron: 'daily 09:00' } });
  assert.equal(job.enabled, false); assert.equal(job.draft, true); assert.equal(job.assistantBriefing, true);
  const project = h.engine.createProject({ name: 'Daily priorities' });
  h.engine.addProjectTodo(project.id, 'Fresh commitment created after scheduling.');
  let requests = 0;
  h.engine.AgentClass = class extends Agent { async streamTurn() {
    requests++; assert.match(this.config.systemExtra, /Fresh commitment created after scheduling/);
    assert.match(this.config.systemExtra, /not_checked/);
    return { content: 'Your fresh commitment is ready for review. Calendar and inbox were not checked.', toolCalls: [] };
  } };
  const scheduler = h.engine.schedule();
  scheduler.update(job.id, { prompt: 'Give a short local daily briefing.', enabled: true });
  await scheduler.execute(scheduler.list().find(item => item.id === job.id));
  const result = scheduler.list().find(item => item.id === job.id);
  assert.equal(requests, 1); assert.equal(result.lastStatus, 'ok');
  assert.match(result.lastReceipt.text, /fresh commitment/);
});
