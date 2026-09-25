import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  parseCron,
  matchCron,
  describeCron,
  normalizeSchedule,
  parseDuration,
  formatDuration,
} from '../../src/automation/cron.mjs';
import { RoutineStore, numericDelta, toNumber, hashContent } from '../../src/automation/routines.mjs';
import { extractValue, formatWatchStatus } from '../../src/automation/watcher.mjs';
import { splitMessage, updateToJob, parseChatIds, TG_LIMIT } from '../../src/channels/telegram.mjs';
import { Daemon, parseApproval, stripAnsi } from '../../src/automation/daemon.mjs';
import { bucketNotifications, formatNotification, tokenCandidates } from '../../tools/github/github-notifications.mjs';

function tmpStore(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-state-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return new RoutineStore(path.join(dir, 'state.json')).load();
}

test('cron parses fields, steps, ranges and aliases', () => {
  assert.equal(normalizeSchedule('@daily'), '0 0 * * *');
  assert.equal(normalizeSchedule('every 30m'), '*/30 * * * *');
  assert.equal(normalizeSchedule('every 2h'), '0 */2 * * *');
  assert.equal(normalizeSchedule('daily 08:00'), '0 8 * * *');
  assert.equal(normalizeSchedule('daily 9:05pm'), '5 21 * * *');
  assert.equal(normalizeSchedule('weekdays 09:30'), '30 9 * * 1-5');
  assert.equal(normalizeSchedule('0 8 * * 1-5'), '0 8 * * 1-5');
  assert.equal(normalizeSchedule('not a schedule'), null);
  assert.equal(parseCron('99 0 * * *'), null);
  assert.equal(parseCron('0 0 32 * *'), null);
});

test('cron matching is minute-accurate and day-fields follow cron rules', () => {
  const monday = new Date(2026, 8, 21, 8, 0, 30); // Mon 21 Sep 2026 08:00
  assert.equal(matchCron('0 8 * * *', monday), true);
  assert.equal(matchCron('0 8 * * 1', monday), true);
  assert.equal(matchCron('0 8 * * 0', monday), false);
  assert.equal(matchCron('30 8 * * *', monday), false);
  // dom or dow when both are restricted
  assert.equal(matchCron('0 8 21 * 0', monday), true);
  assert.equal(matchCron('0 8 22 * 0', monday), false);
  // steps
  assert.equal(matchCron('*/30 * * * *', new Date(2026, 8, 21, 8, 30)), true);
  assert.equal(matchCron('*/30 * * * *', new Date(2026, 8, 21, 8, 31)), false);
});

test('describeCron reads like a schedule', () => {
  assert.equal(describeCron('0 8 * * *'), 'daily at 08:00');
  assert.equal(describeCron('30 9 * * 1-5'), 'weekdays at 09:30');
  assert.equal(describeCron('*/15 * * * *'), 'every 15 minutes');
  assert.equal(describeCron('0 */2 * * *'), 'every 2 hours');
  assert.equal(describeCron('nonsense'), 'invalid schedule');
});

test('durations parse and format round-trip', () => {
  assert.equal(parseDuration('15m'), 900000);
  assert.equal(parseDuration('2h'), 7200000);
  assert.equal(parseDuration('1d'), 86400000);
  assert.equal(parseDuration('bogus', 42), 42);
  assert.equal(formatDuration(90000), '2m');
  assert.equal(formatDuration(7200000), '2h');
});

test('routines persist, dedupe ids, and only fire when due', (t) => {
  const store = tmpStore(t);
  const routine = store.addRoutine({ name: 'Morning briefing', cron: 'daily 08:00', prompt: 'brief me' });
  assert.equal(routine.id, 'morning-briefing');
  const second = store.addRoutine({ name: 'Morning briefing', cron: '0 9 * * *', prompt: 'again' });
  assert.equal(second.id, 'morning-briefing-2');

  assert.throws(() => store.addRoutine({ cron: 'nope', prompt: 'x' }), /invalid schedule/);
  assert.throws(() => store.addRoutine({ cron: '0 8 * * *', prompt: '' }), /prompt is required/);

  const due = new Date(2026, 8, 21, 8, 0, 10);
  assert.deepEqual(store.dueRoutines(due).map((r) => r.id), ['morning-briefing']);
  // same minute again: already fired
  store.markRoutineRun('morning-briefing', { status: 'ok', summary: 'hi', at: due.toISOString() });
  assert.deepEqual(store.dueRoutines(due).map((r) => r.id), []);
  // next day
  assert.deepEqual(store.dueRoutines(new Date(2026, 8, 22, 8, 0, 5)).map((r) => r.id), ['morning-briefing']);

  store.setRoutineEnabled('morning-briefing', false);
  assert.deepEqual(store.dueRoutines(new Date(2026, 8, 23, 8, 0, 5)).map((r) => r.id), []);
});

test('a routine can be queued to run once, ignoring its cron', (t) => {
  const store = tmpStore(t);
  store.addRoutine({ name: 'Ping', cron: 'daily 08:00', prompt: 'ping' });
  assert.deepEqual(store.dueRoutines(new Date(2026, 8, 21, 3, 0)).map((r) => r.id), []);
  store.scheduleRoutineNow('ping');
  const due = store.dueRoutines(new Date(Date.now() + 1000));
  assert.deepEqual(due.map((r) => r.id), ['ping']);
  store.clearRunAt('ping');
  assert.deepEqual(store.dueRoutines(new Date(Date.now() + 1000)).map((r) => r.id), []);
});

test('watches store readings, detect change and compute deltas', (t) => {
  const store = tmpStore(t);
  const watch = store.addWatch({ name: 'Signups', url: 'https://ex.test/dash', regex: '([\\d,]+) users', interval: '30m' });
  assert.equal(watch.id, 'signups');
  assert.throws(() => store.addWatch({ url: 'ftp://x.test' }), /http/);
  assert.throws(() => store.addWatch({ url: 'https://x.test', interval: '10s' }), /at least 15s/);

  const first = store.recordWatchCheck('signups', { value: '1,204', text: '1,204 users' });
  assert.equal(first.changed, false, 'first reading is a baseline, not a change');
  assert.equal(first.delta, null);

  const same = store.recordWatchCheck('signups', { value: '1,204', text: '1,204 users' });
  assert.equal(same.changed, false);

  const moved = store.recordWatchCheck('signups', { value: '1,227', text: '1,227 users' });
  assert.equal(moved.changed, true);
  assert.equal(moved.delta, 23);
  assert.equal(store.findWatch('signups').changes, 1);

  const errored = store.recordWatchCheck('signups', { error: 'boom' });
  assert.equal(errored.changed, false);
  assert.equal(store.findWatch('signups').lastError, 'boom');

  assert.equal(store.removeWatch('signups').name, 'Signups');
  assert.equal(store.findWatch('signups'), null);
});

test('whole-page watches notice edits even without a value', (t) => {
  const store = tmpStore(t);
  store.addWatch({ name: 'Status', url: 'https://ex.test/status' });
  store.recordWatchCheck('status', { value: null, text: 'all systems ok' });
  const changed = store.recordWatchCheck('status', { value: null, text: 'degraded performance' });
  assert.equal(changed.changed, true);
  assert.equal(changed.delta, null);
  assert.equal(hashContent('a'), hashContent('a'));
  assert.notEqual(hashContent('a'), hashContent('b'));
});

test('watch due times respect the interval', (t) => {
  const store = tmpStore(t);
  store.addWatch({ name: 'x', url: 'https://ex.test/', interval: '1h' });
  const now = new Date();
  assert.equal(store.dueWatches(now).length, 1, 'never checked = due');
  store.recordWatchCheck('x', { value: null, text: 'page' });
  assert.equal(store.dueWatches(now).length, 0);
  // 10s of slack: the check above takes a few ms, so a 1ms margin is a flake.
  assert.equal(store.dueWatches(new Date(now.getTime() + 3610000)).length, 1);
  assert.equal(store.dueWatches(new Date(now.getTime() + 3590000)).length, 0, 'not due before the interval');
});

test('alerts are rate-limited so a busy number cannot spam', (t) => {
  const store = tmpStore(t);
  const w = store.addWatch({ name: 'busy', url: 'https://ex.test/', interval: '20s' });
  assert.equal(w.alertCooldownMs, 600000, 'default 10m cooldown');
  assert.throws(() => store.addWatch({ name: 'fast', url: 'https://ex.test/', interval: '5s' }), /at least 15s/);

  const t0 = new Date('2026-09-21T08:00:00Z');
  assert.equal(store.shouldAlert(w, t0), true, 'never alerted yet');

  store.markAlerted('busy', t0.toISOString());
  assert.equal(store.shouldAlert(store.findWatch('busy'), new Date(t0.getTime() + 60000)), false, 'inside cooldown');
  assert.equal(store.shouldAlert(store.findWatch('busy'), new Date(t0.getTime() + 600001)), true, 'after cooldown');

  const always = store.addWatch({ name: 'always', url: 'https://ex.test/', alertEvery: '0s' });
  assert.equal(always.alertCooldownMs, 0);
  store.markAlerted('always', t0.toISOString());
  assert.equal(store.shouldAlert(store.findWatch('always'), t0), true, '0 disables the cooldown');
  assert.equal(store.shouldAlert(store.findWatch('always'), t0), true, 'and stays disabled');
});

test('value extraction uses capture group 1 and fails loudly', () => {
  assert.equal(extractValue('Signups: 1,204 users right now', '([\\d,]+)\\s+users').value, '1,204');
  assert.equal(extractValue('no numbers here', '([\\d,]+)').error, 'pattern not found on the page');
  assert.match(extractValue('x', '([unclosed').error, /invalid regex/);
  const plain = extractValue('just text');
  assert.equal(plain.value, null);
  assert.equal(plain.digestSource, 'just text');
});

test('numbers and deltas handle separators and junk', () => {
  assert.equal(toNumber('1,204'), 1204);
  assert.equal(toNumber(' 12 '), 12);
  assert.equal(toNumber('1.5'), 1.5);
  assert.equal(toNumber('n/a'), null);
  assert.equal(toNumber(null), null);
  assert.equal(numericDelta('1,204', '1,227'), 23);
  assert.equal(numericDelta('10', '4'), -6);
  assert.equal(numericDelta('ten', '4'), null);
});

test('watch status lines read like an alert', () => {
  const watch = { name: 'Signups' };
  assert.equal(formatWatchStatus(watch, { changed: true, delta: 23, value: '1,227', previous: '1,204' }),
    'Signups: 1,204 \u2192 1,227 (+23)');
  assert.equal(formatWatchStatus(watch, { changed: false, value: '1,204' }), 'Signups: unchanged (1,204)');
  assert.equal(formatWatchStatus(watch, { error: 'nope' }), 'Signups: nope');
});

test('telegram messages split on natural boundaries within the limit', () => {
  assert.deepEqual(splitMessage(''), []);
  assert.deepEqual(splitMessage('short'), ['short']);
  const long = ('word '.repeat(2000)).trim();
  const parts = splitMessage(long);
  assert.ok(parts.length > 1);
  for (const part of parts) assert.ok(part.length <= TG_LIMIT, `part too long: ${part.length}`);
  assert.equal(parts.join(' ').replace(/\s+/g, ' '), long.replace(/\s+/g, ' '));
  const para = `${'a'.repeat(3000)}\n\n${'b'.repeat(3000)}`;
  assert.equal(splitMessage(para)[0].length, 3000, 'splits on the paragraph break');
});

test('telegram updates map to jobs, including voice notes', () => {
  const text = updateToJob({ update_id: 1, message: { message_id: 5, chat: { id: 42 }, from: { username: 'krish' }, text: ' hi ' } });
  assert.deepEqual(text, { chatId: 42, from: 'krish', kind: 'text', text: 'hi', messageId: 5 });

  const voice = updateToJob({ update_id: 2, message: { message_id: 6, chat: { id: 42 }, voice: { file_id: 'F1', duration: 3 } } });
  assert.equal(voice.kind, 'voice');
  assert.equal(voice.fileId, 'F1');

  assert.equal(updateToJob({ update_id: 3 }), null);
  assert.equal(updateToJob({ update_id: 4, message: { chat: { id: 1 }, photo: [] } }), null);
  assert.deepEqual(parseChatIds('123, -456 789'), [123, -456, 789]);
});

test('daemon runs due routines and delivers, and alerts on watch changes', async (t) => {
  const store = tmpStore(t);
  store.addRoutine({ name: 'Brief', cron: 'daily 08:00', prompt: 'brief me' });
  store.addWatch({ name: 'Signups', url: 'https://ex.test/', regex: '([\\d,]+) users' });

  const delivered = [];
  const daemon = new Daemon({
    store,
    bot: null,
    config: { autoApprove: false },
    client: {},
    runPrompt: async () => 'the morning report',
    deliver: async (text, meta) => delivered.push({ text, meta }),
    now: () => new Date(2026, 8, 21, 8, 0, 5),
  });
  daemon.checkDueWatches = async () => ({ checked: 0, alerted: 0 });

  await daemon.runDueRoutines();
  assert.equal(delivered.length, 1);
  assert.match(delivered[0].text, /Morning|Brief/);
  assert.match(delivered[0].text, /the morning report/);
  assert.equal(store.findRoutine('brief').lastStatus, 'ok');
  assert.equal(store.findRoutine('brief').runs, 1);
  assert.equal(daemon.stats.routinesRun, 1);

  // second pass in the same minute must not re-deliver
  await daemon.runDueRoutines();
  assert.equal(delivered.length, 1);
});

test('github notifications bucket into triage groups', () => {
  const items = [
    { reason: 'review_requested', repository: { full_name: 'a/b' }, subject: { type: 'PullRequest', title: 'Fix' } },
    { reason: 'mention', repository: { full_name: 'a/b' }, subject: { type: 'Issue', title: 'Ping' } },
    { reason: 'mention', repository: { full_name: 'c/d' }, subject: { type: 'Issue', title: 'Ping 2' } },
    { reason: 'subscribed', repository: { full_name: 'c/d' }, subject: { type: 'Issue', title: 'Chatter' } },
  ];
  const buckets = bucketNotifications(items);
  assert.equal(buckets.review_requested.length, 1);
  assert.equal(buckets.mention.length, 2);
  assert.equal(buckets.other.length, 1);
  const line = formatNotification(items[0]);
  assert.match(line, /\[review_requested\] PullRequest - Fix/);
  assert.match(line, /a\/b/);
});

test('github token candidates are deduped and never empty strings', () => {
  const previous = { GITHUB_TOKEN: process.env.GITHUB_TOKEN, GH_TOKEN: process.env.GH_TOKEN };
  process.env.GITHUB_TOKEN = 'from-env';
  delete process.env.GH_TOKEN;
  try {
    const list = tokenCandidates();
    assert.ok(list.includes('from-env'));
    assert.ok(list.every((t) => typeof t === 'string' && t.length > 0));
    assert.equal(new Set(list).size, list.length, 'no duplicates');
  } finally {
    for (const [k, v] of Object.entries(previous)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
});

test('the daemon picks up routines added while it is already running', async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-live-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'state.json');
  const store = new RoutineStore(file).load();

  const delivered = [];
  const daemon = new Daemon({
    store,
    config: {},
    client: {},
    model: 'gpt-4.1',
    runPrompt: async () => 'ran it',
    deliver: async (text) => delivered.push(text),
    now: () => new Date(2026, 8, 21, 8, 0, 5),
  });
  daemon.checkDueWatches = async () => ({ checked: 0, alerted: 0 });
  daemon.pollInbox = async () => 0;

  await daemon.tickOnce();
  assert.equal(delivered.length, 0, 'nothing scheduled yet');

  // Another process (the REPL, or the agent's own schedule tool) writes state.
  new RoutineStore(file).load().addRoutine({ name: 'Later', cron: '0 8 * * *', prompt: 'go' });

  await daemon.tickOnce();
  await daemon.drain(); // tickOnce returns once work is dispatched, not finished
  assert.equal(delivered.length, 1, 'the daemon noticed without a restart');
  assert.match(delivered[0], /ran it/);
});

test('state written by a tool mid-routine survives the daemon bookkeeping', async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-clobber-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'state.json');
  const store = new RoutineStore(file).load();
  store.addRoutine({ name: 'Watcher', cron: 'daily 08:00', prompt: 'add a watch' });

  const daemon = new Daemon({
    store,
    config: {},
    client: {},
    model: 'gpt-4.1',
    // Stands in for the agent calling the `watch` tool, which owns its own store.
    runPrompt: async () => {
      new RoutineStore(file).load().addWatch({ name: 'created by agent', url: 'https://ex.test/' });
      return 'added the watch';
    },
    deliver: async () => {},
    now: () => new Date(2026, 8, 21, 8, 0, 5),
  });
  daemon.checkDueWatches = async () => ({ checked: 0, alerted: 0 });
  daemon.pollInbox = async () => 0;

  await daemon.runDueRoutines();

  const after = new RoutineStore(file).load();
  assert.equal(after.watches.length, 1, 'the agent-created watch was not overwritten');
  assert.equal(after.watches[0].name, 'created by agent');
  assert.equal(after.routines.length, 1, 'and the routine is still there');
  assert.equal(after.findRoutine('watcher').lastStatus, 'ok');
});

test('daemon chat agents inherit the resolved model', (t) => {
  const store = tmpStore(t);
  const seen = [];
  const daemon = new Daemon({
    store,
    config: { autoApprove: false },
    client: {},
    model: 'gpt-4.1',
    runPrompt: async () => '',
    deliver: async () => {},
  });
  // Stub the Agent construction path by checking what chatAgent would set.
  const agent = daemon.chatAgent(42);
  assert.equal(agent.model, 'gpt-4.1', 'chat agent must not send model:null');
  assert.equal(daemon.chatAgent(42), agent, 'same chat reuses one agent');
  assert.notEqual(daemon.chatAgent(43), agent, 'different chats get their own agent');
  seen.push(daemon.model);
  assert.deepEqual(seen, ['gpt-4.1']);
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

function daemonWith(t, bot, extra = {}) {
  return new Daemon({
    store: tmpStore(t),
    bot,
    config: { autoApprove: false, telegramChatId: '7280190750', ...extra },
    client: {},
    model: 'gpt-4.1',
    runPrompt: async () => '',
    deliver: async () => {},
  });
}

test('approval timeout is read as seconds, with a sane floor', (t) => {
  const at = (seconds) => daemonWith(t, fakeBot(), { telegramConfirmTimeout: seconds }).confirmTimeoutMs;
  assert.equal(at(300), 300000, 'default 5 minutes');
  assert.equal(at(60), 60000);
  assert.equal(at(1), 30000, 'never below 30s or approvals become impossible');
  assert.equal(at(undefined), 300000);
});

test('approval replies parse the way people actually type them', () => {
  for (const yes of ['y', 'Y', 'yes', 'yeah', 'ok', 'sure', 'go', 'do it', 'Approved.']) {
    assert.equal(parseApproval(yes), 'yes', yes);
  }
  for (const always of ['a', 'always', 'A', 'always allow']) {
    assert.equal(parseApproval(always), 'always', always);
  }
  for (const no of ['n', 'no', 'nah', 'deny', 'stop', 'cancel', '', 'what?']) {
    assert.equal(parseApproval(no), 'no', JSON.stringify(no));
  }
  assert.equal(stripAnsi('\u001b[31m-red\u001b[0m plain'), '-red plain');
});

test('a DM tool call asks in Telegram and honours the reply', async (t) => {
  const bot = fakeBot();
  const daemon = daemonWith(t, bot);
  const agent = daemon.chatAgent('7280190750');

  const decision = agent.confirm('run_command', '$ rm -rf build');
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(bot.sent.length, 1, 'the question was sent to the chat');
  assert.match(bot.sent[0].text, /Permission needed: run_command/);
  assert.match(bot.sent[0].text, /rm -rf build/);

  const consumed = daemon.resolvePending({ chatId: 7280190750, kind: 'text', text: 'y' });
  assert.equal(consumed, true, 'the reply is consumed, not treated as a new request');
  assert.equal(await decision, true);
});

test('answering "always" approves this call and the rest of the session', async (t) => {
  const bot = fakeBot();
  const daemon = daemonWith(t, bot);
  const agent = daemon.chatAgent('7280190750');

  const first = agent.confirm('write_file', 'create notes.txt');
  await new Promise((r) => setTimeout(r, 10));
  daemon.resolvePending({ chatId: 7280190750, kind: 'text', text: 'always' });
  assert.equal(await first, true);

  assert.equal(await agent.confirm('delete_file', 'delete notes.txt'), true, 'no second question');
  assert.equal(bot.sent.length, 1, 'nothing else was sent to the chat');
});

test('denying is a denial, and a question times out to denial', async (t) => {
  const bot = fakeBot();
  const daemon = daemonWith(t, bot, { telegramConfirmTimeout: undefined });
  daemon.confirmTimeoutMs = 40;
  const agent = daemon.chatAgent('7280190750');

  const denied = agent.confirm('delete_file', 'rm important.txt');
  await new Promise((r) => setTimeout(r, 10));
  daemon.resolvePending({ chatId: 7280190750, kind: 'text', text: 'n' });
  assert.equal(await denied, false);

  const timedOut = agent.confirm('run_command', 'sleep');
  assert.equal(await timedOut, false, 'no reply means no permission');
  assert.ok(bot.sent.some((m) => /No reply/.test(m.text)), 'and it says so');
});

test('voice notes cannot approve, and read-only work never asks', async (t) => {
  const bot = fakeBot();
  const daemon = daemonWith(t, bot);
  const agent = daemon.chatAgent('7280190750');

  const waiting = agent.confirm('run_command', 'x');
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(daemon.resolvePending({ chatId: 7280190750, kind: 'voice', fileId: 'F' }), true);
  assert.ok(bot.sent.some((m) => /Reply with text/.test(m.text)), 'it asks for a text answer');
  assert.ok(daemon.pending.has('7280190750'), 'still waiting: a voice note is not an approval');

  daemon.resolvePending({ chatId: 7280190750, kind: 'text', text: 'n' });
  assert.equal(await waiting, false);
});

test('the poll loop stays free while a turn waits for approval', async (t) => {
  const bot = fakeBot();
  // One approval request, then the approval reply on the next poll.
  let round = 0;
  bot.poll = async (offset) => {
    round++;
    if (round === 1) return { jobs: [{ chatId: 7280190750, kind: 'text', text: 'delete it', messageId: 1 }], denied: [], offset: 2, error: null };
    if (round === 2) return { jobs: [{ chatId: 7280190750, kind: 'text', text: 'y', messageId: 2 }], denied: [], offset: 3, error: null };
    return { jobs: [], denied: [], offset: 3, error: null };
  };

  const daemon = daemonWith(t, bot);
  daemon.offsetReady = true;
  let ran = null;
  daemon.handleJob = async (job) => {
    const agent = daemon.chatAgent(job.chatId);
    ran = job.text;
    await agent.confirm('run_command', 'rm -rf build');
    ran += ' -> allowed';
  };

  await daemon.pollInbox();               // receives the request, parks it
  await new Promise((r) => setTimeout(r, 20));
  await daemon.pollInbox();               // receives the approval while parked
  await daemon.drain();
  assert.equal(ran, 'delete it -> allowed', 'the turn resumed with permission');
});

test('a routine parked on approval still lets the inbox be polled', async (t) => {
  const store = tmpStore(t);
  store.addRoutine({ name: 'Needs permission', cron: 'daily 08:00', prompt: 'write a file' });

  const bot = fakeBot();
  let pollRounds = 0;
  bot.poll = async () => {
    pollRounds++;
    // Your reply is only waiting on the second poll, after the question is out.
    if (pollRounds >= 2) {
      return { jobs: [{ chatId: 7280190750, kind: 'text', text: 'y', messageId: 9 }], denied: [], offset: 3, error: null };
    }
    return { jobs: [], denied: [], offset: 2, error: null };
  };

  const delivered = [];
  const daemon = new Daemon({
    store,
    bot,
    config: { autoApprove: false, telegramChatId: '7280190750' },
    client: {},
    model: 'gpt-4.1',
    // Stands in for the agent: asks for approval, then reports.
    runPrompt: async () => {
      const allowed = await daemon.confirmOwner('write_file', 'create notes.txt');
      return allowed ? 'created it' : 'not allowed';
    },
    deliver: async (text) => delivered.push(text),
    now: () => new Date(2026, 8, 21, 8, 0, 5),
  });

  daemon.offsetReady = true; // skip the first-run backlog drain
  // The regression: tickOnce must return while the routine is still parked, so
  // the next poll can pick up the approval. Before the fix it awaited the work
  // and the answer could never arrive.
  await daemon.tickOnce();
  await waitFor(() => bot.sent.some((m) => /Permission needed: write_file/.test(m.text)));
  assert.equal(delivered.length, 0, 'routine is parked waiting for permission');

  await daemon.tickOnce();               // your "y" arrives here
  await waitFor(() => delivered.length === 1);
  await daemon.drain();
  assert.match(delivered[0], /created it/);
});

test('a stray "y" with nothing pending is answered, not fed to the model', async (t) => {
  const bot = fakeBot();
  bot.poll = async () => ({
    jobs: [{ chatId: 7280190750, kind: 'text', text: 'y', messageId: 3 }],
    denied: [],
    offset: 2,
    error: null,
  });
  const daemon = daemonWith(t, bot);
  daemon.offsetReady = true;
  let ran = false;
  daemon.handleJob = async () => { ran = true; };

  await daemon.pollInbox();
  await daemon.drain();
  assert.equal(ran, false, 'the model never saw it');
  assert.ok(
    bot.sent.some((m) => /Nothing is waiting for approval/.test(m.text)),
    'and the user is told why nothing happened'
  );
});

test('remote DMs cannot approve mutations unless auto-approve is on', async (t) => {
  const store = tmpStore(t);
  const build = (autoApprove) =>
    new Daemon({
      store,
      config: { autoApprove },
      client: {},
      model: 'gpt-4.1',
      runPrompt: async () => '',
      deliver: async () => {},
    }).chatAgent('42');

  let denied = false;
  const strict = build(false);
  await strict.runToolCall({ id: '1', type: 'function', function: { name: 'delete_file', arguments: JSON.stringify({ path: 'x' }) } })
    .then((r) => { denied = /denied permission/.test(r); });
  assert.equal(denied, true, 'a DM must not silently delete files');

  const permissive = await build(true).runToolCall({
    id: '2',
    type: 'function',
    function: { name: 'delete_file', arguments: JSON.stringify({ path: 'definitely-missing-file' }) },
  });
  assert.doesNotMatch(permissive, /denied permission/, 'auto-approve=on allows it through to the tool');
});

test('daemon records a failed routine instead of dying', async (t) => {
  const store = tmpStore(t);
  store.addRoutine({ name: 'Broken', cron: 'daily 08:00', prompt: 'x' });
  const daemon = new Daemon({
    store,
    config: {},
    client: {},
    runPrompt: async () => { throw new Error('model exploded'); },
    deliver: async () => {},
    now: () => new Date(2026, 8, 21, 8, 0, 5),
  });
  await daemon.runDueRoutines();
  assert.equal(store.findRoutine('broken').lastStatus, 'error');
  assert.match(store.findRoutine('broken').lastSummary, /model exploded/);
  assert.equal(daemon.stats.errors, 1);
});
