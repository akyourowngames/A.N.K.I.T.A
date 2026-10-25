import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ProjectStore } from '../../src/memory/projects.mjs';
import { maintainTurn } from '../../src/memory/project-maintenance.mjs';

function fixture(t, extra = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-maintain-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const projectsFile = path.join(dir, 'projects.json');
  const store = new ProjectStore(projectsFile).load();
  const project = store.add({ name: 'Atlas', ...extra });
  return { dir, projectsFile, store, project };
}

const audit = (files = ['src/a.js', 'src/b.js']) => ({
  turnId: 'turn-1', tools: ['write_file'], files, changed: true, termination: 'model_answer', dropped: 0,
});

test('one changed turn writes one bounded work-log entry and leaves the active project alone', async (t) => {
  const f = fixture(t);
  assert.equal(new ProjectStore(f.projectsFile).load().activeId, null);
  const result = await maintainTurn({ projectId: f.project.id, audit: audit(), sessionId: 's1', turnId: 'turn-1', config: {}, projectsFile: f.projectsFile });
  assert.equal(result.written, 1);

  const stored = new ProjectStore(f.projectsFile).load();
  assert.equal(stored.activeId, null, 'automatic activity never activates a project');
  const project = stored.find(f.project.id);
  assert.equal(project.worklog.length, 1);
  assert.match(project.worklog[0].text, /model_answer · 2 file\(s\) · src\/a\.js, src\/b\.js/);
  assert.equal(project.worklog[0].source.kind, 'auto-worklog');
  assert.equal(project.worklog[0].source.sessionId, 's1');
  assert.equal(project.worklog[0].source.turnId, 'turn-1');
  assert.ok(project.lastUsedAt, 'activity stamps lastUsedAt');

  const replay = await maintainTurn({ projectId: f.project.id, audit: audit(), sessionId: 's1', turnId: 'turn-1', config: {}, projectsFile: f.projectsFile });
  assert.equal(replay.written, 0);
  assert.equal(new ProjectStore(f.projectsFile).load().find(f.project.id).worklog.length, 1, 'a turn is never logged twice');
});

test('pure question turns write nothing', async (t) => {
  const f = fixture(t);
  const result = await maintainTurn({ projectId: f.project.id, audit: { ...audit([]), changed: false }, todos: [], sessionId: 's1', turnId: 'q', config: {}, projectsFile: f.projectsFile });
  assert.equal(result.skipped, 'no-work');
  assert.equal(new ProjectStore(f.projectsFile).load().find(f.project.id).worklog.length, 0);
});

test('session todos are added and auto-completed with provenance that undo can reverse', async (t) => {
  const f = fixture(t);
  const store = new ProjectStore(f.projectsFile).load();
  store.addTodo(f.project.id, 'ship the release');
  const todos = [
    { id: 'session-1', content: 'write the docs', status: 'pending' },
    { id: 'session-2', content: 'ship the release', status: 'completed' },
  ];
  const result = await maintainTurn({ projectId: f.project.id, audit: { ...audit([]), changed: false }, todos, sessionId: 's1', turnId: 't2', config: {}, projectsFile: f.projectsFile });
  assert.equal(result.written, 2);

  const stored = new ProjectStore(f.projectsFile).load().find(f.project.id);
  assert.ok(stored.todos.some(todo => !todo.done && todo.text === 'write the docs'));
  const closed = stored.todos.find(todo => todo.text === 'ship the release');
  assert.equal(closed.done, true);
  assert.equal(closed.doneSource.kind, 'auto-todo');
  assert.equal(stored.worklog.length, 0, 'bookkeeping alone is not work-log noise');

  const undo = new ProjectStore(f.projectsFile).load().removeAutoEntries(f.project.id, { sessionId: 's1' });
  assert.equal(undo.todos, 1);
  assert.equal(undo.reopened, 1);
  const restored = new ProjectStore(f.projectsFile).load().find(f.project.id);
  assert.deepEqual(restored.todos.map(todo => [todo.text, todo.done]), [['ship the release', false]]);
});

test('the per-turn todo cap is enforced', async (t) => {
  const f = fixture(t);
  const todos = ['one', 'two', 'three'].map((content, index) => ({ id: `s${index}`, content, status: 'pending' }));
  await maintainTurn({ projectId: f.project.id, audit: { ...audit([]), changed: false }, todos, sessionId: 's1', config: { projectTodoSyncMax: 2 }, projectsFile: f.projectsFile });
  const stored = new ProjectStore(f.projectsFile).load().find(f.project.id);
  assert.deepEqual(stored.todos.map(todo => todo.text), ['one', 'two']);
});

test('a disabled flag or a malformed store writes nothing and never throws', async (t) => {
  const f = fixture(t);
  const disabled = await maintainTurn({ projectId: f.project.id, audit: audit(), sessionId: 's1', config: { projectAutoMaintenance: false }, projectsFile: f.projectsFile });
  assert.equal(disabled.skipped, 'disabled');
  assert.equal(new ProjectStore(f.projectsFile).load().find(f.project.id).worklog.length, 0);

  fs.writeFileSync(f.projectsFile, '{ not json');
  const malformed = await maintainTurn({ projectId: f.project.id, audit: audit(), sessionId: 's1', config: {}, projectsFile: f.projectsFile });
  assert.equal(malformed.written, 0);
  assert.equal(malformed.skipped, 'no-project');
});

test('the work-log cap keeps the newest entries', async (t) => {
  const f = fixture(t);
  for (let i = 0; i < 4; i++) {
    await maintainTurn({ projectId: f.project.id, audit: audit([`src/${i}.js`]), sessionId: 's1', turnId: `t${i}`, config: { projectWorklogMax: 2 }, projectsFile: f.projectsFile });
  }
  const stored = new ProjectStore(f.projectsFile).load().find(f.project.id);
  assert.equal(stored.worklog.length, 2);
  assert.match(stored.worklog.at(-1).text, /src\/3\.js/);
});
