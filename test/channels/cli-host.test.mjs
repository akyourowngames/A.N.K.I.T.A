import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createCliChannelHost } from '../../src/channels/cli-host.mjs';
import { ChannelStore } from '../../src/channels/core/store.mjs';
import { ChannelRegistry } from '../../src/channels/core/registry.mjs';
import { telegramManifest } from '../../src/channels/manifests/telegram.mjs';
import { commonFields } from '../../src/channels/manifests/common.mjs';
import { RoutineStore } from '../../src/automation/routines.mjs';

test('connecting a terminal channel runs its socket without starting scheduled routines', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'channel-cli-host-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const manifest = { id: 'fixture', label: 'Fixture', capabilities: [], required: ['secret'], connect: 'fixture', fields: { ...commonFields, secret: { kind: 'secret', default: '' } } };
  const channelStore = new ChannelStore(path.join(directory, 'channels.json'), { registry: new ChannelRegistry([telegramManifest, manifest]) }).load();
  channelStore.update('fixture', { secret: 'private-fixture-value' });
  const store = new RoutineStore(path.join(directory, 'routines.json')).load();
  store.addRoutine({ name: 'Do not run during channel connect', cron: '* * * * *', prompt: 'unrelated schedule' });
  const host = createCliChannelHost({ store, channelStore, config: {}, client: {}, adapterFactories: { fixture: () => ({ manifest, send() {}, stop() {},
    start(ctx) { this.ready = Promise.resolve({ account: 'fixture' }); return new Promise(resolve => ctx.signal.addEventListener('abort', resolve, { once: true })); },
  }) } });
  t.after(() => host.stopAll());
  assert.equal(host.publicView().channels.fixture.status.running, false);
  await host.save('fixture', { enabled: true });
  assert.equal(host.publicView().channels.fixture.status.running, true);
  assert.equal(store.routines[0].lastRun, null);
  assert.equal(JSON.stringify(host.publicView()).includes('private-fixture-value'), false);
  await host.stopAll();
  assert.equal(host.publicView().channels.fixture.status.running, false);
});
