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
  const out = remember.run({ action: 'add', text: 'Avoid em dashes', kind: 'style', always: true });
  assert.match(out, /Avoid em dashes/);
  const id = new ProfileStore(PROFILE_FILE).load().facts[0].id;
  const agent = new Agent({ client: {}, config: { tools: true } });
  assert.match(agent.messages[0].content, /Avoid em dashes/);
  remember.run({ action: 'update', id, text: 'Prefer concise replies' });
  agent.refreshPrompt();
  assert.match(agent.messages[0].content, /Prefer concise replies/);
  assert.match(remember.run({ action: 'list' }), /Prefer concise replies/);
  remember.run({ action: 'forget', id });
  agent.refreshPrompt();
  assert.doesNotMatch(agent.messages[0].content, /Prefer concise replies/);
});

test('recall searches personal facts, project notes/decisions/todos and session summaries', async () => {
  remember.run({ action: 'add', text: 'I enjoy lunar photography' });
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
