import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const apiUrl = new URL('../../src/assistant/tasks.mjs', import.meta.url);
async function setup(t, options = {}) {
  assert.ok(fs.existsSync(apiUrl), 'durable assistant tasks exist');
  const api = await import(apiUrl.href);
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-assistant-tasks-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  return { ...api, directory, store: new api.AssistantTaskStore({ directory, ...options }) };
}
const metadata = { ownerId: 'thread-one', goal: 'Read the brief, save a note and make a reminder.', surface: 'desktop', projectId: 'project-one' };
const call = (id, name = 'write_file', args = { path: 'note.txt', content: 'A useful note' }) => ({ id, name, arguments: args });
const success = { content: [{ type: 'text', text: 'Saved the note.' }], isError: false };

test('goals, checklist and actual action phases survive a new store instance', async t => {
  const { store, directory, AssistantTaskStore } = await setup(t);
  const task = store.create(metadata);
  store.start(task.id, { ownerId: metadata.ownerId });
  store.requested(task.id, call('save'), { mutation: true });
  assert.equal(store.get(task.id).steps[0].phase, 'requested');
  store.started(task.id, call('save'));
  store.settled(task.id, call('save'), success);
  store.checklist(task.id, [{ id: 'read', content: 'Read brief', status: 'completed' }, { id: 'remind', content: 'Create reminder', status: 'pending' }]);
  store.finish(task.id, { reply: 'The note is saved.', status: 'interrupted' });
  const recovered = new AssistantTaskStore({ directory }).get(task.id);
  assert.equal(recovered.goal, metadata.goal);
  assert.equal(recovered.steps[0].phase, 'settled');
  assert.equal(recovered.steps[0].mutation, true);
  assert.equal(recovered.checklist[1].status, 'pending');
  assert.equal(recovered.status, 'interrupted');
});

test('recovery distinguishes unstarted permission requests from uncertain started writes', async t => {
  const { store, directory, AssistantTaskStore } = await setup(t, { runtimeId: 'old-runtime' });
  const task = store.create(metadata);
  store.start(task.id, { ownerId: metadata.ownerId });
  store.requested(task.id, call('awaiting-permission'), { mutation: true });
  store.requested(task.id, call('started-write', 'write_file', { path: 'other.txt', content: 'Other' }), { mutation: true });
  store.started(task.id, call('started-write', 'write_file', { path: 'other.txt', content: 'Other' }));
  const current = new AssistantTaskStore({ directory, runtimeId: 'new-runtime', isProcessAlive: () => false });
  assert.equal(current.recoverInterrupted(), 1);
  const recovered = current.get(task.id);
  assert.equal(recovered.status, 'interrupted');
  assert.deepEqual(recovered.steps.map(step => step.phase), ['not_run', 'uncertain']);
  assert.equal(current.recoverInterrupted(), 0);
});

test('resume preserves original goal and blocks exact completed or uncertain mutations without blocking fresh reads', async t => {
  const { store, recoveryPrompt } = await setup(t);
  const task = store.create(metadata);
  store.start(task.id, { ownerId: metadata.ownerId });
  store.requested(task.id, call('first'), { mutation: true }); store.started(task.id, call('first')); store.settled(task.id, call('first'), success);
  store.finish(task.id, { status: 'interrupted' });
  store.resume(task.id, { ownerId: metadata.ownerId });
  assert.throws(() => store.guard(task.id, call('repeat'), { mutation: true }), /already.*completed|previously.*completed/i);
  assert.doesNotThrow(() => store.guard(task.id, call('read', 'read_file', { path: 'note.txt' }), { mutation: false }));
  assert.doesNotThrow(() => store.guard(task.id, call('new', 'write_file', { path: 'reminder.txt', content: 'Reminder' }), { mutation: true }));
  const prompt = recoveryPrompt(store.get(task.id));
  assert.ok(prompt.includes(metadata.goal));
  assert.match(prompt, /untrusted|data/i);
  assert.match(prompt, /remaining|unfinished/i);
  assert.doesNotMatch(prompt, /"content":"A useful note"/);
});

test('task ownership, corruption, traversal and live process leases fail closed', async t => {
  const { store, directory, AssistantTaskStore } = await setup(t);
  const task = store.create(metadata); store.start(task.id, { ownerId: metadata.ownerId });
  assert.throws(() => store.resume(task.id, { ownerId: 'different-thread' }), /owner|conversation/i);
  assert.throws(() => store.get('../outside'), /identity|id/i);
  assert.throws(() => store.resume(task.id, { ownerId: metadata.ownerId }), /running|active/i);
  const sibling = new AssistantTaskStore({ directory, runtimeId: 'another-runtime', isProcessAlive: () => true });
  assert.equal(sibling.recoverInterrupted(), 0);
  assert.equal(sibling.get(task.id).status, 'running');
  fs.writeFileSync(path.join(directory, task.id, 'task.json'), '{corrupt');
  assert.throws(() => store.get(task.id), /read|corrupt|JSON/i);
  assert.equal(fs.readFileSync(path.join(directory, task.id, 'task.json'), 'utf8'), '{corrupt');
});

test('checkpoints redact secrets, bound results and never persist raw action arguments or stale UI refs', async t => {
  const secret = 'fixture-secret-do-not-persist';
  const { store, directory } = await setup(t, { transform: value => JSON.parse(JSON.stringify(value).replaceAll(secret, '[removed]')) });
  const task = store.create({ ...metadata, goal: `Use ${secret} safely` }); store.start(task.id, { ownerId: metadata.ownerId });
  const action = call('private', 'mcp__phone__click', { ref: 'stale-private-ref', token: secret });
  store.requested(task.id, action, { mutation: true }); store.started(task.id, action);
  store.settled(task.id, action, { content: [{ type: 'text', text: secret + 'x'.repeat(20000) }] });
  const raw = fs.readFileSync(path.join(directory, task.id, 'task.json'), 'utf8');
  assert.ok(!raw.includes(secret)); assert.ok(!raw.includes('stale-private-ref'));
  assert.ok(raw.length < 10000);
  assert.equal(store.get(task.id).steps[0].resultTruncated, true);
});

test('failed or unsettled effects cannot make an assistant task look completed', async t => {
  const { store } = await setup(t);
  const task = store.create(metadata); store.start(task.id, { ownerId: metadata.ownerId });
  store.requested(task.id, call('failure'), { mutation: true }); store.started(task.id, call('failure'));
  store.settled(task.id, call('failure'), { content: [{ type: 'text', text: 'Error: network timeout' }], isError: true });
  store.finish(task.id, { reply: 'Everything is done!', status: 'completed' });
  assert.equal(store.get(task.id).status, 'needs_review');
  assert.throws(() => store.guard(task.id, call('again'), { mutation: true }), /uncertain|check/i);
});

test('a deliberate repeated action in the same uninterrupted attempt is not confused with recovery replay', async t => {
  const { store } = await setup(t);
  const task = store.create(metadata); store.start(task.id, { ownerId: metadata.ownerId });
  store.requested(task.id, call('first'), { mutation: true }); store.started(task.id, call('first')); store.settled(task.id, call('first'), success);
  assert.doesNotThrow(() => store.guard(task.id, call('intentional-repeat'), { mutation: true }));
});

test('unresolved interrupted writes block fresh writes too, but allow fresh reads until reviewed', async t => {
  const { store } = await setup(t), task = store.create(metadata), pending = call('pending');
  store.start(task.id); store.requested(task.id, pending); store.started(task.id, pending);
  store.finish(task.id, { status: 'interrupted' }); store.resume(task.id, { ownerId: metadata.ownerId });
  assert.throws(() => store.guard(task.id, { id: 'different', name: 'write_file', arguments: { path: 'different.txt' } }), /uncertain|review/i);
  assert.doesNotThrow(() => store.guard(task.id, pending, { mutation: false }));
});

test('recovery context stays bounded while retaining the original goal and signalling omitted receipts', async t => {
  const { store, recoveryPrompt } = await setup(t), task = store.create(metadata); store.start(task.id);
  for (let i = 0; i < 24; i++) { const action = call(`read-${i}`); store.requested(task.id, action, { mutation: false }); store.started(task.id, action); store.settled(task.id, action, { content: [{ type: 'text', text: 'x'.repeat(3000) }] }); }
  store.finish(task.id, { status: 'interrupted' });
  const prompt = recoveryPrompt(store.get(task.id));
  assert.ok(Buffer.byteLength(prompt) < 20000); assert.ok(prompt.includes(metadata.goal)); assert.match(prompt, /omittedSteps/);
});

test('recovery rechecks the current owner and attempt after its discovery snapshot', async t => {
  const { store, directory, AssistantTaskStore } = await setup(t, { runtimeId: 'old' });
  const task = store.create(metadata); store.start(task.id);
  const winner = new AssistantTaskStore({ directory, runtimeId: 'winner', isProcessAlive: () => false });
  const slow = new AssistantTaskStore({ directory, runtimeId: 'slow', isProcessAlive: () => false });
  const discovered = store.list();
  slow.list = () => {
    winner.recoverInterrupted(); winner.resume(task.id, { ownerId: metadata.ownerId });
    return discovered;
  };
  assert.equal(slow.recoverInterrupted(), 0);
  assert.equal(store.get(task.id).runtimeId, 'winner'); assert.equal(store.get(task.id).status, 'running');
});

test('one damaged task is preserved and reported without disabling healthy tasks', async t => {
  const { store, directory } = await setup(t);
  const broken = store.create(metadata), file = path.join(directory, broken.id, 'task.json');
  fs.writeFileSync(file, '{corrupt');
  const healthy = store.create({ ...metadata, goal: 'An independent healthy request.' });
  assert.equal(store.list().length, 1); assert.equal(store.list()[0].id, healthy.id);
  assert.equal(store.readIssues()[0].id, broken.id);
  assert.equal(fs.readFileSync(file, 'utf8'), '{corrupt');
});

test('native browser operation binding persists once and rejects a changed operation or wrong owner', async t => {
  const { store, directory, AssistantTaskStore } = await setup(t), task = store.create(metadata); store.start(task.id);
  store.bindBrowserOperation(task.id, 'native-operation', { ownerId: metadata.ownerId, provider: 'browser-provider' });
  store.bindBrowserOperation(task.id, 'native-operation', { ownerId: metadata.ownerId, provider: 'browser-provider' });
  assert.throws(() => store.bindBrowserOperation(task.id, 'other', { ownerId: metadata.ownerId, provider: 'browser-provider' }), /operation|binding/i);
  assert.throws(() => store.bindBrowserOperation(task.id, 'native-operation', { ownerId: 'another-owner', provider: 'browser-provider' }), /conversation/i);
  const saved = new AssistantTaskStore({ directory }).get(task.id);
  assert.equal(saved.browserOperationId, 'native-operation'); assert.equal(saved.provider, 'browser-provider');
});
