import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { RoutineStore, describeRoutine, describeWatch } from '../../src/automation/routines.mjs';
import { ProjectStore, resolveProjectRef } from '../../src/memory/projects.mjs';
import { Agent } from '../../src/core/agent.mjs';

function tmpFile(t, name) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-tag-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return path.join(dir, name);
}

/* ---------------------------- the store side ---------------------------- */

test('a routine keeps its project tag across a reload, and untagged stays null', (t) => {
  const file = tmpFile(t, 'state.json');
  const store = new RoutineStore(file).load();
  store.addRoutine({ name: 'tagged', cron: 'daily 08:00', prompt: 'x', projectId: 'zumba' });
  store.addRoutine({ name: 'untagged', cron: 'daily 09:00', prompt: 'y' });

  const reloaded = new RoutineStore(file).load();
  assert.equal(reloaded.findRoutine('tagged').projectId, 'zumba');
  assert.equal(reloaded.findRoutine('untagged').projectId, null);
});

test('a watch keeps its project tag, and untagged stays null', (t) => {
  const file = tmpFile(t, 'state.json');
  const store = new RoutineStore(file).load();
  store.addWatch({ name: 'tagged', url: 'https://ex.test/', projectId: 'zumba' });
  store.addWatch({ name: 'untagged', url: 'https://ex.test/b' });

  const reloaded = new RoutineStore(file).load();
  assert.equal(reloaded.findWatch('tagged').projectId, 'zumba');
  assert.equal(reloaded.findWatch('untagged').projectId, null);
});

test('old records with no projectId field load fine', (t) => {
  const file = tmpFile(t, 'state.json');
  // Exactly what phase-1 records look like on disk.
  fs.writeFileSync(
    file,
    JSON.stringify({
      version: 1,
      routines: [{ id: 'legacy', name: 'legacy', cron: '0 8 * * *', prompt: 'x', enabled: true, runs: 0 }],
      watches: [{ id: 'legacy-w', name: 'legacy-w', url: 'https://ex.test/', intervalMs: 3600000, enabled: true }],
    })
  );
  const store = new RoutineStore(file).load();
  assert.equal(store.findRoutine('legacy').projectId, undefined, 'absent, not invented');
  assert.equal(store.findWatch('legacy-w').projectId, undefined);
  // And the display does not crash on them.
  assert.doesNotMatch(describeRoutine(store.findRoutine('legacy')), /\[/);
  assert.doesNotMatch(describeWatch(store.findWatch('legacy-w')), /\[/);
});

/* ------------------------------ displaying ------------------------------ */

test('describe* show the tag only when there is one', (t) => {
  const file = tmpFile(t, 'state.json');
  const store = new RoutineStore(file).load();
  store.addRoutine({ name: 'with proj', cron: 'daily 08:00', prompt: 'x', projectId: 'zumba' });
  store.addRoutine({ name: 'without', cron: 'daily 09:00', prompt: 'y' });
  const lines = store.routines.map(describeRoutine).join('\n');
  assert.match(lines, /with proj  \[zumba\]/);
  assert.doesNotMatch(lines, /without  \[/);

  store.addWatch({ name: 'w with', url: 'https://ex.test/', projectId: 'ankita' });
  store.addWatch({ name: 'w without', url: 'https://ex.test/b' });
  const wl = store.watches.map(describeWatch).join('\n');
  assert.match(wl, /w with  \[ankita\]/);
  assert.doesNotMatch(wl, /w without  \[/);
});

/* ------------------------------ resolving ------------------------------- */

test('resolveProjectRef: by id, by name, none, fallback, unknown', (t) => {
  const file = tmpFile(t, 'projects.json');
  const projects = new ProjectStore(file).load();
  projects.add({ name: 'Zumba' }); // id zumba
  projects.add({ name: 'ankita' });

  assert.deepEqual(resolveProjectRef(projects, 'zumba', null), { ok: true, projectId: 'zumba', projectName: 'Zumba' });
  assert.deepEqual(resolveProjectRef(projects, 'Zumba', null), { ok: true, projectId: 'zumba', projectName: 'Zumba' });
  assert.deepEqual(resolveProjectRef(projects, 'ankita', null), { ok: true, projectId: 'ankita', projectName: 'ankita' });

  // omitted -> whatever is active
  assert.deepEqual(resolveProjectRef(projects, undefined, 'zumba'), { ok: true, projectId: 'zumba' });
  assert.deepEqual(resolveProjectRef(projects, '', null), { ok: true, projectId: null });
  assert.deepEqual(resolveProjectRef(projects, '   ', 'ankita'), { ok: true, projectId: 'ankita' });

  // explicit opt-out wins over an active project
  assert.deepEqual(resolveProjectRef(projects, 'none', 'zumba'), { ok: true, projectId: null });
  assert.deepEqual(resolveProjectRef(projects, 'NONE', 'zumba'), { ok: true, projectId: null });

  const bad = resolveProjectRef(projects, 'ghost', 'zumba');
  assert.equal(bad.ok, false);
  assert.match(bad.error, /no project "ghost"/);
  assert.match(bad.error, /Known: zumba, ankita/);
  assert.match(bad.error, /none/);
});

test('an unknown project with no projects at all still explains itself', (t) => {
  const projects = new ProjectStore(tmpFile(t, 'projects.json')).load();
  const bad = resolveProjectRef(projects, 'ghost', null);
  assert.equal(bad.ok, false);
  assert.match(bad.error, /No projects exist yet/);
});

/* --------------------------- agent context ------------------------------ */

test('the agent exposes a project id to tools, and clears it with the project', () => {
  const agent = new Agent({ client: {}, config: { tools: false } });
  assert.equal(agent.projectId, null, 'no project -> no id');

  agent.setProject('Active project: zumba', 'zumba');
  assert.equal(agent.projectId, 'zumba');
  assert.match(agent.messages[0].content, /Active project: zumba/);

  agent.setProject('', null);
  assert.equal(agent.projectId, null, 'cleared with the project');
  assert.doesNotMatch(agent.messages[0].content, /Active project/);
});

test('a project block with no id yields no tag rather than an empty string', () => {
  const agent = new Agent({ client: {}, config: { tools: false } });
  agent.setProject('Active project: thing');
  assert.equal(agent.projectId, null);
});

/* --------------------------- metadata only ------------------------------ */

test('tagging does not change when a routine fires', (t) => {
  const file = tmpFile(t, 'state.json');
  const store = new RoutineStore(file).load();
  const at = new Date(2026, 8, 21, 8, 0, 5);
  store.addRoutine({ name: 'tagged', cron: 'daily 08:00', prompt: 'x', projectId: 'zumba' });
  store.addRoutine({ name: 'plain', cron: 'daily 08:00', prompt: 'y' });
  assert.deepEqual(store.dueRoutines(at).map((r) => r.id).sort(), ['plain', 'tagged']);
});

test('tagging does not change when a watch is due', (t) => {
  const file = tmpFile(t, 'state.json');
  const store = new RoutineStore(file).load();
  store.addWatch({ name: 'tagged', url: 'https://ex.test/', projectId: 'zumba' });
  store.addWatch({ name: 'plain', url: 'https://ex.test/b' });
  assert.equal(store.dueWatches(new Date()).length, 2);
});
