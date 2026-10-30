import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DesktopEngine } from '../../desktop/electron/engine.mjs';
import { normalizePersonality } from '../../src/core/personality.mjs';

test('desktop personality saves persist, reach idle agents and future voice captures without reconnecting', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-personality-engine-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const client = {}, events = [];
  const engine = new DesktopEngine({
    teammateFile: path.join(directory, 'teammates.json'), settingsFile: path.join(directory, 'settings.json'),
    channelsFile: path.join(directory, 'channels.json'), sessionsDir: path.join(directory, 'sessions'),
    config: { provider: 'custom', model: 'fixture', tools: false },
    bootstrap: async () => ({ client, models: [{ id: 'fixture' }], model: 'fixture', provider: { name: 'custom' } }),
    mcp: { reconcile: async () => {}, ensureComposio: async () => {}, closeAll: async () => {} }, emit: event => events.push(event),
  });
  await engine.init(); t.after(() => engine.close());
  assert.equal(typeof engine.getPersonality, 'function', 'Desktop personality editor backend is missing');
  const previous = structuredClone(engine.config.personality);
  const idle = { config: { ...engine.config } };
  engine.agents.set('idle-fixture', idle);
  const saved = engine.savePersonality({ description: 'Caring and sassy custom fixture' });
  assert.equal(saved.profile.description, 'Caring and sassy custom fixture');
  assert.equal(engine.client, client);
  assert.equal(idle.config.personality.description, saved.profile.description);
  assert.equal(previous.description === saved.profile.description, false);
  assert.deepEqual(JSON.parse(fs.readFileSync(engine.personalityStore.file, 'utf8')).profile, saved.profile);
  const before = fs.readFileSync(engine.personalityStore.file, 'utf8');
  engine.turns.set('busy-fixture', {});
  assert.throws(() => engine.savePersonality({ teasing: 'off' }), /finish/i);
  assert.equal(fs.readFileSync(engine.personalityStore.file, 'utf8'), before);
  engine.turns.clear();
  assert.deepEqual(engine.getPersonality().profile, normalizePersonality(saved.profile));
});

test('a personality saved during provider connection remains current after reconnect', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-personality-reconnect-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const session = { client: {}, models: [{ id: 'fixture' }], model: 'fixture', provider: { name: 'custom' } };
  const engine = new DesktopEngine({
    teammateFile: path.join(directory, 'teammates.json'), settingsFile: path.join(directory, 'settings.json'),
    channelsFile: path.join(directory, 'channels.json'), sessionsDir: path.join(directory, 'sessions'),
    config: { provider: 'custom', model: 'fixture', tools: false }, bootstrap: async () => session,
    mcp: { reconcile: async () => {}, ensureComposio: async () => {}, closeAll: async () => {} },
  });
  await engine.init(); t.after(() => engine.close());
  let release, started;
  const gate = new Promise(resolve => { release = resolve; });
  const entered = new Promise(resolve => { started = resolve; });
  engine.connectProvider = async () => { started(); await gate; return { ...session, provider: {name:'groq'} }; };
  const pending = engine.saveDesktopSettings({ provider: 'groq' });
  await entered;
  const saved = engine.savePersonality({ description: 'New style saved while provider connects' });
  release(); await pending;
  assert.equal(engine.config.personality.description, saved.profile.description);
  assert.equal(engine.baseConfig.personality.description, saved.profile.description);
  assert.deepEqual(engine.getPersonality().profile, saved.profile);
});
