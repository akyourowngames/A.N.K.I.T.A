import test from 'node:test';
import assert from 'node:assert/strict';
import { ChannelRegistry, defaultRegistry } from '../../src/channels/core/registry.mjs';
import { assertAdapter, normalizeInbound, sessionKey } from '../../src/channels/core/contract.mjs';

const fixture = {
  id: 'fixture', label: 'Fixture', capabilities: ['upload'], required: ['secret'],
  fields: { enabled: { kind: 'bool', default: false }, secret: { kind: 'secret', env: 'FIXTURE_CHANNEL_SECRET', default: '', label: 'Secret' }, count: { kind: 'int', min: 1, max: 3, default: 2 } },
  connect: 'fixture', docsUrl: '',
};

test('a registered descriptor drives validation, env resolution and secret-free setup views', () => {
  const registry = new ChannelRegistry([fixture]);
  const settings = registry.resolve('fixture', {}, name => ({ FIXTURE_CHANNEL_SECRET: 'private-value' })[name]);
  assert.equal(settings.secret, 'private-value');
  assert.equal(settings.enabled, false);
  assert.deepEqual(registry.validate('fixture', { count: 3 }), { count: 3 });
  assert.throws(() => registry.validate('fixture', { count: 4 }), /count/);
  assert.throws(() => registry.validate('fixture', { surprise: true }), /Unknown channel setting/);
  const view = registry.publicView('fixture', settings);
  assert.equal(view.secrets.secret, true);
  assert.equal(view.manifest.fields.secret.kind, 'secret');
  assert.equal(JSON.stringify(view).includes('private-value'), false);
  assert.equal(registry.list().length, 1);
});

test('an explicitly cleared secret wins over environment fallback', () => {
  const registry = new ChannelRegistry([fixture]);
  assert.equal(registry.resolve('fixture', { secret: '' }, () => 'env-secret').secret, '');
  assert.throws(() => registry.register(fixture), /already registered/);
});

test('invalid manifest capabilities, identifiers and defaults fail before runtime', () => {
  for (const patch of [{ id: '../escape' }, { capabilities: ['made-up'] }, { fields: { count: { kind: 'int', default: 99, min: 1, max: 3 } } }]) {
    assert.throws(() => new ChannelRegistry([{ ...fixture, ...patch }]));
  }
});

test('Telegram keeps its canonical chat settings and rejects invalid updates', () => {
  assert.deepEqual(defaultRegistry.validate('telegram', { allowedChatIds: ' 123, 456 789 ', confirmTimeout: 120 }), { allowedChatIds: '123, 456, 789', confirmTimeout: 120 });
  assert.throws(() => defaultRegistry.validate('telegram', { confirmTimeout: 5 }), /between 30 and 3600/);
  assert.throws(() => defaultRegistry.validate('telegram', { enabled: 'yes' }), /enabled/);
});

test('session identifiers cannot collide across channels or crafted chat IDs', () => {
  assert.equal(sessionKey({ channel: 'telegram', chatId: 42 }), 'telegram:42');
  assert.notEqual(sessionKey({ channel: 'telegram', chatId: 42 }), sessionKey({ channel: 'discord', chatId: 42 }));
  assert.throws(() => sessionKey({ channel: 'not:a-channel', chatId: '42' }));
  assert.throws(() => normalizeInbound({ channel: 'fixture', chatId: '1', messageId: '2', raw: { nope: 1n } }), /serialisable/);
});

test('adapter capabilities require their implementation instead of silently claiming support', () => {
  const adapter = { manifest: fixture, start() {}, stop() {}, send() {} };
  assert.throws(() => assertAdapter(adapter), /upload/);
  assert.doesNotThrow(() => assertAdapter({ ...adapter, upload() {} }));
});
