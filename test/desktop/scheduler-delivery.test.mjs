import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DesktopEngine } from '../../desktop/electron/engine.mjs';
import { JOB_HISTORY_KEEP } from '../../src/automation/job-policy.mjs';
import { ProjectStore } from '../../src/memory/projects.mjs';

function mainTeammate(engine, write = async () => 'I checked the page and found 71 followers.') {
  const calls = [];
  const agent = {
    model: 'teammate-model',
    messages: [{ role: 'system', content: 'You are the Research desk teammate.' }],
    state: { todos: [] },
    config: { historyMessages: 40 }, contextWindow: 32768,
    refreshPrompt() { return this; }, trimHistory() {},
    async streamTurn(options) { calls.push({ options, messages: structuredClone(this.messages) }); return { content: await write(options) , toolCalls: [] }; },
  };
  engine.agents.set('chief', agent);
  return { agent, calls };
}

test('job project context refreshes from disk and respects fixed, inherited and detached projects', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'job-context-'));
  t.after(() => { assert.equal(path.dirname(fs.realpathSync(dir)), fs.realpathSync(os.tmpdir())); fs.rmSync(dir, { recursive: true, force: true }); });
  const projectsFile = path.join(dir, 'projects.json'), projects = new ProjectStore(projectsFile).load();
  const owner = projects.add({ name: 'Owner work', summary: 'Original brief', path: dir });
  const fixed = projects.add({ name: 'Fixed work', summary: 'Explicit job context', path: dir });
  const engine = new DesktopEngine({ teammateFile: path.join(dir, 'teammates.json'), projectsFile, config: {}, mcp: {} });
  engine.teammates.load(); engine.teammates.update('chief', { projectId: owner.id });
  const routine = { threadId: 'chief' };
  assert.equal(engine.contextForJob(routine).projectId, owner.id);
  projects.update(owner.id, { summary: 'Refreshed brief' });
  assert.match(engine.contextForJob(routine).project, /Refreshed brief/);
  assert.equal(engine.contextForJob({ ...routine, projectId: fixed.id }).projectId, fixed.id);
  const detached = engine.contextForJob({ ...routine, projectDetached: true });
  assert.equal(detached.projectId, null); assert.ok(!detached.project.includes('Refreshed brief'));
  assert.throws(() => engine.validateJobProject('missing'), /Project not found/);
});

test('text error diagnostics scrub ordinary password echoes without changing the live error', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'job-diagnostics-'));
  t.after(() => { assert.equal(path.dirname(fs.realpathSync(dir)), fs.realpathSync(os.tmpdir())); fs.rmSync(dir, { recursive: true, force: true }); });
  const engine = new DesktopEngine({ teammateFile: path.join(dir, 'teammates.json'), config: {}, mcp: {} });
  const secret = 'short-diagnostic-password';
  await engine.secretHistory.prepare(`DB_PASSWORD=${secret}`);
  const error = new Error(`Transport echoed ${secret}`); engine.recordDiagnostic(error);
  const logs = fs.readdirSync(path.join(dir, 'logs')).map(file => fs.readFileSync(path.join(dir, 'logs', file), 'utf8')).join('');
  assert.ok(!logs.includes(secret)); assert.match(logs, /REDACTED/);
  assert.ok(error.message.includes(secret), 'The live error is untouched');
});
test('proof retention is capped in the copied chat receipts and old run markers still deduplicate', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'job-proof-retention-')); t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const engine = new DesktopEngine({ teammateFile: path.join(dir, 'teammates.json'), sessionsDir: dir, config: {}, mcp: {} }); engine.teammates.load();
  mainTeammate(engine);
  const base = { routineId: 'routine', name: 'Routine', threadId: 'chief', status: 'ok', text: 'Done', proof: { screenshot: 'private-proof' }, at: new Date().toISOString() };
  for (let n = 0; n <= JOB_HISTORY_KEEP; n++) await engine.deliverRoutine({ ...base, runId: String(n) });
  assert.equal(engine.routineReceipts('chief').length, JOB_HISTORY_KEEP);
  await engine.deliverRoutine({ ...base, runId: '0' });
  assert.equal(engine.loadThread('chief').length, JOB_HISTORY_KEEP + 1); assert.equal(engine.routineReceipts('chief').length, JOB_HISTORY_KEEP);
});
test('job delivery waits for a live turn, is idempotent across restart, and restores the proof card', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'job-delivery-')); t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const engine = new DesktopEngine({ teammateFile: path.join(dir, 'teammates.json'), sessionsDir: dir, config: {}, mcp: {} });
  engine.teammates.load();
  const { calls } = mainTeammate(engine);
  const receipt = { runId: 'once', routineId: 'read', name: 'Read', threadId: 'chief', status: 'ok', text: 'Finished.', proof: { url: 'https://example.com', screenshot: null }, at: new Date().toISOString() };
  assert.equal(typeof engine.deliverRoutine, 'function');
  engine.turns.set('chief', Promise.resolve());
  assert.equal(await engine.deliverRoutine(receipt), false); assert.deepEqual(engine.loadThread('chief'), []);
  engine.turns.delete('chief'); await engine.flushRoutineDeliveries('chief');
  assert.equal(await engine.deliverRoutine(receipt), true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.useTools, false, 'The main teammate writes without re-running tools');
  assert.match(JSON.stringify(calls[0].messages), /Finished\./);
  assert.equal(engine.loadThread('chief').length, 1);
  assert.equal(engine.loadThread('chief')[0].content, 'I checked the page and found 71 followers.');
  assert.equal(engine.loadThread('chief')[0].job.runId, 'once');
  const restored = new DesktopEngine({ teammateFile: path.join(dir, 'teammates.json'), sessionsDir: dir, config: {}, mcp: {} }); restored.teammates.load();
  await restored.deliverRoutine(receipt); assert.equal(restored.loadThread('chief').length, 1);
  assert.equal(restored.loadThread('chief')[0].job.proof.url, 'https://example.com');
});

test('a failed teammate composition stays queued without exposing the raw worker summary', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'job-compose-retry-')); t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const engine = new DesktopEngine({ teammateFile: path.join(dir, 'teammates.json'), sessionsDir: dir, config: {}, mcp: {} }); engine.teammates.load();
  let attempts = 0;
  mainTeammate(engine, async () => { if (!attempts++) throw new Error('Provider disconnected'); return 'I retried the report: 71 followers.'; });
  const receipt = { runId: 'retry', routineId: 'followers', name: 'Follower check', threadId: 'chief', status: 'ok', text: 'Followers: 71', proof: null, at: new Date().toISOString() };
  await assert.rejects(engine.deliverRoutine(receipt), /Provider disconnected/);
  assert.deepEqual(engine.loadThread('chief'), []);
  assert.equal(engine.routineDeliveryIds('chief').includes(receipt.runId), false);
  assert.equal(await engine.deliverRoutine(receipt), true);
  assert.equal(engine.loadThread('chief')[0].content, 'I retried the report: 71 followers.');
  assert.equal(attempts, 2);
});

test('delivery resumes a saved teammate draft after a crash without asking the model twice', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'job-draft-recovery-')); t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const engine = new DesktopEngine({ teammateFile: path.join(dir, 'teammates.json'), sessionsDir: dir, config: {}, mcp: {} }); engine.teammates.load();
  const { calls } = mainTeammate(engine, async () => { throw new Error('The model must not run again'); });
  const receipt = { runId: 'saved-draft', routineId: 'followers', name: 'Follower check', threadId: 'chief', status: 'ok', text: 'Followers: 71', proof: null, at: new Date().toISOString() };
  fs.writeFileSync(engine.routineReceiptFile('chief'), JSON.stringify([{ ...receipt, messageContent: 'I found 71 followers.', messageOccurrence: 1 }]));
  assert.equal(await engine.deliverRoutine(receipt), true);
  assert.equal(calls.length, 0);
  assert.equal(engine.loadThread('chief')[0].content, 'I found 71 followers.');
  assert.equal(engine.loadThread('chief')[0].job.runId, receipt.runId);
  assert.deepEqual(engine.routineDeliveryIds('chief'), [receipt.runId]);
});

test('the scheduled handoff reserves the main teammate while it writes', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'job-compose-lock-')); t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const engine = new DesktopEngine({ teammateFile: path.join(dir, 'teammates.json'), sessionsDir: dir, config: {}, mcp: {} }); engine.teammates.load();
  let release, entered;
  const began = new Promise(resolve => { entered = resolve; });
  mainTeammate(engine, () => { entered(); return new Promise(resolve => { release = resolve; }); });
  const receipt = { runId: 'locked', routineId: 'followers', name: 'Follower check', threadId: 'chief', status: 'ok', text: 'Followers: 71', proof: null, at: new Date().toISOString() };
  const delivery = engine.deliverRoutine(receipt);
  await began;
  await assert.rejects(engine.send('chief', 'A new request'), /already replying/);
  release('I found 71 followers.');
  assert.equal(await delivery, true);
  assert.equal(engine.loadThread('chief').length, 1);
});

test('the teammate turn is reserved before start listeners can send a second request', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'job-compose-event-lock-')); t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  let attempted;
  const engine = new DesktopEngine({ teammateFile: path.join(dir, 'teammates.json'), sessionsDir: dir, config: {}, mcp: {}, emit: event => {
    if (event.type === 'turn-start' && event.source === 'routine') attempted = engine.send('chief', 'Another request');
  } }); engine.teammates.load();
  mainTeammate(engine);
  const receipt = { runId: 'event-lock', routineId: 'followers', name: 'Follower check', threadId: 'chief', status: 'ok', text: 'Followers: 71', proof: null, at: new Date().toISOString() };
  await engine.deliverRoutine(receipt);
  await assert.rejects(attempted, /already replying/);
  assert.equal(engine.loadThread('chief').length, 1);
});

test('equal teammate wording still restores each run with its own proof', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'job-equal-replies-')); t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const engine = new DesktopEngine({ teammateFile: path.join(dir, 'teammates.json'), sessionsDir: dir, config: {}, mcp: {} }); engine.teammates.load();
  mainTeammate(engine);
  const base = { routineId: 'followers', name: 'Follower check', threadId: 'chief', status: 'ok', text: 'Followers: 71', proof: null, at: new Date().toISOString() };
  await engine.deliverRoutine({ ...base, runId: 'first' });
  await engine.deliverRoutine({ ...base, runId: 'second' });
  const restored = new DesktopEngine({ teammateFile: path.join(dir, 'teammates.json'), sessionsDir: dir, config: {}, mcp: {} }); restored.teammates.load();
  assert.deepEqual(restored.loadThread('chief').map(message => message.job?.runId), ['first', 'second']);
});
