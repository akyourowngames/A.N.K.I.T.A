import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const api = await import('../../src/automation/voice-resources.mjs').catch(() => ({}));
const tick = () => new Promise(resolve => setImmediate(resolve));
const file = (key, mode = 'write') => ({ kind: 'path', key, mode });

test('disjoint voice files overlap, but one read/modify/write sequence keeps its lease', async () => {
  const broker = new api.VoiceResourceBroker();
  await broker.acquire('first', [file('/workspace/poem.txt')]);
  await broker.acquire('other', [file('/workspace/research.md')]);
  let entered = false;
  const second = broker.acquire('second', [file('/workspace/poem.txt')]).then(() => { entered = true; });
  await tick(); assert.equal(entered, false);
  broker.release('first'); await second; assert.equal(entered, true);
  broker.release('second'); broker.release('other');
});

test('parent path leases conflict with descendants and cancelled waiters cannot steal them', async () => {
  const broker = new api.VoiceResourceBroker();
  await broker.acquire('shell', [file('/workspace')]);
  const controller = new AbortController();
  const blocked = broker.acquire('cancelled', [file('/workspace/file.txt')], { signal: controller.signal });
  controller.abort(); await assert.rejects(blocked, { name: 'AbortError' });
  broker.release('shell'); await broker.acquire('next', [file('/workspace/file.txt')]);
  broker.release('next'); assert.equal(broker.waitingCount, 0);
});

test('shared reads can overlap, but cyclic upgrades fail clearly instead of deadlocking', async () => {
  const broker = new api.VoiceResourceBroker();
  await broker.acquire('a', [file('/workspace/file.txt', 'read')]);
  await broker.acquire('b', [file('/workspace/file.txt', 'read')]);
  const upgrade = broker.acquire('a', [file('/workspace/file.txt')]);
  await assert.rejects(broker.acquire('b', [file('/workspace/file.txt')]), { code: 'VOICE_RESOURCE_CYCLE' });
  broker.release('b'); await upgrade; broker.release('a');
});

test('a shared interaction lease prevents two jobs interleaving an app', async () => {
  const broker = new api.VoiceResourceBroker();
  const ui = { kind: 'shared', key: 'desktop', mode: 'write' };
  await broker.acquire('a', [ui]);
  let next = false;
  const waiting = broker.acquire('b', [ui]).then(() => { next = true; });
  await tick(); assert.equal(next, false);
  broker.release('a'); await waiting; broker.release('b');
});

test('canonical paths fold existing aliases and new descendants using runtime discovery', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-resource-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, 'real'));
  fs.symlinkSync(path.join(root, 'real'), path.join(root, 'alias'), process.platform === 'win32' ? 'junction' : 'dir');
  assert.equal(api.canonicalVoicePath(path.join(root, 'alias', 'new.txt')), api.canonicalVoicePath(path.join(root, 'real', 'new.txt')));
  assert.equal(api.canonicalVoicePath(path.toNamespacedPath(path.join(root, 'real', 'new.txt'))), api.canonicalVoicePath(path.join(root, 'real', 'new.txt')));
});

test('a dangling file alias shares the future target identity rather than a second lock', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-future-alias-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const target = path.join(root, 'future.txt'), alias = path.join(root, 'alias.txt');
  try { fs.symlinkSync(target, alias, 'file'); }
  catch (error) { if (error.code === 'EPERM') { t.skip('This OS account cannot create a file symlink. Junction alias is covered separately.'); return; } throw error; }
  assert.equal(api.canonicalVoicePath(alias), api.canonicalVoicePath(target));
});

test('live shared-file increments preserve both changes while disjoint work completes', async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-rmw-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const target = path.join(root, 'count.txt'); fs.writeFileSync(target, '0');
  const broker = new api.VoiceResourceBroker();
  const increment = async id => {
    await broker.acquire(id, [file(api.canonicalVoicePath(target))]);
    try { const value = Number(fs.readFileSync(target)); await tick(); fs.writeFileSync(target, String(value + 1)); }
    finally { broker.release(id); }
  };
  await Promise.all([increment('one'), increment('two')]);
  assert.equal(fs.readFileSync(target, 'utf8'), '2');
});
