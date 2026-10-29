import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ChannelHost } from '../../src/channels/core/host.mjs';
import { ChannelStore } from '../../src/channels/core/store.mjs';
import { ChannelRegistry } from '../../src/channels/core/registry.mjs';
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
function fixture(t, create) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-host-')); t.after(() => fs.rmSync(dir, { force: true, recursive: true }));
  const registry = new ChannelRegistry([{ id: 'fixture', label: 'Fixture', capabilities: [], fields: { enabled: { kind: 'bool', default: true } } }]);
  const store = new ChannelStore(path.join(dir, 'channels.json'), { registry }).load();
  return new ChannelHost({ store, surface: {}, adapterFactories: { fixture: create } });
}
test('concurrent channel operations create only one transport and shutdown joins pending creation', async t => {
  const gate = deferred(); let creates = 0, stops = 0;
  const host = fixture(t, async () => { creates++; await gate.promise; return { manifest: host.registry.get('fixture'), start() {}, stop() { stops++; }, send() {} }; });
  const first = host.runtime('fixture'), second = host.runtime('fixture');
  const ending = host.stopAll(); gate.resolve();
  const [a, b] = await Promise.all([first, second]); await ending;
  assert.equal(a, b); assert.equal(creates, 1); assert.equal(stops, 1);
});

test('simultaneous settings saves serialize reconnects instead of stopping a newer connection', async t => {
  let stops = 0, active = 0, maximum = 0, stopping = 0; const startsDuringStop = [];
  const host = fixture(t, async () => ({ manifest: host.registry.get('fixture'), start() { startsDuringStop.push(stopping); active++; maximum = Math.max(maximum, active); },
    async stop() { stops++; stopping++; await new Promise(resolve => setTimeout(resolve, stops === 1 ? 5 : 15)); active = 0; stopping--; }, send() {} }));
  await Promise.all([host.save('fixture', { enabled: true }), host.save('fixture', { enabled: true })]);
  assert.equal(maximum, 1); assert.equal(host.runtimes.get('fixture').running, true);
  assert.ok(startsDuringStop.every(count => count === 0));
  await host.stopAll();
});
