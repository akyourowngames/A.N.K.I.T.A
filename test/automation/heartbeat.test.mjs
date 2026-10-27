import test from 'node:test';
import assert from 'node:assert/strict';
import { HEARTBEAT_CARD_INSTRUCTIONS, heartbeatContext, heartbeatPolicy, parseHeartbeat, substantive } from '../../src/automation/heartbeat.mjs';
import { DEFAULT_HEARTBEAT_BUDGET, HEARTBEAT_COOLDOWN_MINUTES, HEARTBEAT_MAX_TOKENS_PER_DAY, heartbeatRunLabel, normalizeRoutine } from '../../src/automation/job-policy.mjs';

const NOW = new Date('2026-10-26T12:00:00Z');
const card = (patch = {}) => JSON.stringify({ v: 1, status: 'notable', title: 'Deadline', summary: 'The report is due in two hours.', dedupe_key: 'report-due', evidence: ['calendar'], state: { due: 'today' }, ...patch });
const fenced = value => `\`\`\`heartbeat-card\n${value}\n\`\`\``;
const state = (patch = {}) => ({ v: 1, day: '2026-10-26', sent: 1, last: null, recent: [], held: [], ...patch });
const at = offsetMs => new Date(NOW.getTime() + offsetMs);

test('the silence marker survives an added sentence and boilerplate never becomes an update', () => {
  for (const answer of ['HEARTBEAT_OK', 'HEARTBEAT_OK\nAll good here.', 'HEARTBEAT_OK — nothing new.  ', '  \nHEARTBEAT_OK  \n', 'Job finished without a summary.', 'Nothing to report.', '   ']) {
    assert.equal(parseHeartbeat(answer).quiet, true, JSON.stringify(answer));
  }
  assert.equal(substantive('Noted'), false);
  assert.equal(substantive('The report moved to Friday.'), true);
});

test('a structured card keeps its status, stable key, evidence and bounded state', () => {
  const parsed = parseHeartbeat(fenced(card()));
  assert.equal(parsed.quiet, false);
  assert.equal(parsed.card.status, 'notable');
  assert.equal(parsed.card.key, 'report-due');
  assert.deepEqual(parsed.card.evidence, ['calendar']);
  assert.deepEqual(parsed.card.state, { due: 'today' });
  assert.equal(parsed.card.confidence, null);
  const oversized = parseHeartbeat(fenced(card({ state: { blob: 'x'.repeat(2000) }, evidence: Array.from({ length: 9 }, (_, index) => `source-${index}`) })));
  assert.equal(oversized.card.state, null); assert.equal(oversized.card.evidence.length, 6);
});

test('a corrupt or empty card is silence, while plain heartbeat text still works', () => {
  assert.equal(parseHeartbeat(fenced('{not json')).quiet, true);
  assert.equal(parseHeartbeat(fenced(card({ summary: 'ok' }))).quiet, true);
  assert.equal(parseHeartbeat(fenced(card({ status: 'quiet' }))).quiet, true);
  const legacy = parseHeartbeat('Two bills are due tomorrow.');
  assert.equal(legacy.quiet, false); assert.equal(legacy.card.status, 'notable'); assert.match(legacy.card.key, /bills/);
});

test('the same dedupe key is delivered once and becomes eligible after the cooldown', () => {
  const parsed = parseHeartbeat(fenced(card()));
  const first = heartbeatPolicy({ heartbeatState: state({ sent: 0 }) }, parsed, { now: NOW, timeZone: 'UTC' });
  assert.equal(first.action, 'deliver');
  assert.equal(first.text, 'Deadline\nThe report is due in two hours.');
  const repeat = heartbeatPolicy({ heartbeatState: first.state }, parsed, { now: at(60 * 60_000), timeZone: 'UTC' });
  assert.equal(repeat.action, 'quiet'); assert.equal(repeat.reason, 'duplicate');
  const later = heartbeatPolicy({ heartbeatState: first.state }, parsed, { now: at(HEARTBEAT_COOLDOWN_MINUTES * 60_000 + 1), timeZone: 'UTC' });
  assert.equal(later.action, 'deliver');
});

test('quiet hours hold notable and urgent cards, then one quiet check flushes the digest', () => {
  const notable = parseHeartbeat(fenced(card()));
  const urgent = parseHeartbeat(fenced(card({ status: 'urgent', title: 'Payment failed', summary: 'The card was declined for rent.', dedupe_key: 'rent-declined' })));
  const night = { now: new Date('2026-10-26T23:00:00Z'), timeZone: 'UTC', quietHours: '22:00-07:00' };
  const heldNotable = heartbeatPolicy({ heartbeatState: state() }, notable, night);
  assert.equal(heldNotable.action, 'held'); assert.equal(heldNotable.reason, 'quiet-hours');
  const heldUrgent = heartbeatPolicy({ heartbeatState: heldNotable.state }, urgent, { ...night, now: new Date('2026-10-26T23:30:00Z') });
  assert.equal(heldUrgent.action, 'held'); assert.equal(heldUrgent.state.held.length, 2);
  const morning = heartbeatPolicy({ heartbeatState: heldUrgent.state }, parseHeartbeat('HEARTBEAT_OK'), { now: new Date('2026-10-27T07:30:00Z'), timeZone: 'UTC', quietHours: '22:00-07:00' });
  assert.equal(morning.action, 'digest');
  assert.match(morning.text, /While you were away:/); assert.match(morning.text, /\[urgent\] Payment failed/); assert.match(morning.text, /The report is due/);
  assert.deepEqual(morning.state.held, []); assert.equal(morning.state.recent.length, 2);
  assert.ok(morning.state.recent.every(item => item.at === '2026-10-27T07:30:00.000Z'), 'reported keys restart the cooldown at delivery time');
});

test('the daily limit holds new updates, urgent bypasses it, and a new day resets it', () => {
  const parsed = parseHeartbeat(fenced(card()));
  const full = state({ sent: 4 });
  const held = heartbeatPolicy({ heartbeatState: full }, parsed, { now: NOW, timeZone: 'UTC' });
  assert.equal(held.action, 'held'); assert.equal(held.reason, 'daily-limit'); assert.equal(held.state.held.length, 1);
  const urgent = parseHeartbeat(fenced(card({ status: 'urgent', dedupe_key: 'rent-declined', summary: 'The card was declined for rent.' })));
  assert.equal(heartbeatPolicy({ heartbeatState: full }, urgent, { now: NOW, timeZone: 'UTC' }).action, 'deliver');
  assert.equal(heartbeatPolicy({ heartbeatState: { ...full, day: '2026-10-25' } }, parsed, { now: NOW, timeZone: 'UTC' }).action, 'deliver');
});

test('the heartbeat knows its own job and how to read a superseded failure', () => {
  const context = heartbeatContext({ id: 'job-watch', name: 'Job watch' }, { now: NOW, timeZone: 'UTC' });
  assert.match(context, /"job":\{"id":"job-watch","name":"Job watch"\}/);
  assert.match(HEARTBEAT_CARD_INSTRUCTIONS, /a failed receipt for that job is your own previous check/, 'A self-failure must not read as another job failing');
  assert.match(HEARTBEAT_CARD_INSTRUCTIONS, /enabled=true and no pausedReason is running normally/, 'A recovered job is live state, not a current outage');
  assert.match(HEARTBEAT_CARD_INSTRUCTIONS, /quote only limits the list shows/, 'A predicted reset or invented ceiling stays out of the report');
});

test('a new update merges earlier held items and the context carries structured state', () => {
  const parsed = parseHeartbeat(fenced(card()));
  const delivered = heartbeatPolicy({ heartbeatState: state({ sent: 0 }) }, parsed, { now: NOW, timeZone: 'UTC' });
  const context = heartbeatContext({ heartbeatState: delivered.state }, { now: at(30 * 60_000), timeZone: 'UTC' });
  assert.match(context, /"state":\{"due":"today"\}/); assert.match(context, /"recentKeys":\["report-due"\]/); assert.match(context, /"sentToday":1/);
  const held = state({ sent: 1, held: [{ at: NOW.toISOString(), key: 'old-news', title: '', summary: 'A package will arrive tomorrow.', status: 'notable' }] });
  const merged = heartbeatPolicy({ heartbeatState: held }, parseHeartbeat(fenced(card({ dedupe_key: 'new-topic', title: '', summary: 'The meeting moved to noon.' }))), { now: NOW, timeZone: 'UTC' });
  assert.equal(merged.action, 'deliver');
  assert.match(merged.text, /The meeting moved to noon\./); assert.match(merged.text, /Also earlier:\n- A package will arrive tomorrow\./);
  assert.deepEqual(merged.state.held, []);
  assert.deepEqual(merged.state.recent.map(item => item.key), ['old-news', 'new-topic'], 'merged items also enter the cooldown');
});

test('the job card explains a silent check in plain words', () => {
  assert.equal(heartbeatRunLabel('quiet', 'marker'), 'Checked — nothing to report');
  assert.equal(heartbeatRunLabel('quiet', 'empty'), 'Checked — nothing to report');
  assert.equal(heartbeatRunLabel('quiet', 'duplicate'), 'Checked — already reported');
  assert.equal(heartbeatRunLabel('held', 'quiet-hours'), 'Held for quiet hours');
  assert.equal(heartbeatRunLabel('held', 'daily-limit'), 'Held — daily limit reached');
  assert.equal(heartbeatRunLabel('ok', 'deliver'), null, 'A delivered run keeps the generic status label');
  assert.equal(heartbeatRunLabel(null, null), null);
});

test('a heartbeat budget is a runaway gate sized for a full day at the fastest useful cadence', () => {
  const fresh = normalizeRoutine({ kind: 'heartbeat', cron: '*/30 * * * *', prompt: 'Watch my jobs' });
  assert.deepEqual(fresh.budget, DEFAULT_HEARTBEAT_BUDGET);
  assert.ok(DEFAULT_HEARTBEAT_BUDGET.maxRunsPerDay > 288, 'A five-minute cadence (288 checks) plus manual runs fits');
  assert.ok(DEFAULT_HEARTBEAT_BUDGET.maxTokensPerDay >= 288 * 12_100, 'A day of measured ~12k checks fits under the ceiling');
  const legacy = normalizeRoutine({ kind: 'heartbeat', cron: '*/30 * * * *', prompt: 'Watch', budget: { maxRunsPerDay: 48, maxTokensPerDay: 50000, maxMinutesPerDay: 60 } });
  assert.equal(legacy.budget.maxTokensPerDay, HEARTBEAT_MAX_TOKENS_PER_DAY, 'An untouched legacy budget was never a user choice, so it migrates');
  const earlier = normalizeRoutine({ kind: 'heartbeat', cron: '*/30 * * * *', prompt: 'Watch', budget: { maxRunsPerDay: 60, maxTokensPerDay: 1_200_000, maxMinutesPerDay: 60 } });
  assert.equal(earlier.budget.maxTokensPerDay, HEARTBEAT_MAX_TOKENS_PER_DAY, 'The earlier cadence-sized default migrates too');
  const custom = normalizeRoutine({ kind: 'heartbeat', cron: '*/30 * * * *', prompt: 'Watch', budget: { maxTokensPerDay: 5000 } });
  assert.equal(custom.budget.maxTokensPerDay, 5000, 'A budget the user actually set is kept');
  assert.equal(normalizeRoutine({ prompt: 'Read' }).budget.maxTokensPerDay, 50000, 'Regular jobs keep the generic ceiling');
});
