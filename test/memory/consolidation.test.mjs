import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-consolidate-'));
process.env.CONFIG_DIR = dir;
test.after(() => fs.rmSync(dir, { recursive: true, force: true }));
const { recordTurn, saveSession } = await import('../../src/core/sessions.mjs');
const { MemoryConsolidator } = await import('../../src/memory/consolidate.mjs');
const { ProfileStore } = await import('../../src/memory/profile.mjs');
const { ProjectStore } = await import('../../src/memory/projects.mjs');
const { Daemon } = await import('../../src/automation/daemon.mjs');
const { RoutineStore } = await import('../../src/automation/routines.mjs');
const { Agent } = await import('../../src/core/agent.mjs');

let seq = 0;
function fixture() {
  const root = path.join(dir, String(++seq));
  fs.mkdirSync(root);
  const sessionsDir = path.join(root, 'sessions'), journalDir = path.join(sessionsDir, 'journal');
  const profileFile = path.join(root, 'profile.json'), projectsFile = path.join(root, 'projects.json'), indexFile = path.join(root, 'index.json');
  const projects = new ProjectStore(projectsFile).load();
  const project = projects.add({ name: 'Atlas' });
  const at = '2026-09-20T14:00:00Z';
  const source = recordTurn({ text: 'I prefer concise replies. We chose SQLite. Need to add backups.', reply: 'Agreed.', projectId: project.id, sessionId: 's1', at }, { journalDir, timeZone: 'UTC' });
  return { root, sessionsDir, journalDir, profileFile, projectsFile, indexFile, projects, project, source, config: { timeZone: 'UTC', memoryConsolidationHour: 3, memoryBatchSize: 4 }, now: () => new Date('2026-09-21T04:00:00Z') };
}

test('model extracts durable facts and project work; replay and restart are idempotent', async () => {
  const f = fixture();
  let calls = 0;
  const extract = async prompt => {
    calls++;
    assert.match(prompt, /I prefer concise replies/);
    return JSON.stringify({ summary: 'Selected SQLite and planned backups.', personal: [{ text: 'Prefers concise replies', kind: 'style', evidence: 'I prefer concise replies.', always: true }], project: [{ action: 'decide', text: 'Use SQLite', evidence: 'We chose SQLite.' }, { action: 'todo', text: 'Add backups', evidence: 'Need to add backups.' }] });
  };
  assert.equal((await new MemoryConsolidator({ ...f, extract }).run()).processed, 1);
  const profile = new ProfileStore(f.profileFile).load();
  assert.equal(profile.facts[0].text, 'Prefers concise replies');
  assert.equal(profile.facts[0].always, false, 'background extraction never pins facts');
  assert.ok(profile.facts[0].source);
  const p = new ProjectStore(f.projectsFile).load().find(f.project.id);
  assert.equal(p.decisions.length, 1);
  assert.equal(p.todos.length, 1);
  assert.equal((await new MemoryConsolidator({ ...f, extract }).run()).processed, 0);
  assert.equal(calls, 1);
  assert.equal(JSON.parse(fs.readFileSync(f.indexFile)).entries[0].summary, 'Selected SQLite and planned backups.');
});

test('invalid JSON or unsupported evidence never writes memory or marks transcript processed', async () => {
  const f = fixture();
  const c = new MemoryConsolidator({ ...f, extract: async () => 'not JSON' });
  await assert.rejects(c.run(), /JSON/);
  c.extract = async () => JSON.stringify({ summary: 'bad', personal: [{ text: 'Lives in Paris', evidence: 'I live in Paris' }], project: [] });
  await assert.rejects(c.run(), /evidence/);
  assert.equal(new ProfileStore(f.profileFile).load().facts.length, 0);
  c.extract = async () => JSON.stringify({ summary: 'No durable changes.', personal: [], project: [] });
  assert.equal((await c.run()).processed, 1);
});

test('today is excluded and large transcripts are chunked within per-run model budgets', async () => {
  const f = fixture();
  recordTurn({ text: 'today only', reply: 'ok', at: '2026-09-21T00:00:00Z' }, f);
  recordTurn({ text: 'long history '.repeat(1200), reply: 'ok', at: '2026-09-20T15:00:00Z' }, f);
  let calls = 0;
  const c = new MemoryConsolidator({ ...f, config: { ...f.config, memoryBatchSize: 2, memoryChunkChars: 2000 }, extract: async prompt => {
    calls++;
    assert.doesNotMatch(prompt, /today only/);
    assert.ok(prompt.length < 12000);
    return JSON.stringify({ summary: 'Processed part.', personal: [], project: [] });
  } });
  assert.equal((await c.run()).processed, 2);
  assert.equal(calls, 2);
  assert.equal((await c.run()).processed, 2);
});

test('legacy saved sessions are read without attributing them to the currently active project', async () => {
  const f = fixture();
  fs.rmSync(f.source);
  fs.writeFileSync(path.join(f.sessionsDir, 'autosave.json'), JSON.stringify({ savedAt: '2026-09-20T12:00:00Z', messages: [{ role: 'system', content: 'NOT TRANSCRIPT' }, { role: 'user', content: 'I like short answers' }] }));
  const c = new MemoryConsolidator({ ...f, extract: async prompt => {
    assert.doesNotMatch(prompt, /NOT TRANSCRIPT/);
    return JSON.stringify({ summary: 'Preferred short answers', personal: [], project: [{ action: 'note', text: 'short answers', evidence: 'I like short answers' }] });
  } });
  await assert.rejects(c.run(), /project/);
});

test('daemon consolidation does not block inbox polling or consume a chat concurrency slot', async () => {
  const f = fixture();
  let finish, started = false, polls = 0;
  const work = new Promise(r => { finish = r; });
  const daemon = new Daemon({ store: new RoutineStore(path.join(f.root, 'state.json')).load(), config: {}, client: {}, runPrompt: async () => '', deliver: async () => {},
    consolidator: { due: () => true, run: () => { started = true; return work; } },
    bot: { enabled: true, poll: async () => { polls++; return { jobs: [], offset: 1 }; } },
  });
  await daemon.tickOnce();
  assert.equal(started, true);
  assert.equal(polls, 1);
  assert.equal(daemon.active, 0);
  await daemon.tickOnce();
  assert.equal(polls, 2);
  finish({ processed: 1 });
  await daemon.drain();
});

test('interactive journal captures user and final assistant without an extra model round trip', async () => {
  const captured = [];
  const agent = new Agent({ client: {}, config: { tools: false, contextWindow: 32768 }, journal: turn => captured.push(turn), project: 'Atlas', projectId: 'atlas' });
  let calls = 0;
  agent.streamTurn = async () => { calls++; return { content: 'Remembered.', toolCalls: [] }; };
  await agent.send('I use PowerShell');
  assert.equal(calls, 1);
  assert.equal(captured[0].text, 'I use PowerShell');
  assert.equal(captured[0].reply, 'Remembered.');
  assert.equal(captured[0].projectId, 'atlas');
});

test('a newer explicit correction and forgetting win over older pending consolidation', async () => {
  const f = fixture();
  const s = new ProfileStore(f.profileFile).load();
  const fact = s.add({ text: 'Prefers tea', source: { at: '2026-09-19T00:00:00Z' } });
  s.update(fact.id, { text: 'Prefers water' });
  const c = new MemoryConsolidator({ ...f, extract: async () => '' });
  const entry = { id: 'older', at: '2026-09-20T00:00:00Z', plan: { personal: [{ id: fact.id, text: 'Prefers coffee' }], project: [] } };
  c.apply(entry);
  assert.equal(s.load().facts[0].text, 'Prefers water');
  s.forget(fact.id);
  entry.plan.personal = [{ text: 'Prefers tea' }];
  c.apply(entry);
  assert.equal(s.load().facts.length, 0, 'forgotten facts must not be learned again from old transcripts');
});

test('memory writes survive a staged-plan restart without duplicate project todos', async () => {
  const f = fixture();
  const c = new MemoryConsolidator({ ...f, extract: async () => JSON.stringify({ summary: 'Planned backups', personal: [], project: [{ action: 'todo', text: 'Add backups', evidence: 'Need to add backups.' }] }) });
  const apply = c.apply.bind(c);
  c.apply = entry => { apply(entry); throw new Error('simulated crash after writes'); };
  await assert.rejects(c.run(), /simulated crash/);
  const restarted = new MemoryConsolidator({ ...f, extract: async () => { throw Error('must replay staged plan without another model call'); } });
  await restarted.run();
  assert.equal(new ProjectStore(f.projectsFile).load().find(f.project.id).todos.length, 1);
});

test('switching to journaled autosaves preserves an older unsummarized transcript', () => {
  const f = fixture();
  const file = path.join(f.sessionsDir, 'autosave.json');
  const old = { savedAt: '2026-09-19T12:00:00Z', messages: [{ role: 'user', content: 'old unsummarized conversation' }] };
  fs.writeFileSync(file, JSON.stringify(old));
  saveSession(file, { journaled: true, savedAt: '2026-09-21T12:00:00Z', messages: [] });
  const archived = fs.readdirSync(f.sessionsDir).find(name => name.startsWith('legacy-'));
  assert.ok(archived);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(f.sessionsDir, archived))), old);
});

test('project switches during a turn update tool context and avoid misattributing a mixed-project journal', async () => {
  const { PROJECTS_FILE } = await import('../../src/core/config.mjs');
  const s = new ProjectStore(PROJECTS_FILE).load();
  const a = s.add({ name: 'First project' }), b = s.add({ name: 'Second project' });
  s.use(a.id);
  const captured = [];
  const agent = new Agent({ client: {}, config: { tools: true }, project: s.promptBlock(), projectId: a.id, journal: turn => captured.push(turn) });
  let step = 0;
  agent.streamTurn = async () => ++step === 1 ? { content: '', toolCalls: [{ id: 'switch', function: { name: 'project', arguments: JSON.stringify({ action: 'use', name: b.id }) } }] } : { content: 'Switched.', toolCalls: [] };
  await agent.send('Switch to the second project');
  assert.equal(agent.projectId, b.id);
  assert.equal(captured[0].projectId, null);
});

test('updating a project does not adopt another session\'s active project', async () => {
  const { PROJECTS_FILE } = await import('../../src/core/config.mjs');
  const s = new ProjectStore(PROJECTS_FILE).load();
  const a = s.add({ name: 'Local project' }), b = s.add({ name: 'Other session project' });
  s.use(b.id);
  const agent = new Agent({ client: {}, config: { tools: true }, project: 'Local project', projectId: a.id });
  await agent.runToolCall({ id: 'update', function: { name: 'project', arguments: JSON.stringify({ action: 'update', name: a.id, summary: 'updated summary' }) } });
  assert.equal(agent.projectId, a.id);
  assert.match(agent.messages[0].content, /updated summary/);
});

test('disabling consolidation during a session stops automatic journaling immediately', async () => {
  const turns = [];
  const agent = new Agent({ client: {}, config: { tools: false }, journal: turn => turns.push(turn) });
  agent.streamTurn = async () => ({ content: 'ok', toolCalls: [] });
  agent.config = { tools: false, memoryConsolidation: false };
  await agent.send('Do not journal this turn');
  assert.equal(turns.length, 0);
  assert.equal(agent.journalComplete, false);
});
