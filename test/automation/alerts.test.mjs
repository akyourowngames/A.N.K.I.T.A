import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { RoutineStore } from '../../src/automation/routines.mjs';
import { Daemon } from '../../src/automation/daemon.mjs';
import { buildAlertPrompt, renderAlertFallback, direction } from '../../src/automation/alerts.mjs';

function tmpStore(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-alerts-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return new RoutineStore(path.join(dir, 'state.json')).load();
}

const CHANGE = {
  watch: { id: 'active', name: 'Active users', url: 'http://127.0.0.1:4173', regex: 'Active users:\\s*([\\d,]+)' },
  previous: '1,305',
  value: '1,298',
  delta: -7,
};

test('direction reads a delta as a direction', () => {
  assert.equal(direction(5), 'rose');
  assert.equal(direction(-7), 'fell');
  assert.equal(direction(0), 'unchanged');
  assert.equal(direction(null), 'changed');
});

test('the alert prompt carries the name, both numbers, the delta and the direction', () => {
  const prompt = buildAlertPrompt({
    username: 'krish',
    agentName: 'ankita',
    changes: [CHANGE, { ...CHANGE, watch: { ...CHANGE.watch, id: 's', name: 'Signups today' }, previous: '335', value: '350', delta: 15 }],
  });
  assert.match(prompt, /krish/);
  assert.match(prompt, /Active users/);
  assert.match(prompt, /1,305 -> now 1,298/);
  assert.match(prompt, /change -7 \(fell\)/);
  assert.match(prompt, /Signups today/);
  assert.match(prompt, /change \+15 \(rose\)/);
  assert.match(prompt, /regex "Active users/);
  assert.match(prompt, /You cannot change anything/);
});

test('page excerpt is included when available and capped', () => {
  const long = 'x'.repeat(900);
  const prompt = buildAlertPrompt({
    username: 'krish',
    changes: [{ ...CHANGE, watch: { ...CHANGE.watch, lastText: long } }],
  });
  assert.match(prompt, /page says: x{100}/);
  assert.ok(prompt.length < 2000, 'excerpt must be capped, not the whole page');
});

test('a custom template overrides the built-in wording', () => {
  const prompt = buildAlertPrompt({
    username: 'krish',
    changes: [CHANGE],
    template: 'Yo {{username}}, {{count}} change(s):\n{{changes}}',
  });
  assert.match(prompt, /^Yo krish, 1 change\(s\):/);
  assert.match(prompt, /Active users/);
  assert.doesNotMatch(prompt, /Write the notification/);
});

test('the fallback always renders a complete notification', () => {
  const text = renderAlertFallback([CHANGE]);
  assert.match(text, /Active users: 1,305 \u2192 1,298 \(-7\)/);
  assert.match(text, /http:\/\/127\.0\.0\.1:4173/);
  const wholePage = renderAlertFallback([{ ...CHANGE, value: null, previous: null, delta: null }]);
  assert.match(wholePage, /page changed/);
});

/** Polls a condition so tests do not depend on microtask ordering. */
async function waitFor(predicate, timeoutMs = 2000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return true;
    await new Promise((r) => setTimeout(r, 5));
  }
  throw new Error('waitFor timed out');
}

function fakeBot() {
  const sent = [];
  return {
    enabled: true,
    sent,
    async send(chatId, text) { sent.push({ chatId: String(chatId), text }); return [{}]; },
    async sendTyping() {},
    async sendVoice() {},
    async poll() { return { jobs: [], denied: [], offset: 0, error: null }; },
  };
}

function daemonWith(t, extra = {}) {
  const store = tmpStore(t);
  store.addWatch({ name: 'Active users', url: 'https://ex.test/', regex: 'users:\\s*(\\d+)', interval: '20s' });
  store.addWatch({ name: 'Signups', url: 'https://ex.test/', regex: 'signups:\\s*(\\d+)', interval: '20s' });
  const prompts = [];
  const delivered = [];
  const daemon = new Daemon({
    store,
    bot: fakeBot(),
    config: { autoApprove: false, username: 'krish', agentName: 'ankita', ...extra.config },
    client: {},
    model: 'gpt-4.1',
    runPrompt: async (prompt, meta) => {
      prompts.push({ prompt, purpose: meta?.purpose });
      if (extra.onPrompt) return extra.onPrompt(prompt, meta);
      return 'Krish, active users dipped 7 to 1,298 - want me to dig in?';
    },
    deliver: async (text, meta) => delivered.push({ text, meta }),
    // recordWatchCheck uses real time. Advance past its interval rather than
    // freezing a date that eventually lies before every baseline reading.
    now: () => new Date(Date.now() + 60000),
  });
  daemon.pollInbox = async () => 0;
  return { daemon, store, prompts, delivered };
}

test('a tick with several changes sends exactly one composed message', async (t) => {
  const { daemon, prompts, delivered } = daemonWith(t);
  // Baselines, then a second reading that moved for both watches.
  for (const id of ['active-users', 'signups']) {
    daemon.store.recordWatchCheck(id, { value: id === 'signups' ? '335' : '1,305', text: 'users: 0' });
  }
  const next = { 'active-users': '1,298', signups: '350' };
  daemon.checker = async (watch) => ({ value: next[watch.id], text: `reading ${next[watch.id]}` });

  // Real path: dispatchWatches -> chain -> executeWatch -> flushAlerts.
  daemon.dispatchWatches();
  await waitFor(() => delivered.length > 0);

  assert.equal(prompts.length, 1, 'one prompt for the whole tick, not one per watch');
  assert.equal(prompts[0].purpose, 'alert');
  assert.match(prompts[0].prompt, /Active users/);
  assert.match(prompts[0].prompt, /Signups/);
  assert.match(prompts[0].prompt, /change -7 \(fell\)/);
  assert.match(prompts[0].prompt, /change \+15 \(rose\)/);
  assert.equal(delivered.length, 1, 'one message, not two');
  assert.equal(daemon.alertQueue.length, 0, 'queue drained');
});

test('a second tick inside the alert cooldown sends nothing', async (t) => {
  const { daemon, prompts, delivered } = daemonWith(t);
  daemon.store.removeWatch('signups'); // isolate: one watch, one baseline
  daemon.store.recordWatchCheck('active-users', { value: '1,305', text: 'x' });
  let n = 0;
  daemon.checker = async () => ({ value: String(1290 + n++), text: 'reading' });

  daemon.dispatchWatches();
  await waitFor(() => delivered.length > 0);

  // Same clock, so the cooldown still applies.
  daemon.dispatchWatches();
  await new Promise((r) => setTimeout(r, 40));
  assert.equal(delivered.length, 1, 'cooldown suppresses the repeat');
  assert.equal(prompts.length, 1);
});

test('a failing model still delivers a complete plain-text alert', async (t) => {
  const { daemon, delivered } = daemonWith(t, {
    onPrompt: async () => {
      throw new Error('model exploded');
    },
  });
  daemon.alertQueue.push(CHANGE);
  const mode = await daemon.flushAlerts();
  assert.equal(mode, 'fallback');
  assert.equal(delivered.length, 1, 'the change was not swallowed');
  assert.match(delivered[0].text, /Active users: 1,305 \u2192 1,298 \(-7\)/);
});

test('WATCH_ALERT_LLM=off skips the model entirely', async (t) => {
  const { daemon, prompts, delivered } = daemonWith(t, { config: { watchAlertLlm: false } });
  daemon.alertQueue.push(CHANGE);
  const mode = await daemon.flushAlerts();
  assert.equal(mode, 'fallback');
  assert.equal(prompts.length, 0, 'no model call at all');
  assert.equal(delivered.length, 1);
  assert.match(delivered[0].text, /Active users/);
});

test('an empty queue sends nothing', async (t) => {
  const { daemon, prompts, delivered } = daemonWith(t);
  assert.equal(await daemon.flushAlerts(), null);
  assert.equal(prompts.length, 0);
  assert.equal(delivered.length, 0);
});

test('failed alert enqueue retains changes and a later tick retries even without new watches', async t => {
  const { daemon, store, delivered } = daemonWith(t, { config: { watchAlertLlm: false } });
  store.removeWatch('active-users'); store.removeWatch('signups');
  let failed = true;
  daemon.deliver = async text => { if (failed) throw Error('queue busy'); delivered.push(text); };
  daemon.alertQueue.push(CHANGE);
  await assert.rejects(daemon.flushAlerts(), /queue busy/);
  assert.equal(daemon.alertQueue.length, 1);
  failed = false;
  await daemon.tickOnce();
  await daemon.drain();
  assert.equal(delivered.length, 1);
  assert.equal(daemon.alertQueue.length, 0);
});

test('alerts cannot mutate: mutations are declined, reads are allowed', async (t) => {
  const { daemon, store } = daemonWith(t);
  store.addRoutine({ name: 'touch', cron: 'daily 08:00', prompt: 'x' });

  // The confirm the CLI installs for alert-purpose agents.
  const alertConfirm = async () => false;
  const agent = daemon.chatAgent('999');
  agent.confirm = alertConfirm;

  const denied = await agent.runToolCall({
    id: '1',
    type: 'function',
    function: { name: 'delete_file', arguments: JSON.stringify({ path: 'important.txt' }) },
  });
  assert.match(denied, /denied permission/i, 'an alert must not delete anything');

  const written = await agent.runToolCall({
    id: '2',
    type: 'function',
    function: { name: 'write_file', arguments: JSON.stringify({ path: 'sneaky.txt', content: 'x' }) },
  });
  assert.match(written, /denied permission/i, 'an alert must not write anything');

  const read = await agent.runToolCall({
    id: '3',
    type: 'function',
    function: { name: 'list_dir', arguments: JSON.stringify({ path: '.', max_results: 3 }) },
  });
  assert.doesNotMatch(read, /denied permission/i, 'read-only work still runs');
});

test('a model that returns nothing falls back rather than sending an empty message', async (t) => {
  const { daemon, delivered } = daemonWith(t, { onPrompt: async () => '   ' });
  daemon.alertQueue.push(CHANGE);
  const mode = await daemon.flushAlerts();
  assert.equal(mode, 'fallback');
  assert.match(delivered[0].text, /Active users/, 'never deliver blank');
});
