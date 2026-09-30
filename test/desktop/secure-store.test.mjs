import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';

const load = () => import('../../desktop/electron/secure-store.mjs');
const SECRET = 'disposable-vault-password'; // Test-only secret, never a production credential.
function encryption() {
  const key = crypto.randomBytes(32);
  return {
    isAsyncEncryptionAvailable: async () => true,
    getSelectedStorageBackend: () => 'gnome_libsecret',
    encryptStringAsync: async text => { const iv = crypto.randomBytes(12); const cipher = crypto.createCipheriv('aes-256-gcm', key, iv); const bytes = Buffer.concat([cipher.update(text, 'utf8'), cipher.final()]); return Buffer.concat([iv, cipher.getAuthTag(), bytes]); },
    decryptStringAsync: async bytes => { const decipher = crypto.createDecipheriv('aes-256-gcm', key, bytes.subarray(0, 12)); decipher.setAuthTag(bytes.subarray(12, 28)); return { result: Buffer.concat([decipher.update(bytes.subarray(28)), decipher.final()]).toString('utf8'), shouldReEncrypt: false }; },
  };
}
async function fixture(t, options = {}) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-secure-store-'));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const { SecureStore } = await load();
  const file = path.join(dir, 'vault.json');
  return { file, store: new SecureStore({ file, safeStorage: encryption(), ...options }) };
}

test('secure store encrypts disk records, returns only metadata and fills through a scoped callback', async t => {
  const { store, file } = await fixture(t);
  const saved = await store.save({ website: 'https://example.com/login', username: 'fixture-user', password: SECRET });
  assert.equal(saved.website, 'https://example.com');
  assert.equal(saved.hasPassword, true);
  assert.ok(!JSON.stringify(saved).includes(SECRET));
  assert.ok(!(await fs.readFile(file, 'utf8')).includes(SECRET));
  assert.ok(!JSON.stringify(await store.list()).includes(SECRET));
  let transient;
  await store.withCredentials({ website: 'https://example.com', username: 'fixture-user' }, async value => { transient = value; assert.equal(value.password, SECRET); });
  assert.equal(transient.password, '', 'owned credentials are cleared when the callback settles');
  assert.equal(await store.withCredentials({ website: 'https://other.example' }, () => assert.fail('wrong origin')), null);
  assert.equal(await store.remove(saved.id), true);
  assert.deepEqual(await store.list(), []);
});

test('secure store refuses unavailable encryption and Linux plaintext fallback', async t => {
  for (const unavailable of [false, true]) {
    const safeStorage = { ...encryption(), isAsyncEncryptionAvailable: async () => !unavailable, getSelectedStorageBackend: () => 'basic_text' };
    const { store } = await fixture(t, { safeStorage, platform: 'linux' });
    await assert.rejects(store.save({ website: 'example.com', username: 'user', password: SECRET }), /secure|encryption|libsecret/i);
  }
});

test('named pasted secrets are encrypted separately from browser credentials', async t => {
  const { store, file } = await fixture(t);
  const saved = await store.saveSecret('provider-api-key', SECRET);
  assert.equal(saved.name, 'provider-api-key');
  assert.ok(!(await fs.readFile(file, 'utf8')).includes(SECRET));
  assert.deepEqual(await store.list(), [], 'API secrets do not become browser accounts');
  assert.equal((await store.listSecrets()).length, 1);
  await store.withSecret(saved.name, value => assert.equal(value, SECRET));
});

test('secure store fails closed on corruption and sanitizes encryption failures', async t => {
  const safeStorage = { ...encryption(), encryptStringAsync: async () => { throw new Error(SECRET); } };
  const { store, file } = await fixture(t, { safeStorage });
  await assert.rejects(store.save({ website: 'example.com', username: 'user', password: SECRET }), error => !error.message.includes(SECRET));
  await fs.writeFile(file, '{broken');
  await assert.rejects(store.save({ website: 'example.com', username: 'user', password: SECRET }), /read|corrupt/i);
  assert.equal(await fs.readFile(file, 'utf8'), '{broken');
});
