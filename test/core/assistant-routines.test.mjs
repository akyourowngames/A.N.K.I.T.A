import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const api = await import('../../src/assistant/routines.mjs').catch(() => ({}));
const source = { id: 'source-task', ownerId: 'owner', goal: 'Save a short note.', status: 'completed', projectId: null, workspacePath: null,
  reply: 'The note was saved.', steps: [{ tool: 'write_file', phase: 'settled', mutation: true, isError: false }], checklist: [] };
function setup(t, options = {}) {
  assert.ok(api.AssistantRoutineStore, 'teach-once storage exists');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'assistant-routines-')); t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  return new api.AssistantRoutineStore({ directory, ...options });
}

test('a completed request becomes an editable parameterized routine with source evidence and no tool replay', async t => {
  const store = setup(t);
  const routine = await store.save({ name: 'Save a note', template: 'Save a note about {{topic}} to {{filename}}.', parameters: [{ name: 'filename', defaultValue: 'note.txt' }], sourceTask: source });
  assert.equal(routine.sourceTaskId, source.id); assert.equal(routine.ownerId, source.ownerId);
  assert.deepEqual(routine.parameters.map(item => item.name), ['topic', 'filename']);
  assert.equal(routine.sourceEvidence.tools[0], 'write_file'); assert.equal(routine.enabled, undefined);
  assert.deepEqual((await store.prepare(routine.id, { ownerId: source.ownerId, values: {} })).missing, ['topic']);
  const prepared = await store.prepare(routine.id, { ownerId: source.ownerId, values: { topic: 'my project' } });
  assert.deepEqual(prepared.missing, []); assert.match(prepared.goal, /my project/); assert.match(prepared.goal, /note.txt/);
  assert.ok(!JSON.stringify(routine).includes('arguments'));
  const changed = await store.save({ id: routine.id, ownerId: source.ownerId, expectedRevision: routine.revision, name: 'Save a project note', template: routine.template, parameters: routine.parameters });
  assert.equal(changed.revision, routine.revision + 1);
  await assert.rejects(store.save({ id: routine.id, ownerId: source.ownerId, expectedRevision: routine.revision, name: 'stale', template: 'stale' }), /changed|revision/i);
});

test('uncertain sources, wrong owners, unsupported placeholders and unknown parameters fail before execution', async t => {
  const store = setup(t);
  await assert.rejects(store.save({ name: 'Unsafe', template: 'Do something', sourceTask: { ...source, status: 'needs_review' } }), /completed|uncertain/i);
  await assert.rejects(store.save({ name: 'Invalid', template: '{{eval.code}}', sourceTask: source }), /parameter|placeholder/i);
  const routine = await store.save({ name: 'Safe', template: 'Summarize {{topic}}.', sourceTask: source });
  await assert.rejects(store.prepare(routine.id, { ownerId: 'other', values: { topic: 'x' } }), /owner|conversation/i);
  await assert.rejects(store.prepare(routine.id, { ownerId: source.ownerId, values: { topic: 'x', secret_script: 'no' } }), /parameter/i);
  await store.remove(routine.id, { ownerId: source.ownerId }); assert.deepEqual(await store.list(), []);
});

test('serialized updates survive another store and malformed persisted state is not overwritten', async t => {
  const store = setup(t), routine = await store.save({ name: 'A routine', template: 'Explain {{topic}}.', sourceTask: source });
  const other = new api.AssistantRoutineStore({ directory: store.directory });
  assert.equal((await other.list())[0].id, routine.id);
  fs.writeFileSync(store.file, '{broken');
  await assert.rejects(other.save({ name: 'Cannot overwrite', template: 'No', sourceTask: source }));
  assert.equal(fs.readFileSync(store.file, 'utf8'), '{broken');
});
