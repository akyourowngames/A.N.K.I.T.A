import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// Point the whole config layer at a scratch home BEFORE anything that reads it
// loads, so the tool under test uses these files and not the real ones.
const SANDBOX = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-mem-'));
process.env.CONFIG_DIR = SANDBOX;

const { ProjectStore, since, MAX_NOTES, MAX_TODOS } = await import('../src/projects.mjs');
const { RoutineStore } = await import('../src/routines.mjs');
const mem = await import('../tools/project-memory.mjs');
const { PROJECTS_FILE, STATE_FILE } = await import('../src/config.mjs');

test.after(() => fs.rmSync(SANDBOX, { recursive: true, force: true }));

const ctx = { config: { username: 'krish' }, projectId: null };

let seq = 0;
/** A fresh project, so tests never tread on each other. */
function project(extra = {}) {
  const store = new ProjectStore(PROJECTS_FILE).load();
  const name = `p${++seq}`;
  store.add({ name, summary: 'a test project', ...extra });
  return name;
}

const reload = () => new ProjectStore(PROJECTS_FILE).load();

/* -------------------------------- writing -------------------------------- */

test('note, decide and todo all record and survive a reload', () => {
  const name = project();
  assert.match(mem.run({ action: 'note', name, text: 'client wants SSO' }, ctx), /Note recorded/);
  assert.match(mem.run({ action: 'decide', name, text: 'chose SQLite - single writer' }, ctx), /Decision recorded/);
  assert.match(mem.run({ action: 'todo', name, text: 'set up the vault' }, ctx), /\[t1\]/);

  const p = reload().find(name);
  assert.equal(p.notes[0].text, 'client wants SSO');
  assert.equal(p.decisions[0].text, 'chose SQLite - single writer');
  assert.equal(p.todos[0].text, 'set up the vault');
  assert.equal(p.todos[0].done, false);
  assert.ok(p.notes[0].at, 'timestamped');
});

test('the confirmation echoes what was kept and the running counts', () => {
  const name = project();
  mem.run({ action: 'note', name, text: 'first' }, ctx);
  const out = mem.run({ action: 'note', name, text: 'second' }, ctx);
  assert.match(out, /Note recorded on "[^"]+": second/);
  assert.match(out, /2 note\(s\), 0 decision\(s\), 0 open/);
});

test('text is required, and says so', () => {
  const name = project();
  assert.match(mem.run({ action: 'note', name }, ctx), /'text' is required/);
  assert.match(mem.run({ action: 'decide', name, text: '   ' }, ctx), /needs some text/);
  assert.match(mem.run({ action: 'todo', name, text: '' }, ctx), /'text' is required/);
});

/* ------------------------------ completing ------------------------------- */

test('done closes by id, by open-number, and by part of the text', () => {
  const name = project();
  mem.run({ action: 'todo', name, text: 'set up the vault' }, ctx);
  mem.run({ action: 'todo', name, text: 'write the SSO flow' }, ctx);
  mem.run({ action: 'todo', name, text: 'ship it' }, ctx);

  assert.match(mem.run({ action: 'done', name, ref: 't1' }, ctx), /Closed "set up the vault"/);
  // t1 is closed, so number 1 now refers to the next open item.
  assert.match(mem.run({ action: 'done', name, ref: '1' }, ctx), /Closed "write the SSO flow"/);
  assert.match(mem.run({ action: 'done', name, ref: 'ship' }, ctx), /Closed "ship it"/);
  assert.match(mem.run({ action: 'done', name, ref: 'anything' }, ctx), /nothing is open/);
});

test('an ambiguous done lists the candidates instead of guessing', () => {
  const name = project();
  mem.run({ action: 'todo', name, text: 'add SSO for the client' }, ctx);
  mem.run({ action: 'todo', name, text: 'add SSO for the admin' }, ctx);
  const out = mem.run({ action: 'done', name, ref: 'SSO' }, ctx);
  assert.match(out, /matches 2/);
  assert.match(out, /t1/);
  assert.match(out, /t2/);
  assert.equal(reload().find(name).todos.filter((t) => !t.done).length, 2, 'nothing was closed');
});

/* --------------------------------- log ----------------------------------- */

test('log shows counts, open items, decisions and notes in a readable order', () => {
  const name = project();
  mem.run({ action: 'note', name, text: 'kickoff call went well' }, ctx);
  mem.run({ action: 'decide', name, text: 'chose SQLite over Postgres' }, ctx);
  mem.run({ action: 'todo', name, text: 'set up the vault' }, ctx);
  mem.run({ action: 'todo', name, text: 'wire the SSO' }, ctx);

  const log = mem.run({ action: 'log', name }, ctx);
  assert.match(log, /1 note\(s\), 1 decision\(s\), 2 open \(0 done\)/);
  assert.match(log, /\[1\] set up the vault/);
  assert.match(log, /\[2\] wire the SSO/);
  assert.match(log, /decisions/, 'has a decisions section');
  assert.match(log, /chose SQLite over Postgres/);
  assert.match(log, /notes/);
  assert.match(log, /kickoff call went well/);
  assert.ok(log.indexOf('open') < log.indexOf('notes'), 'open items come first');
});

test('log on an empty project explains itself instead of printing nothing', () => {
  const name = project();
  const log = mem.run({ action: 'log', name }, ctx);
  assert.match(log, /Nothing remembered about/);
  assert.match(log, /action=note/, 'tells the model how to start');
});

test('completed items show under done, not under open', () => {
  const name = project();
  mem.run({ action: 'todo', name, text: 'finish the thing' }, ctx);
  mem.run({ action: 'done', name, ref: 't1' }, ctx);
  const log = mem.run({ action: 'log', name }, ctx);
  assert.match(log, /0 open \(1 done\)/);
  assert.match(log, /done\n\s+just now\s+finish the thing/);
});

/* -------------------------------- brief ---------------------------------- */

test('brief hands over everything needed, grounded in that project alone', () => {
  const name = project({ path: 'C:\\work\\thing' });
  mem.run({ action: 'note', name, text: 'the client asked about SSO' }, ctx);
  mem.run({ action: 'decide', name, text: 'chose SQLite over Postgres' }, ctx);
  mem.run({ action: 'todo', name, text: 'set up the vault' }, ctx);

  const routines = new RoutineStore(STATE_FILE).load();
  routines.attachToProject(name);
  routines.addRoutine({ name: 'thing nightly', cron: 'daily 03:00', prompt: 'x', projectId: name });
  routines.addWatch({ name: 'thing uptime', url: 'https://a.test/', projectId: name });
  routines.addWatch({ name: 'someone elses', url: 'https://b.test/', projectId: 'other-project' });

  const brief = mem.run({ action: 'brief', name }, ctx);
  assert.match(brief, /Write krish a short brief/);
  assert.match(brief, /WHAT IT IS/);
  assert.match(brief, /a test project/);
  assert.match(brief, /C:\\work\\thing/);
  assert.match(brief, /OPEN ITEMS/);
  assert.match(brief, /set up the vault/);
  assert.match(brief, /DECISIONS/);
  assert.match(brief, /chose SQLite over Postgres/);
  assert.match(brief, /RECENT NOTES/);
  assert.match(brief, /thing nightly/, 'includes its routines');
  assert.match(brief, /thing uptime/, 'includes its watches');
  assert.doesNotMatch(brief, /someone elses/, "never another project's watch");
  assert.match(brief, /invent nothing/i, 'tells the model to stay grounded');
});

test('brief on an empty project is honest rather than padded', () => {
  const name = project();
  const brief = mem.run({ action: 'brief', name }, ctx);
  assert.match(brief, /OPEN ITEMS\n\s+none recorded/);
  assert.match(brief, /say so plainly instead of padding/);
});

/* ------------------------- project resolution --------------------------- */

test('the memory tool defaults to the active project', () => {
  const name = project();
  const store = reload();
  store.use(name);
  assert.match(mem.run({ action: 'note', text: 'via the active project' }, { config: {}, projectId: name }), /Note recorded/);
  assert.equal(reload().find(name).notes.at(-1).text, 'via the active project');
});

test('an unnameable project is reported, never guessed', () => {
  const out = mem.run({ action: 'log' }, { config: {}, projectId: null });
  assert.match(out, /No project is active and none was named/);
  const bad = mem.run({ action: 'log', name: 'ghost' }, ctx);
  assert.match(bad, /No project "ghost"/);
});

/* ---------------------------- the design rule --------------------------- */

test('memory never reaches the system prompt, however much accumulates', () => {
  const name = project();
  for (let i = 0; i < 10; i++) mem.run({ action: 'note', name, text: `private detail ${i}` }, ctx);
  mem.run({ action: 'decide', name, text: 'drop the old API next quarter' }, ctx);
  mem.run({ action: 'todo', name, text: 'call the lawyer' }, ctx);

  const store = reload();
  store.use(name);
  const block = store.promptBlock();
  assert.doesNotMatch(block, /private detail/);
  assert.doesNotMatch(block, /drop the old API/);
  assert.doesNotMatch(block, /lawyer/);
  assert.match(block, /Active project/, 'the block still works');
  assert.ok(block.length < 700, `bounded as memory grows, got ${block.length}`);
});

/* -------------------------------- caps ---------------------------------- */

test('caps hold and say when older entries were dropped', () => {
  const name = project();
  const store = reload();
  for (let i = 0; i < MAX_NOTES + 2; i++) store.addNote(name, `note ${i}`);
  const notes = reload().find(name).notes;
  assert.equal(notes.length, MAX_NOTES);
  assert.equal(notes.at(-1).text, `note ${MAX_NOTES + 1}`, 'newest kept');
  assert.equal(notes[0].text, 'note 2', 'oldest dropped');

  const todoStore = reload();
  for (let i = 0; i < MAX_TODOS + 2; i++) todoStore.addTodo(name, `todo ${i}`);
  assert.equal(reload().find(name).todos.length, MAX_TODOS);
});

/* -------------------------------- since --------------------------------- */

test('since() reads like a memory, not a timestamp', () => {
  const now = Date.UTC(2026, 8, 19, 12, 0, 0);
  const at = (ms) => new Date(now - ms).toISOString();
  assert.equal(since(at(5_000), now), 'just now');
  assert.equal(since(at(90_000), now), '1m ago');
  assert.equal(since(at(3 * 3600_000), now), '3h ago');
  assert.equal(since(at(2 * 86400_000), now), '2d ago');
  assert.equal(since(at(10 * 86400_000), now), '1w ago');
  assert.equal(since(at(60 * 86400_000), now), '2mo ago');
  assert.equal(since('not a date', now), '');
});

test('the tool is registered and self-describes', () => {
  assert.equal(mem.name, 'project_memory');
  assert.equal(mem.needsApproval, false);
  assert.match(mem.description, /note, decide, todo, done, log, brief/);
});
