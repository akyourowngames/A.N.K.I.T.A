import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ChannelStore, ChannelManager } from '../../desktop/electron/channels.mjs';
import { ChannelRegistry } from '../../src/channels/core/registry.mjs';
import { telegramManifest } from '../../src/channels/manifests/telegram.mjs';
import { commonFields } from '../../src/channels/manifests/common.mjs';
import { runChannelCommand } from '../../src/channels/commands.mjs';
import { itemFor } from '../../src/core/commands.mjs';

test('terminal channel discovery, connection, verification and disconnect share the registry and store', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'channel-command-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const manifest = { id: 'fixture', label: 'Fixture messenger', connect: 'fixture', capabilities: [], required: ['secret'], fields: { ...commonFields, secret: { kind: 'secret', env: 'FIXTURE_CHANNEL_SECRET', default: '' } } };
  const registry = new ChannelRegistry([telegramManifest, manifest]);
  const store = new ChannelStore(path.join(directory, 'channels.json'), { registry }).load(); store.update('fixture', { secret: 'private-value', teammateId: 'chief' });
  const host = new ChannelManager({ store, adapterFactories: { fixture: () => ({ manifest, send: async () => ({}), stop: async () => {},
    start(ctx) { this.ready = Promise.resolve({ account: 'fixture-account' }); return new Promise(resolve => ctx.signal.addEventListener('abort', resolve, { once: true })); },
    verify: async () => ({ account: 'fixture-account' }),
  }) } });
  t.after(() => host.stopAll());
  assert.ok(itemFor('/channels'));
  const listed = await runChannelCommand('', { host }); assert.match(listed, /Fixture messenger/); assert.ok(!listed.includes('private-value'));
  assert.match(await runChannelCommand('connect fixture', { host }), /connected/i);
  assert.equal(host.publicView().channels.fixture.status.running, true);
  assert.match(await runChannelCommand('test fixture', { host }), /fixture-account/);
  await runChannelCommand('disconnect fixture', { host });
  assert.equal(store.get('fixture').enabled, false); assert.equal(host.publicView().channels.fixture.status.running, false);
  await assert.rejects(runChannelCommand('connect fixture pasted-secret', { host }), /secret|usage/i);
  assert.match(await runChannelCommand('doctor', { host }), /healthy|OK/i);
});
