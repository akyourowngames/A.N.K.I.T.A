import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ProjectStore, STATUSES } from '../src/projects.mjs';
import { RoutineStore } from '../src/routines.mjs';

function ctxFor(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-life-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return {
    projectsFile: path.join(dir, 'projects.json'),
    stateFile: path.join(dir, 'state.json'),
  };
}

/* -------------------------------- rename -------------------------------- */

test('rename changes the display name and leaves the id alone', (t) => {
  const { projectsFile } = ctxFor(t);
  const s = new ProjectStore(projectsFile).load();
  s.add({ name: 'zumba' });

  const renamed = s.renameProject('zumba', 'Zumba Bot');
  assert.equal(renamed.name, 'Zumba Bot');
  assert.equal(renamed.id, 'zumba', 'id must not move under tagged items');
  // Still findable by the id, and by the new name.
  assert.equal(s.find('zumba').name, 'Zumba Bot');
  assert.equal(s.find('Zumba Bot').id, 'zumba');
  assert.equal(new ProjectStore(projectsFile).load().find('zumba').name, 'Zumba Bot');
  assert.equal(s.renameProject('ghost', 'x'), null);
  assert.equal(s.renameProject('zumba', '   '), null, 'empty name refused');
});

test('renaming does not orphan a tagged routine (the regression that matters)', (t) => {
  const { projectsFile, stateFile } = ctxFor(t);
  const projects = new ProjectStore(projectsFile).load();
  projects.add({ name: 'zumba' });
  const routines = new RoutineStore(stateFile).load();
  routines.addRoutine({ name: 'nightly', cron: 'daily 03:00', prompt: 'x', projectId: 'zumba' });

  new ProjectStore(projectsFile).load().renameProject('zumba', 'Zumba Bot');

  const after = new RoutineStore(stateFile).load().findRoutine('nightly');
  assert.equal(after.projectId, 'zumba', 'tag still resolves');
  assert.equal(new ProjectStore(projectsFile).load().find(after.projectId).name, 'Zumba Bot');
});

/* -------------------------------- status -------------------------------- */

test('status round-trips and rejects anything unknown', (t) => {
  const { projectsFile } = ctxFor(t);
  const s = new ProjectStore(projectsFile).load();
  s.add({ name: 'zumba' });
  assert.equal(s.find('zumba').status, 'active', 'defaults to active');

  for (const st of STATUSES) assert.equal(s.setStatus('zumba', st).status, st);
  assert.match(s.setStatus('zumba', 'banana').error, /must be one of/);
  assert.equal(s.find('zumba').status, STATUSES.at(-1), 'a rejected status changes nothing');
  assert.equal(s.setStatus('ghost', 'active'), null);
});

/* ------------------------------- archive -------------------------------- */

test('archive hides from list but keeps everything, and clears active', (t) => {
  const { projectsFile } = ctxFor(t);
  const s = new ProjectStore(projectsFile).load();
  s.add({ name: 'old' });
  s.add({ name: 'live' });
  s.use('old');
  assert.equal(s.activeId, 'old');

  const archived = s.setArchived('old', true);
  assert.equal(archived.archived, true);
  assert.equal(s.activeId, null, 'archiving the active project deactivates it');
  assert.equal(s.projects.length, 2, 'still stored');

  const reloaded = new ProjectStore(projectsFile).load();
  assert.deepEqual(reloaded.projects.filter((p) => !p.archived).map((p) => p.id), ['live']);
  assert.equal(reloaded.setArchived('old', false).archived, false, 'restore works');
  assert.equal(s.setArchived('ghost', true), null);
});

/* -------------------------- contacts and links -------------------------- */

test('a partial contact update keeps the fields it did not mention', (t) => {
  const { projectsFile } = ctxFor(t);
  const s = new ProjectStore(projectsFile).load();
  s.add({ name: 'zumba' });

  s.addContact('zumba', { name: 'Anu', role: 'PM' });
  assert.deepEqual(s.find('zumba').contacts, [{ name: 'Anu', role: 'PM', email: '' }]);

  // Adding just an email must not wipe the role.
  s.addContact('zumba', { name: 'anu', email: 'a@b.c' });
  assert.deepEqual(s.find('zumba').contacts, [{ name: 'anu', role: 'PM', email: 'a@b.c' }]);

  s.addContact('zumba', { name: 'Bob' });
  assert.equal(s.find('zumba').contacts.length, 2);
  assert.deepEqual(s.find('zumba').contacts[1], { name: 'Bob', role: '', email: '' });

  assert.match(s.addContact('zumba', {}).error, /needs a name/);
});

test('links validate the url and never duplicate-merge', (t) => {
  const { projectsFile } = ctxFor(t);
  const s = new ProjectStore(projectsFile).load();
  s.add({ name: 'zumba' });

  s.addLink('zumba', { label: 'dash', url: 'https://x.test/d' });
  assert.deepEqual(s.find('zumba').links, [{ label: 'dash', url: 'https://x.test/d' }]);
  assert.match(s.addLink('zumba', { url: 'notaurl' }).error, /not a valid url/);
  assert.match(s.addLink('zumba', { url: 'ftp://x.test' }).error, /http\(s\)/);
  assert.match(s.addLink('zumba', {}).error, /needs a url/);
  assert.equal(s.find('zumba').links.length, 1, 'nothing was added by the failures');
});

test('contacts and links are capped', (t) => {
  const { projectsFile } = ctxFor(t);
  const s = new ProjectStore(projectsFile).load();
  s.add({ name: 'zumba' });
  for (let i = 0; i < 30; i++) s.addContact('zumba', { name: `person ${i}` });
  assert.ok(s.find('zumba').contacts.length <= 20, `contacts capped, got ${s.find('zumba').contacts.length}`);
  for (let i = 0; i < 50; i++) s.addLink('zumba', { label: `l${i}`, url: `https://x.test/${i}` });
  assert.ok(s.find('zumba').links.length <= 40, `links capped, got ${s.find('zumba').links.length}`);
});

/* -------------------------------- attach -------------------------------- */

test('attach adopts only untagged items, then reports nothing left to do', (t) => {
  const { stateFile } = ctxFor(t);
  const s = new RoutineStore(stateFile).load();
  s.addRoutine({ name: 'plain one', cron: 'daily 01:00', prompt: 'x' });
  s.addRoutine({ name: 'already', cron: 'daily 02:00', prompt: 'y', projectId: 'other' });
  s.addWatch({ name: 'plain watch', url: 'https://ex.test/' });
  s.addWatch({ name: 'tagged watch', url: 'https://ex.test/b', projectId: 'other' });

  const moved = s.attachToProject('zumba');
  assert.deepEqual(moved.routines, ['plain-one']);
  assert.deepEqual(moved.watches, ['plain-watch']);
  assert.equal(s.findRoutine('already').projectId, 'other', 'existing tags untouched');
  assert.equal(s.findWatch('tagged-watch').projectId, 'other');
  assert.equal(new RoutineStore(stateFile).load().findRoutine('plain-one').projectId, 'zumba', 'persisted');

  const again = s.attachToProject('zumba');
  assert.deepEqual(again, { routines: [], watches: [] }, 'idempotent');
});

test('attach can take explicit ids, by id or by name', (t) => {
  const { stateFile } = ctxFor(t);
  const s = new RoutineStore(stateFile).load();
  s.addRoutine({ name: 'one', cron: 'daily 01:00', prompt: 'x', projectId: 'other' });
  s.addRoutine({ name: 'two', cron: 'daily 02:00', prompt: 'y' });
  s.addWatch({ name: 'w one', url: 'https://ex.test/' });

  // "one" is already tagged elsewhere; naming it explicitly moves it.
  const moved = s.attachToProject('zumba', { routines: ['one', 'Two'], watches: ['w-one'] });
  assert.deepEqual(moved.routines.sort(), ['one', 'two']);
  assert.deepEqual(moved.watches, ['w-one']);
  assert.equal(s.findRoutine('one').projectId, 'zumba');
  assert.equal(s.findRoutine('two').projectId, 'zumba');

  const none = s.attachToProject('zumba', { routines: ['ghost'] });
  assert.deepEqual(none, { routines: [], watches: [] }, 'unknown id matches nothing');
});

test('attach survives the multi-writer pattern', (t) => {
  const { stateFile } = ctxFor(t);
  const first = new RoutineStore(stateFile).load();
  first.addRoutine({ name: 'a', cron: 'daily 01:00', prompt: 'x' });

  // Another instance writes a watch after the first loaded.
  new RoutineStore(stateFile).load().addWatch({ name: 'added elsewhere', url: 'https://ex.test/' });

  const moved = first.attachToProject('zumba');
  assert.deepEqual(moved.watches, ['added-elsewhere'], 'the other instance is not lost');
});
