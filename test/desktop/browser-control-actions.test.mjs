import test from 'node:test';
import assert from 'node:assert/strict';
const module = await import('../../desktop/electron/browser-control-actions.mjs').catch(() => null);
test('disconnect and unpair affect the companion grant without closing unrelated browser work', async () => {
  assert.ok(module, 'browser control IPC actions have a focused boundary');
  let paused = null, revoked = 0;
  const service = { pauseBrowser: async value => { paused = value; return { paused }; }, revokeBrowser: async () => { revoked++; return { paired: false }; } };
  const engine = { browserManager: { close: () => assert.fail('unrelated private browser work must not close') } };
  await module.runBrowserControlAction({ action: 'browserExtensionDisconnect', engine, start: async () => service });
  assert.equal(paused, true);
  await module.runBrowserControlAction({ action: 'browserExtensionResume', engine, start: async () => service });
  assert.equal(paused, false);
  await module.runBrowserControlAction({ action: 'browserExtensionRevoke', engine, start: async () => service });
  assert.equal(revoked, 1);
});
