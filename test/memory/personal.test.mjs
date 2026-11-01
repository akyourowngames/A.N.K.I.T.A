import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-personal-'));
process.env.CONFIG_DIR = dir;
test.after(() => fs.rmSync(dir, { recursive: true, force: true }));
const { ProfileStore } = await import('../../src/memory/profile.mjs');
const remember = await import('../../tools/personal/remember.mjs');
const recall = await import('../../tools/personal/recall.mjs');
const { Agent, buildSystemPrompt } = await import('../../src/core/agent.mjs');
const { ProjectStore } = await import('../../src/memory/projects.mjs');
const { PROFILE_FILE, PROJECTS_FILE, MEMORY_INDEX_FILE } = await import('../../src/core/config.mjs');
const { personalMemoryContext } = await import('../../src/memory/memory-context.mjs');

test('personal facts survive reload, update by stable id, deduplicate and forget', () => {
  const s = new ProfileStore(path.join(dir, 'isolated.json')).load();
  const a = s.add({ text: 'Use PowerShell', kind: 'style', always: true });
  assert.equal(s.add({ text: 'Use PowerShell' }).id, a.id);
  assert.equal(new ProfileStore(s.file).load().facts.length, 1);
  s.update(a.id, { text: 'Use fish', always: false });
  assert.equal(new ProfileStore(s.file).load().facts[0].text, 'Use fish');
  assert.equal(s.promptBlock(), '');
  assert.equal(s.forget(a.id).id, a.id);
  assert.equal(new ProfileStore(s.file).load().facts.length, 0);
});

test('prompt uses only explicit pins and bounds both lines and characters without truncating storage', () => {
  const s = new ProfileStore(path.join(dir, 'pins.json')).load();
  s.add({ text: 'secret unpinned fact' });
  for (let i = 0; i < 20; i++) s.add({ text: `${i}: ` + 'x\n'.repeat(500), always: true });
  const block = s.promptBlock();
  assert.equal(block.split('\n').length, 13);
  assert.ok(block.length < 2100);
  assert.doesNotMatch(block, /secret unpinned/);
  assert.ok(s.facts[1].text.length > 900);
  assert.match(buildSystemPrompt({}, '.', null, [], block), /Personal memory/);
});

test('tool list/update/forget roundtrip and prompt refresh do not call a model', async () => {
  const out = await remember.run({ action: 'add', text: 'Avoid em dashes', kind: 'style', always: true });
  assert.match(out, /Avoid em dashes/);
  const id = new ProfileStore(PROFILE_FILE).load().facts[0].id;
  const agent = new Agent({ client: {}, config: { tools: true } });
  assert.match(agent.messages[0].content, /Avoid em dashes/);
  await remember.run({ action: 'update', id, text: 'Prefer concise replies' });
  agent.refreshPrompt();
  assert.match(agent.messages[0].content, /Prefer concise replies/);
  assert.match(await remember.run({ action: 'list' }), /Prefer concise replies/);
  await remember.run({ action: 'forget', id });
  agent.refreshPrompt();
  assert.doesNotMatch(agent.messages[0].content, /Prefer concise replies/);
});

test('recall searches personal facts, project notes/decisions/todos and session summaries', async () => {
  await remember.run({ action: 'add', text: 'I enjoy lunar photography' });
  const s = new ProjectStore(PROJECTS_FILE).load();
  const p = s.add({ name: 'Observatory' });
  s.addNote(p.id, 'lunar lens arrives Friday');
  s.addDecision(p.id, 'lunar images use RAW');
  s.addTodo(p.id, 'calibrate lunar camera');
  fs.writeFileSync(MEMORY_INDEX_FILE, JSON.stringify({ entries: [{ id: 'session-one', summary: 'Discussed lunar equipment', at: '2026-09-20', projectId: p.id }] }));
  const result = JSON.parse(await recall.run({ query: 'lunar' }));
  assert.equal(result.total, 5);
  assert.deepEqual(new Set(result.results.map(r => r.type)), new Set(['personal', 'note', 'decision', 'todo', 'summary']));
  assert.equal(JSON.parse(await recall.run({ query: 'lunar', project: p.id })).total, 4);
  assert.equal(JSON.parse(await recall.run({ query: 'lunar', limit: 2 })).results.length, 2);
});

test('fresh agents can read and write memory in their first request without discovery', () => {
  const agent = new Agent({ client: {}, config: { tools: true } });
  const names = agent.currentSpecs().map(s => s.function.name);
  assert.ok(names.includes('remember'));
  assert.ok(names.includes('recall'));
  assert.equal(new Set(names).size, names.length);
});

test('a wording mismatch returns bounded candidates for the model instead of pretending nothing is remembered', async () => {
  const profileFile = path.join(dir, 'vocabulary.json');
  const s = new ProfileStore(profileFile).load();
  s.add({ text: 'Enjoys pottery', kind: 'preference' });
  s.add({ text: 'Loves hand-pulled noodles', kind: 'preference' });
  const result = JSON.parse(await recall.run({ query: 'dining favorites', project: 'personal', limit: 1 }, { profileFile }));
  assert.equal(result.matched, 0);
  assert.equal(result.mode, 'browse');
  assert.equal(result.total, 2);
  assert.equal(result.results.length, 1);
  assert.equal(result.nextOffset, 1);
  const second = JSON.parse(await recall.run({ query: 'dining favorites', project: 'personal', limit: 1, offset: 1 }, { profileFile }));
  assert.notEqual(result.results[0].id, second.results[0].id);
});

test('fresh-session memory availability metadata does not expose unpinned facts in the prompt', () => {
  const s = new ProfileStore(PROFILE_FILE).load();
  s.add({ text: 'Unique unpinned preference for the metadata regression' });
  const agent = new Agent({ client: {}, config: { tools: true } });
  assert.match(agent.messages[0].content, /Personal memory store: \d+ saved fact/);
  assert.doesNotMatch(agent.messages[0].content, /Unique unpinned preference/);
});

/* ------------------- dedup, conflicts, ageing, project recall -------------- */

const tempProfile = t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-mem-quality-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return { profileFile: path.join(dir, 'profile.json'), projectsFile: path.join(dir, 'projects.json'),
    memoryIndexFile: path.join(dir, 'summaries.json'), config: {} };
};

test('a near-duplicate is merged into one fact instead of stored twice', async t => {
  const ctx = tempProfile(t);
  await remember.run({ action: 'add', text: 'I use Postgres', kind: 'preference' }, ctx);
  const out = JSON.parse(await remember.run({ action: 'add', text: 'Database is Postgres', kind: 'preference' }, ctx));
  assert.ok(out.merged, 'the second statement was recognised as the same fact');
  const facts = new ProfileStore(ctx.profileFile).load().facts;
  assert.equal(facts.length, 1, 'one fact, not two');
  assert.equal(facts[0].text, 'Database is Postgres', 'the clearer wording wins');
});

test('a contradictory fact is stored and flagged, never overwritten', async t => {
  const ctx = tempProfile(t);
  const first = JSON.parse(await remember.run({ action: 'add', text: 'My meeting is at 3pm on Monday', kind: 'schedule' }, ctx));
  const second = JSON.parse(await remember.run({ action: 'add', text: 'My meeting is at 5pm on Monday', kind: 'schedule' }, ctx));
  assert.ok(second.conflict, 'the contradiction is reported back');
  assert.equal(second.conflict.id, first.fact.id);
  const facts = new ProfileStore(ctx.profileFile).load().facts;
  assert.equal(facts.length, 2, 'nothing is destroyed');
  assert.equal(facts[0].text, 'My meeting is at 3pm on Monday');
  assert.ok(facts[0].conflictsWith.includes(facts[1].id) && facts[1].conflictsWith.includes(facts[0].id), 'both sides are flagged');
});

test('an inferred fact from extraction is softer than one the user stated directly', async t => {
  const ctx = tempProfile(t);
  // A direct tool call is the user's own statement.
  const direct = JSON.parse(await remember.run({ action: 'add', text: 'Probably enjoys hiking', kind: 'preference' }, ctx));
  assert.equal(direct.fact.confidence, 1, 'a direct remember call is certain');
  // Extraction carries an evidence quote, which marks it as an inference.
  const inferred = JSON.parse(await remember.run({ action: 'add', text: 'Enjoys alpine trekking', kind: 'preference',
    source: { id: 's1', at: new Date().toISOString(), evidence: 'I went trekking last week' } }, ctx));
  assert.ok(inferred.fact.confidence < 1, 'an extracted guess is marked softer');
});

test('a fact not recalled for a long time is hidden by default and returned on request', async t => {
  const ctx = tempProfile(t);
  const s = new ProfileStore(ctx.profileFile).load();
  const old = s.add({ text: 'Uses an ancient laptop' });
  s.mutate(() => { s.facts.find(f => f.id === old.id).updatedAt = new Date(Date.now() - 400 * 86400000).toISOString(); });
  ctx.config = { memoryStaleDays: 90 };
  const hidden = JSON.parse(await recall.run({ query: 'ancient laptop', project: 'personal' }, ctx));
  assert.ok(!hidden.results.some(row => row.text === 'Uses an ancient laptop'), 'stale facts do not crowd recall');
  const shown = JSON.parse(await recall.run({ query: 'ancient laptop', project: 'personal', includeStale: true }, ctx));
  assert.ok(shown.results.some(row => row.text === 'Uses an ancient laptop'), 'an explicit ask still finds it');
});

test('recall records that a fact was used, in one batched write', async t => {
  const ctx = tempProfile(t);
  const s = new ProfileStore(ctx.profileFile).load();
  const fact = s.add({ text: 'Prefers dark themes' });
  await recall.run({ query: 'dark themes', project: 'personal' }, ctx);
  const after = new ProfileStore(ctx.profileFile).load().facts.find(f => f.id === fact.id);
  assert.equal(after.recallCount, 1);
  assert.ok(after.lastRecalledAt, 'the ageing clock is refreshed');
});

test('automatic context can surface project memory, not only personal facts', async t => {
  const ctx = tempProfile(t);
  const projects = new ProjectStore(ctx.projectsFile).load();
  const p = projects.add({ name: 'Observatory' });
  projects.addNote(p.id, 'lunar lens arrives Friday');
  await remember.run({ action: 'add', text: 'I enjoy lunar photography' }, ctx);
  const context = await personalMemoryContext('when does the lunar lens arrive?', { memoryRecallChars: 1600 }, ctx);
  assert.ok(context, 'automatic context exists');
  // Project notes used to be excluded from automatic recall entirely.
  assert.match(context.result, /lunar lens arrives Friday/, 'a project note is offered to the reply model');
});

test('older extraction never overwrites wording the user stated more recently', async t => {
  const ctx = tempProfile(t);
  const now = new Date().toISOString();
  // The user states it today, directly.
  await remember.run({ action: 'add', text: 'I use Postgres', kind: 'preference' }, ctx);
  // Consolidation of yesterday's transcript proposes a different wording.
  const yesterday = new Date(Date.now() - 86400000).toISOString();
  await remember.run({ action: 'add', text: 'Database is Postgres', kind: 'preference',
    source: { id: 'old', at: yesterday, evidence: 'we use postgres' } }, ctx);
  const facts = new ProfileStore(ctx.profileFile).load().facts;
  assert.equal(facts.length, 1, 'still one fact');
  assert.equal(facts[0].text, 'I use Postgres', 'the newer user wording survives');
  assert.ok(Date.parse(facts[0].updatedAt) <= Date.parse(now) + 5000);
});

test('a re-stated pinned fact stays pinned through a merge', async t => {
  const ctx = tempProfile(t);
  await remember.run({ action: 'add', text: 'Always answer in British English', kind: 'style', always: true }, ctx);
  await remember.run({ action: 'add', text: 'Always answer in British English please', kind: 'style' }, ctx);
  const facts = new ProfileStore(ctx.profileFile).load().facts;
  assert.equal(facts.length, 1);
  assert.equal(facts[0].always, true, 'a merge must not silently unpin an instruction');
});

test('forgetting a fact clears the conflict pointers that referenced it', async t => {
  const ctx = tempProfile(t);
  const a = JSON.parse(await remember.run({ action: 'add', text: 'My meeting is at 3pm on Monday', kind: 'schedule' }, ctx));
  await remember.run({ action: 'add', text: 'My meeting is at 5pm on Monday', kind: 'schedule' }, ctx);
  await remember.run({ action: 'forget', id: a.fact.id }, ctx);
  const facts = new ProfileStore(ctx.profileFile).load().facts;
  assert.equal(facts.length, 1);
  assert.deepEqual(facts[0].conflictsWith, [], 'no dangling conflict id survives');
});

test('only the rows actually returned have their recall clock refreshed', async t => {
  const ctx = tempProfile(t);
  const s = new ProfileStore(ctx.profileFile).load();
  for (let i = 0; i < 5; i++) s.add({ text: `note number ${i}` });
  await recall.run({ query: 'note', project: 'personal', limit: 2 }, ctx);
  const touched = new ProfileStore(ctx.profileFile).load().facts.filter(f => f.recallCount > 0).length;
  assert.ok(touched <= 2, `only the delivered page is credited, got ${touched}`);
});
