import test from 'node:test';
import assert from 'node:assert/strict';
test('secure cards preserve actionable plain-text errors and cancellation', async () => {
  const { secureStoreReceipt } = await import('../../desktop/shared/secure-store-receipt.mjs');
  assert.deepEqual(secureStoreReceipt('Error: Secure login supports Playwright only.'), { status: 'attention', message: 'Error: Secure login supports Playwright only.' });
  assert.equal(secureStoreReceipt('Error: Browser action cancelled').status, 'cancelled');
  assert.deepEqual(secureStoreReceipt(''), {});
  assert.equal(secureStoreReceipt(JSON.stringify({ type: 'browser_login', status: 'ready', username: 'user' })).username, 'user');
});

test('secure cards preserve credential state after Agent read-back and repeated-call notices', async () => {
  const { secureStoreReceipt } = await import('../../desktop/shared/secure-store-receipt.mjs');
  const result = JSON.stringify({ type: 'browser_login', status: 'filled', username: 'user', snapshot: 'page refs' });
  assert.equal(secureStoreReceipt(`Repeated call: previously requested\n\n${result}\n[UNVERIFIED: inspect page]`).status, 'filled');
});
