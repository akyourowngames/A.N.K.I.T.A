import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ChannelStore } from '../../src/channels/core/store.mjs';

function fixture(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-channel-store-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  return path.join(directory, 'channels.json');
}

test('v1 migrates atomically to v2 and rollback restores the exact original credentials', t => {
  const file = fixture(t);
  const original = JSON.stringify({ version: 1, channels: { telegram: { token: 'old-token', enabled: true, allowedChatIds: '42', teammateId: 'chief' } } });
  fs.writeFileSync(file, original);
  const store = new ChannelStore(file).load();
  assert.equal(store.telegram().token, 'old-token');
  assert.equal(JSON.parse(fs.readFileSync(file)).version, 2);
  assert.equal(store.doctor().migrated, true);
  assert.equal(store.rollback().telegram().token, 'old-token');
  assert.equal(fs.readFileSync(file, 'utf8'), original);
});

test('legacy top-level Telegram settings migrate without silently losing tokens', t => {
  const file = fixture(t);
  fs.writeFileSync(file, JSON.stringify({ telegram: { token: 'legacy-secret', allowedChatIds: '42' } }));
  const store = new ChannelStore(file).load();
  assert.equal(store.get('telegram').token, 'legacy-secret');
  store.update('telegram', { enabled: true });
  assert.equal(new ChannelStore(file).load().telegram().token, 'legacy-secret');
});

test('unknown saved channels survive updates and rollback cannot discard new channel credentials', t => {
  const file = fixture(t);
  fs.writeFileSync(file, JSON.stringify({ version: 1, channels: { telegram: { token: 'old' } } }));
  const store = new ChannelStore(file).load();
  store.data.unregistered = { token: 'must-survive' };
  store.update('telegram', { voiceReply: true });
  assert.equal(JSON.parse(fs.readFileSync(file)).channels.unregistered.token, 'must-survive');
  assert.throws(() => store.rollback(), /discard/);
});

test('a corrupt settings file is retained and cannot be overwritten by an ordinary save', t => {
  const file = fixture(t);
  fs.writeFileSync(file, '{broken-secret-file');
  const store = new ChannelStore(file).load();
  assert.equal(store.telegram().enabled, false);
  assert.equal(store.doctor().ok, false);
  assert.throws(() => store.update({ enabled: true }), /repair|corrupt/i);
  assert.equal(fs.readFileSync(file, 'utf8'), '{broken-secret-file');
});

test('legacy update aliases and generic updates store no extra temporary files', t => {
  const file = fixture(t), store = new ChannelStore(file).load();
  store.update({ token: 'secret', allowedChatIds: '1 2' });
  store.update('telegram', { enabled: true });
  assert.equal(store.telegram().allowedChatIds, '1, 2');
  assert.equal(store.preview({ voiceReply: true }).telegram.voiceReply, true);
  assert.equal(store.preview('telegram', { enabled: false }).telegram.enabled, false);
  assert.equal(fs.readdirSync(path.dirname(file)).filter(name => name.endsWith('.tmp')).length, 0);
});
