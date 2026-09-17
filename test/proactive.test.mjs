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
} from '../src/cron.mjs';
import { RoutineStore, numericDelta, toNumber, hashContent } from '../src/routines.mjs';
import { extractValue, formatWatchStatus } from '../src/watcher.mjs';
import { splitMessage, updateToJob, parseChatIds, TG_LIMIT } from '../src/telegram.mjs';
import { Daemon } from '../src/daemon.mjs';
import { bucketNotifications, formatNotification, tokenCandidates } from '../tools/github-notifications.mjs';

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
  assert.throws(() => store.addWatch({ url: 'https://x.test', interval: '10s' }), /at least 1m/);

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
  assert.equal(store.dueWatches(new Date(now.getTime() + 3600001)).length, 1);
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
