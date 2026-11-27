import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { sendHeartbeat, maybeSendHeartbeat, heartbeatDay, hashInstallId, HEARTBEAT_ENDPOINT, HEARTBEAT_ANON_KEY } from '../../desktop/electron/heartbeat.mjs';
import { DesktopSettingsStore } from '../../desktop/electron/settings.mjs';

const ENDPOINT = 'https://example.supabase.co';
const ANON_KEY = 'fixture-anon-key';

function tempFile(t, label) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), `ankita-heartbeat-${label}-`));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return path.join(dir, 'heartbeat.json');
}

function capturingFetch({ ok = true } = {}) {
  const calls = [];
  const fetchImpl = async (url, options) => { calls.push({ url, options }); return { ok }; };
  return { calls, fetchImpl };
}

test('the heartbeat is inert when the user has not opted in', async t => {
  const { calls, fetchImpl } = capturingFetch();
  const sent = await sendHeartbeat({ file: tempFile(t, 'off'), endpoint: ENDPOINT, anonKey: ANON_KEY, version: '2.7.5', enabled: false, fetchImpl });
  assert.equal(sent, false);
  assert.equal(calls.length, 0);
});

test('the heartbeat is inert until the endpoint is wired up', async t => {
  const { calls, fetchImpl } = capturingFetch();
  assert.equal(HEARTBEAT_ENDPOINT, '');
  assert.equal(HEARTBEAT_ANON_KEY, '');
  const sent = await sendHeartbeat({ file: tempFile(t, 'no-endpoint'), version: '2.7.5', enabled: true, fetchImpl });
  assert.equal(sent, false);
  assert.equal(calls.length, 0);
});

test('an opted-in install sends one anonymous ping a day, then stays quiet', async t => {
  const file = tempFile(t, 'daily');
  const { calls, fetchImpl } = capturingFetch();
  const dayOne = new Date('2026-11-27T10:00:00Z');
  assert.equal(await sendHeartbeat({ file, endpoint: ENDPOINT, anonKey: ANON_KEY, version: '2.7.5', platform: 'win32', enabled: true, fetchImpl, now: dayOne }), true);
  assert.equal(calls.length, 1);
  const call = calls[0];
  assert.equal(call.url, `${ENDPOINT}/rest/v1/heartbeats?on_conflict=install_id_hash,day`);
  assert.equal(call.options.method, 'POST');
  assert.equal(call.options.headers.apikey, ANON_KEY);
  assert.equal(call.options.headers.Authorization, `Bearer ${ANON_KEY}`);
  const body = JSON.parse(call.options.body);
  assert.equal(body.app_version, '2.7.5');
  assert.equal(body.platform, 'win32');
  assert.equal(body.day, '2026-11-27');
  assert.match(body.install_id_hash, /^[0-9a-f]{64}$/); // SHA-256 hex, never the raw ID.
  assert.equal(Object.keys(body).length, 4); // Nothing else is sent. Ever.
  const saved = JSON.parse(fs.readFileSync(file, 'utf8'));
  assert.equal(saved.lastPingDay, '2026-11-27');
  assert.equal(hashInstallId(saved.installId), body.install_id_hash);

  // Same day again: no second ping.
  assert.equal(await sendHeartbeat({ file, endpoint: ENDPOINT, anonKey: ANON_KEY, version: '2.7.5', platform: 'win32', enabled: true, fetchImpl, now: dayOne }), false);
  assert.equal(calls.length, 1);

  // Next day: one ping again, same install ID.
  assert.equal(await sendHeartbeat({ file, endpoint: ENDPOINT, anonKey: ANON_KEY, version: '2.7.5', platform: 'win32', enabled: true, fetchImpl, now: new Date('2026-11-28T10:00:00Z') }), true);
  assert.equal(calls.length, 2);
  assert.equal(JSON.parse(calls[1].options.body).install_id_hash, body.install_id_hash);
  assert.equal(JSON.parse(calls[1].options.body).day, '2026-11-28');
});

test('a failed ping is silent and does not mark the day as counted', async t => {
  const file = tempFile(t, 'failed');
  const failing = async () => { throw new Error('network down'); };
  const day = new Date('2026-11-27T10:00:00Z');
  assert.equal(await sendHeartbeat({ file, endpoint: ENDPOINT, anonKey: ANON_KEY, version: '2.7.5', enabled: true, fetchImpl: failing, now: day }), false);
  const saved = JSON.parse(fs.readFileSync(file, 'utf8'));
  assert.equal(saved.lastPingDay, ''); // Not counted: tomorrow tries again.
  assert.equal(saved.installId.length > 0, true);

  const { calls, fetchImpl } = capturingFetch({ ok: false });
  assert.equal(await sendHeartbeat({ file, endpoint: ENDPOINT, anonKey: ANON_KEY, version: '2.7.5', enabled: true, fetchImpl, now: day }), false);
  assert.equal(calls.length, 1);
  assert.equal(JSON.parse(fs.readFileSync(file, 'utf8')).lastPingDay, '');
});

test('a corrupt state file starts fresh instead of crashing', async t => {
  const file = tempFile(t, 'corrupt');
  fs.writeFileSync(file, '{not json');
  const { calls, fetchImpl } = capturingFetch();
  assert.equal(await sendHeartbeat({ file, endpoint: ENDPOINT, anonKey: ANON_KEY, version: '2.7.5', enabled: true, fetchImpl, now: new Date('2026-11-27T10:00:00Z') }), true);
  assert.equal(calls.length, 1);
  assert.equal(JSON.parse(fs.readFileSync(file, 'utf8')).lastPingDay, '2026-11-27');
});

test('maybeSendHeartbeat never throws and never blocks the caller', async t => {
  const throwing = () => { throw new Error('boom'); };
  assert.equal(await maybeSendHeartbeat({ file: tempFile(t, 'wrapper'), endpoint: ENDPOINT, anonKey: ANON_KEY, version: '2.7.5', enabled: true, fetchImpl: throwing }), false);
});

test('heartbeatDay uses the UTC calendar day', () => {
  assert.equal(heartbeatDay(new Date('2026-11-27T23:30:00Z')), '2026-11-27');
  assert.equal(heartbeatDay(new Date('2026-11-28T00:30:00Z')), '2026-11-28');
});

test('the usageHeartbeat setting is off unless the user turns it on', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-heartbeat-settings-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'desktop-settings.json');
  const store = new DesktopSettingsStore(file).load();
  assert.equal(store.publicView({}).usageHeartbeat, false);
  store.update({ usageHeartbeat: true });
  assert.equal(store.publicView({}).usageHeartbeat, true);
  assert.equal(JSON.parse(fs.readFileSync(file, 'utf8')).settings.usageHeartbeat, true);
  store.update({ usageHeartbeat: 'yes' }); // Not a real opt-in: anything but true stays off.
  assert.equal(store.publicView({}).usageHeartbeat, false);
});
