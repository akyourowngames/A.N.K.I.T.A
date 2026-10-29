import test from 'node:test';
import assert from 'node:assert/strict';
import { ExtensionBrowserOperations } from '../../desktop/browser-helper/browser-operations.mjs';
const keyboard = await import('../../desktop/browser-helper/keyboard.mjs').catch(() => null);

function apiFixture() {
  const state = {}, listeners = [], commands = [];
  const api = { runtime: { getPlatformInfo: async () => ({ os: 'win' }) },
    storage: { session: { get: async key => ({ [key]: state[key] }), set: async value => Object.assign(state, value) } },
    tabs: { get: async () => ({ id: 1, url: 'https://example.com/' }), create: async () => ({ id: 1 }) },
    scripting: { executeScript: async () => [{ result: { x: 10, y: 20, documentId: 'doc' } }] },
    debugger: { onDetach: { addListener: fn => listeners.push(fn) }, attach: async () => {}, detach: async () => {}, sendCommand: async (_target, method, params) => { commands.push({ method, params }); return {}; } },
  };
  return { api, commands, listeners };
}
test('stopping while deeper access attaches prevents input after attachment', async () => {
  const f = apiFixture(), executor = new ExtensionBrowserOperations(f.api), controller = new AbortController();
  let attached; const attaching = new Promise(resolve => { attached = resolve; });
  f.api.debugger.attach = () => attaching;
  const work = executor.execute({ action: 'act', op: 'press', text: 'Enter', scope: 'one', tab: '1' }, controller.signal);
  const rejected = assert.rejects(work, /abort|cancel/i);
  await new Promise(resolve => setImmediate(resolve)); controller.abort(); attached(); await rejected;
  assert.equal(f.commands.length, 0);
});
test('tab ownership and cancelled debugger access survive a worker restart', async () => {
  const f = apiFixture(), first = new ExtensionBrowserOperations(f.api);
  await first.execute({ action: 'open', url: 'https://example.com/', scope: 'job', ownedTabs: true });
  for (const listener of f.listeners) listener({ tabId: 1 }, 'canceled_by_user');
  await new Promise(resolve => setImmediate(resolve));
  const restart = new ExtensionBrowserOperations(f.api);
  await assert.rejects(restart.execute({ action: 'screenshot', scope: 'job', tab: '1', ownedTabs: true }), /cancelled deeper/);
  assert.equal(restart.owners.get(1), 'job');
});
test('Enter and modifier chords contain native keyboard details', () => {
  assert.ok(keyboard, 'native keyboard encoding is implemented');
  const enter = keyboard.keyEvents('Enter', 'win');
  assert.equal(enter[0].windowsVirtualKeyCode, 13); assert.equal(enter[0].text, '\r');
  const chord = keyboard.keyEvents('Control+A', 'win');
  assert.equal(chord[0].modifiers, 2); assert.equal(chord[0].code, 'KeyA'); assert.equal(chord[0].text, undefined);
  assert.throws(() => keyboard.keyEvents('TotallyUnknownKey', 'win'), /Unsupported/);
});
test('a screenshot refuses a page navigated while debugger attachment awaited', async () => {
  const f = apiFixture(), executor = new ExtensionBrowserOperations(f.api);
  let url = 'https://example.com/';
  f.api.tabs.get = async () => ({ id: 1, url });
  f.api.debugger.attach = async () => { url = 'https://different.example/private'; };
  await assert.rejects(executor.execute({ action: 'screenshot', scope: 'job', tab: '1', expectedUrl: 'https://example.com/' }), /page changed/i);
  assert.equal(f.commands.length, 0);
});
