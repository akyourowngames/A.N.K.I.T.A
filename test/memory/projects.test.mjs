import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ProjectStore, describeProject, describeProjectFull, MAX_WORKLOG } from '../../src/memory/projects.mjs';
import { buildSystemPrompt } from '../../src/core/agent.mjs';

function tmpStore(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-projects-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return { store: new ProjectStore(path.join(dir, 'projects.json')).load(), file: path.join(dir, 'projects.json') };
}

test('a missing or malformed projects file loads empty instead of throwing', (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-projects-bad-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'projects.json');
  assert.deepEqual(new ProjectStore(file).load().projects, []);
  fs.writeFileSync(file, '{ not json at all');
  const store = new ProjectStore(file).load();
  assert.deepEqual(store.projects, []);
  assert.equal(store.activeId, null);
  assert.equal(store.active, null);
});

test('only a name is required, and it survives a reload', (t) => {
  const { store, file } = tmpStore(t);
  const p = store.add({ name: 'zumba' });
  assert.equal(p.id, 'zumba');
  assert.equal(p.summary, null);
  assert.deepEqual(p.conventions, []);
  assert.throws(() => store.add({}), /name is required/);

  const reloaded = new ProjectStore(file).load();
  assert.equal(reloaded.projects.length, 1);
  assert.equal(reloaded.find('zumba').name, 'zumba');
});

test('ids dedupe and lookup accepts an id or a display name', (t) => {
  const { store } = tmpStore(t);
  store.add({ name: 'Zumba' });
  store.add({ name: 'zumba' });
  assert.deepEqual(store.projects.map((p) => p.id), ['zumba', 'zumba-2']);
  assert.equal(store.find('ZUMBA').id, 'zumba');
  assert.equal(store.find('zumba-2').id, 'zumba-2');
  assert.equal(store.find('nope'), null);
});

test('use() sets the active project, stamps lastUsedAt, and persists', (t) => {
  const { store, file } = tmpStore(t);
  store.add({ name: 'one' });
  store.add({ name: 'two' });
  assert.equal(store.activeId, null);

  const used = store.use('two');
  assert.equal(used.id, 'two');
  assert.ok(used.lastUsedAt, 'lastUsedAt stamped');
  assert.equal(store.active.id, 'two');

  const reloaded = new ProjectStore(file).load();
  assert.equal(reloaded.activeId, 'two');
  assert.equal(reloaded.active.name, 'two');
  assert.equal(store.use('missing'), null);
});

test('update merges fields and a single convention appends without wiping the list', (t) => {
  const { store } = tmpStore(t);
  store.add({ name: 'zumba' });
  const updated = store.update('zumba', {
    summary: 'telegram assistant',
    path: 'C:\\Users\\anime\\zumba',
    conventions: ['pnpm not npm'],
  });
  assert.equal(updated.summary, 'telegram assistant');
  assert.equal(updated.path, path.resolve('C:\\Users\\anime\\zumba'));
  assert.deepEqual(updated.conventions, ['pnpm not npm']);

  store.addConvention('zumba', 'ports 4000+');
  assert.deepEqual(store.find('zumba').conventions, ['pnpm not npm', 'ports 4000+']);
  // Duplicates are ignored, and the list is capped.
  store.addConvention('zumba', 'PNPM NOT NPM');
  assert.equal(store.find('zumba').conventions.length, 2);
  for (let i = 0; i < 10; i++) store.addConvention('zumba', `rule ${i}`);
  assert.ok(store.find('zumba').conventions.length <= 5, 'conventions capped');
});

test('a long convention is stored intact, and only the prompt block is trimmed', (t) => {
  const { store } = tmpStore(t);
  // 76 chars - longer than the old 60-char write-time cap that silently
  // truncated a real value ("…edge-tts for voice, scrapling for scraping").
  const long = 'python + fastapi, pnpm for the frontend; edge-tts for voice, scrapling for scraping';
  store.add({ name: 'zumba', conventions: [long] });
  assert.equal(store.find('zumba').conventions[0], long, 'storage must keep every character');

  // It also survives an update round-trip, which is where the truncation bit.
  store.update('zumba', { conventions: [long] });
  assert.equal(store.find('zumba').conventions[0], long);

  store.use('zumba');
  const block = store.promptBlock();
  assert.ok(block.length < 700, `block still bounded, got ${block.length}`);
  assert.ok(block.includes('python + fastapi'), 'the start is shown');
});

test('update only touches the fields it is given', (t) => {
  const { store } = tmpStore(t);
  store.add({ name: 'zumba', summary: 'keep me', client: 'acme' });
  store.update('zumba', { path: 'C:\\tmp' });
  assert.equal(store.find('zumba').summary, 'keep me');
  assert.equal(store.find('zumba').client, 'acme');
});

test('forget removes one project and clears active when it pointed there', (t) => {
  const { store, file } = tmpStore(t);
  store.add({ name: 'one' });
  store.add({ name: 'two' });
  store.use('one');

  assert.equal(store.forget('one').name, 'one');
  assert.equal(store.activeId, null, 'active cleared');
  assert.deepEqual(store.projects.map((p) => p.id), ['two']);
  assert.equal(new ProjectStore(file).load().projects.length, 1, 'persisted');
  assert.equal(store.forget('ghost'), null);
});

test('a write from a second store instance is not clobbered', (t) => {
  const { store, file } = tmpStore(t);
  store.add({ name: 'zumba' });

  // Another process (the tool, or the REPL) holds its own store.
  const other = new ProjectStore(file).load();
  other.addConvention('zumba', 'added elsewhere');

  // This instance writes afterwards and must not lose it.
  store.update('zumba', { summary: 'summary from the first instance' });

  const final = new ProjectStore(file).load();
  assert.deepEqual(final.find('zumba').conventions, ['added elsewhere']);
  assert.equal(final.find('zumba').summary, 'summary from the first instance');
});

test('duplicate open project tasks are rejected without changing IDs or history', t => {
  const { store, file } = tmpStore(t);
  store.add({ name: 'Work' });
  const first = store.addTodo('Work', 'Fix desktop freeze');
  const id = first.todos[0].id;
  assert.equal(store.addTodo('Work', '  fix   DESKTOP freeze  ').error, 'an open todo with the same text already exists');
  store.addTodo('Work', 'Resolve merge conflict');
  store.completeTodo('Work', id);
  const todos = new ProjectStore(file).load().find('Work').todos;
  assert.equal(todos.length, 2);
  assert.equal(todos[0].id, id);
  assert.ok(todos[0].doneAt);
  assert.equal(todos[1].text, 'Resolve merge conflict');
});

test('a full project task list reports a conflict instead of deleting completion history', t => {
  const { store, file } = tmpStore(t);
  store.add({ name: 'Work' });
  for (let i = 0; i < 100; i++) store.addTodo('Work', `Task ${i}`);
  assert.match(store.addTodo('Work', 'One more').error, /limit/);
  const todos = new ProjectStore(file).load().find('Work').todos;
  assert.equal(todos.length, 100);
  assert.equal(todos[0].text, 'Task 0');
});

test('a malformed existing project file is never overwritten by a task update', t => {
  const { store, file } = tmpStore(t);
  store.add({ name: 'Work' });
  fs.writeFileSync(file, '{broken');
  assert.throws(() => store.addTodo('Work', 'New task'), /malformed/i);
  assert.equal(fs.readFileSync(file, 'utf8'), '{broken');
});

test('contradictory active tasks already on disk are reported before another write', t => {
  const { store, file } = tmpStore(t);
  store.add({ name: 'Work' });
  store.addTodo('Work', 'Fix freeze');
  const disk = JSON.parse(fs.readFileSync(file, 'utf8'));
  disk.projects[0].todos.push({ id: 't2', at: '2026-01-01T00:00:00Z', text: 'fix freeze', done: false });
  fs.writeFileSync(file, JSON.stringify(disk));
  const loaded = new ProjectStore(file).load();
  assert.match(loaded.conflicts.join('\n'), /duplicate active todo/i);
  assert.throws(() => loaded.addTodo('Work', 'Another task'), /conflict/i);
  assert.equal(JSON.parse(fs.readFileSync(file, 'utf8')).projects[0].todos.length, 2);
});

test('missingFor lists what is still unknown, most useful first', (t) => {
  const { store } = tmpStore(t);
  const bare = store.add({ name: 'zumba' });
  const missing = store.missingFor(bare);
  assert.equal(missing[0], 'what it is');
  assert.ok(missing.includes('which database it uses'));
  assert.ok(missing.includes('where it lives on disk'));

  const filled = store.update('zumba', { summary: 'x', path: 'C:\\tmp' });
  const still = store.missingFor(filled);
  assert.ok(!still.includes('what it is'));
  assert.ok(!still.includes('where it lives on disk'));
});

test('the prompt block is bounded, and empty when nothing is active', (t) => {
  const { store } = tmpStore(t);
  assert.equal(store.promptBlock(), '', 'nothing active -> no block');

  store.add({
    name: 'zumba',
    summary: 's'.repeat(500),
    path: 'C:\\Users\\anime\\zumba',
    client: 'acme',
    conventions: Array.from({ length: 12 }, (_, i) => `convention number ${i} `.repeat(4)),
    databases: [{ name: 'main', kind: 'postgres' }],
  });
  store.use('zumba');
  const block = store.promptBlock();

  assert.match(block, /Active project: zumba/);
  assert.match(block, /path: /);
  assert.match(block, /client: acme/);
  assert.match(block, /databases: postgres main/);
  assert.ok(block.length < 700, `block must stay small, got ${block.length} chars`);
  assert.ok(block.split('\n').length <= 8, 'few lines only');
});

test('the active project reaches the system prompt, and disappears with it', (t) => {
  const { store } = tmpStore(t);
  const config = { username: 'krish', agentName: 'ankita', systemExtra: '' };

  const before = buildSystemPrompt(config, 'C:/work');
  assert.doesNotMatch(before, /Active project/);

  store.add({ name: 'zumba', summary: 'telegram assistant', path: 'C:\\Users\\anime\\zumba' });
  store.addConvention('zumba', 'pnpm not npm');
  store.use('zumba');

  const after = buildSystemPrompt(config, 'C:/work', store.promptBlock());
  assert.match(after, /Active project: zumba/);
  assert.match(after, /telegram assistant/);
  assert.match(after, /pnpm not npm/);

  store.clearActive();
  const cleared = buildSystemPrompt(config, 'C:/work', store.promptBlock());
  assert.doesNotMatch(cleared, /Active project/);
});

test('listing marks the active project and shows where it lives', (t) => {
  const { store } = tmpStore(t);
  store.add({ name: 'zumba', path: 'C:\\Users\\anime\\zumba', summary: 'telegram assistant' });
  store.add({ name: 'ankita' });
  store.use('zumba');
  const list = store.projects.map((p) => describeProject(p, store.activeId)).join('\n');
  assert.match(list, /^\* zumba/m, 'active marked with *');
  assert.match(list, /^  ankita/m, 'inactive not marked');
  assert.match(describeProjectFull(store.find('zumba'), store), /active/);
});

test('the work log appends, dedupes a turn, caps entries, and never activates the project', (t) => {
  const { store } = tmpStore(t);
  store.add({ name: 'atlas' });
  const source = { kind: 'auto-worklog', sessionId: 's1', turnId: 'turn-1' };
  store.appendWorkLog('atlas', { text: 'model_answer · 1 file(s) · src/a.js', at: '2026-10-25T06:00:00.000Z', source });
  assert.equal(store.appendWorkLog('atlas', { text: 'duplicate', source }).error, 'this turn is already logged');
  assert.equal(store.find('atlas').worklog.length, 1);
  assert.equal(store.activeId, null, 'activity is not activation');
  assert.equal(store.find('atlas').lastUsedAt, '2026-10-25T06:00:00.000Z');

  for (let i = 0; i < MAX_WORKLOG + 2; i++) store.appendWorkLog('atlas', { text: `entry ${i}` });
  const log = store.find('atlas').worklog;
  assert.equal(log.length, MAX_WORKLOG);
  assert.equal(log.at(-1).text, `entry ${MAX_WORKLOG + 1}`, 'newest kept');
  assert.match(describeProjectFull(store.find('atlas'), store), /work\s+.*entry/);
});

test('promptBlock accepts an explicit project while it stays memory-free', (t) => {
  const { store } = tmpStore(t);
  store.add({ name: 'atlas', summary: 'shared work' });
  store.addNote('atlas', 'a private note');
  const block = store.promptBlock(store.find('atlas'));
  assert.match(block, /atlas/);
  assert.match(block, /shared work/);
  assert.doesNotMatch(block, /private note/);
  assert.match(block, /Active project: atlas/);
  assert.equal(store.activeId, null, 'the explicit argument does not activate anything');
});

test('undo removes only automatic writes and reopens the todos it closed', (t) => {
  const { store } = tmpStore(t);
  store.add({ name: 'atlas' });
  store.addNote('atlas', 'manual note');
  store.addTodo('atlas', 'ship it');
  store.addNote('atlas', 'auto note', { kind: 'auto-consolidation', sessionId: 's1', turnId: 't1' });
  store.addTodo('atlas', 'auto todo', { kind: 'auto-todo', sessionId: 's1' });
  store.completeTodo('atlas', 't1', { kind: 'auto-todo', sessionId: 's1' });
  store.appendWorkLog('atlas', { text: 'auto work', source: { kind: 'auto-worklog', sessionId: 's1', turnId: 't1' } });

  const result = store.removeAutoEntries('atlas', { sessionId: 's1' });
  assert.equal(result.worklog, 1);
  assert.equal(result.notes, 1);
  assert.equal(result.todos, 1);
  assert.equal(result.reopened, 1);
  assert.equal(result.total, 4);
  const project = store.find('atlas');
  assert.deepEqual(project.notes.map(note => note.text), ['manual note']);
  assert.deepEqual(project.todos.map(todo => [todo.text, todo.done]), [['ship it', false]]);
  assert.equal(project.worklog.length, 0);
});
