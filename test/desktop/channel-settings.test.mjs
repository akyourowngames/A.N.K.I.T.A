import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ChannelRegistry } from '../../src/channels/core/registry.mjs';
import { telegramManifest } from '../../src/channels/manifests/telegram.mjs';
import { commonFields } from '../../src/channels/manifests/common.mjs';
import { ChannelStore, ChannelManager } from '../../desktop/electron/channels.mjs';
import { channelDraft, channelPatch } from '../../desktop/shared/channel-settings.mjs';

const descriptor = { id: 'fixture', label: 'Fixture messenger', capabilities: [], required: ['secret'], connect: 'fixture', fields: { ...commonFields, secret: { kind: 'secret', env: 'FIXTURE_CHANNEL_SECRET', label: 'Connection key', default: '' } } };

test('one newly registered manifest exposes a settings card, validates, resolves env and verifies without channel-specific host code', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-channel-settings-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const registry = new ChannelRegistry([telegramManifest, descriptor]);
  const store = new ChannelStore(path.join(directory, 'settings.json'), { registry, env: name => name === 'FIXTURE_CHANNEL_SECRET' ? 'private-env-value' : undefined }).load();
  const manager = new ChannelManager({ store, adapterFactories: { fixture: () => ({ manifest: descriptor, start() {}, stop() {}, send() {}, verify: async settings => ({ account: settings.secret === 'private-env-value' ? 'verified fixture' : 'changed key' }) }) } });
  const view = manager.publicView();
  assert.equal(view.channels.fixture.manifest.label, 'Fixture messenger');
  assert.equal(view.channels.fixture.secrets.secret, true);
  assert.equal(JSON.stringify(view).includes('private-env-value'), false);
  assert.deepEqual(registry.validate('fixture', { enabled: true }), { enabled: true });
  assert.equal((await manager.verify('fixture', {})).account, 'verified fixture');
  assert.equal((await manager.verify('fixture', { secret: 'fresh-key' })).account, 'changed key');
  assert.equal(store.get('fixture').secret, 'private-env-value', 'verification does not persist drafts');
});

test('channel drafts never copy saved secrets and patches preserve, replace or explicitly remove them', () => {
  const preferences = { ...Object.fromEntries(Object.entries(descriptor.fields).map(([key, field]) => [key, field.default])), manifest: descriptor, secrets: { secret: true }, status: { running: false, account: null, error: null } };
  const draft = channelDraft(preferences);
  assert.equal(draft.secret, '');
  assert.deepEqual(channelPatch(preferences, draft), {});
  assert.deepEqual(channelPatch(preferences, { ...draft, secret: 'new-private' }), { secret: 'new-private' });
  assert.deepEqual(channelPatch(preferences, draft, ['secret']), { secret: '' });
  assert.deepEqual(channelPatch(preferences, { ...draft, teammateId: 'chief', confirmTimeout: '90' }), { teammateId: 'chief', confirmTimeout: 90 });
  assert.throws(() => channelPatch(preferences, { ...draft, confirmTimeout: '' }), /timeout/i);
});
