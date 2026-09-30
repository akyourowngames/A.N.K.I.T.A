import fs from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { credentialOrigin } from '../../src/integrations/browser-credentials.mjs';

const FORMAT_VERSION = 1; // On-disk encrypted record schema.
const PRIVATE_MODE = 0o600; // Owner-only file access on platforms supporting POSIX permissions.
const CORRUPT_STORE_MESSAGE = 'Cannot read the credential store; it may be corrupt.';
const metadata = ({ id, website, username, updatedAt }) => ({ id, website, username, updatedAt, hasPassword: true });
export class SecureStore {
  constructor({ file, safeStorage, platform = process.platform }) {
    this.file = file; this.safeStorage = safeStorage; this.platform = platform; this.tail = Promise.resolve();
  }
  async available() {
    try {
      return Boolean(this.safeStorage?.encryptStringAsync && this.safeStorage?.decryptStringAsync &&
        await this.safeStorage.isAsyncEncryptionAvailable() &&
        !(this.platform === 'linux' && this.safeStorage.getSelectedStorageBackend?.() === 'basic_text'));
    } catch { return false; }
  }
  async #requireEncryption() { if (!await this.available()) throw new Error('Secure OS encryption is unavailable. Use the browser to sign in manually.'); }
  async #read() {
    let data;
    try { data = JSON.parse(await fs.readFile(this.file, 'utf8')); }
    catch (error) { if (error.code === 'ENOENT') return []; throw new Error(CORRUPT_STORE_MESSAGE); }
    if (data?.version !== FORMAT_VERSION || !Array.isArray(data.records) || data.records.some(r => !r || typeof r.id !== 'string' || typeof r.updatedAt !== 'string' || typeof r.encrypted !== 'string' || !r.encrypted || (r.kind === 'secret' ? !validSecretName(r.name) : typeof r.username !== 'string' || (() => { try { return credentialOrigin(r.website) !== r.website; } catch { return true; } })()))) throw new Error(CORRUPT_STORE_MESSAGE);
    return data.records;
  }
  async #write(records) {
    await fs.mkdir(path.dirname(this.file), { recursive: true });
    const temp = `${this.file}.${randomUUID()}.tmp`;
    try { await fs.writeFile(temp, JSON.stringify({ version: FORMAT_VERSION, records }), { mode: PRIVATE_MODE, flag: 'wx' }); await fs.rename(temp, this.file); }
    finally { await fs.rm(temp, { force: true }).catch(() => {}); }
  }
  #mutate(fn) { const work = this.tail.then(fn); this.tail = work.catch(() => {}); return work; }
  async list() { await this.tail; return (await this.#read()).filter(r => r.kind !== 'secret').map(metadata); }
  async listSecrets() { await this.tail; return (await this.#read()).filter(r => r.kind === 'secret').map(({ id, name, updatedAt }) => ({ id, name, updatedAt })); }
  saveSecret(name, value) {
    return this.#mutate(async () => {
      if (!validSecretName(name) || typeof value !== 'string' || !value) throw new Error('Enter a valid secret name and value');
      await this.#requireEncryption();
      const records = await this.#read(); let bytes;
      try { bytes = await this.safeStorage.encryptStringAsync(value); }
      catch { throw new Error('Could not encrypt the secret. Nothing was saved.'); }
      try {
        const prior = records.find(r => r.kind === 'secret' && r.name === name);
        const record = { id: prior?.id || randomUUID(), kind: 'secret', name, encrypted: bytes.toString('base64'), updatedAt: new Date().toISOString() };
        await this.#write([...records.filter(r => r.id !== record.id), record]);
        return { id: record.id, name, updatedAt: record.updatedAt };
      } finally { bytes.fill(0); }
    });
  }
  async withSecret(name, callback) {
    await this.tail; await this.#requireEncryption();
    const record = (await this.#read()).find(r => r.kind === 'secret' && r.name === name);
    if (!record) return null;
    const bytes = Buffer.from(record.encrypted, 'base64'); let decrypted;
    try { decrypted = await this.safeStorage.decryptStringAsync(bytes); return await callback(decrypted.result); }
    catch { throw new Error('Could not use this saved secret.'); }
    finally { bytes.fill(0); if (decrypted) decrypted.result = ''; }
  }
  save(input) {
    return this.#mutate(async () => {
      const records = await this.#read();
      await this.#requireEncryption();
      const website = credentialOrigin(input?.website), username = String(input?.username || '').trim();
      if (!username || typeof input?.password !== 'string' || !input.password) throw new Error('Enter a username and password');
      let encrypted;
      try { encrypted = await this.safeStorage.encryptStringAsync(input.password); }
      catch { throw new Error('Could not encrypt the credential. Nothing was saved.'); }
      try {
        const prior = records.find(r => r.website === website && r.username === username);
        const record = { id: prior?.id || randomUUID(), website, username, updatedAt: new Date().toISOString(), encrypted: encrypted.toString('base64') };
        await this.#write([...records.filter(r => r.id !== record.id), record]);
        return metadata(record);
      } finally { encrypted.fill(0); }
    });
  }
  remove(id) { return this.#mutate(async () => { const records = await this.#read(); const kept = records.filter(r => r.id !== id); if (kept.length === records.length) return false; await this.#write(kept); return true; }); }
  async withCredentials({ website, username }, callback) {
    await this.tail;
    const records = (await this.#read()).filter(r => r.kind !== 'secret' && r.website === credentialOrigin(website) && (!username || r.username === username));
    // Multiple accounts need explicit selection instead of guessing an identity.
    if (records.length !== 1) return null;
    await this.#requireEncryption();
    const record = records[0], bytes = Buffer.from(record.encrypted, 'base64');
    let value;
    try {
      let decrypted;
      try { decrypted = await this.safeStorage.decryptStringAsync(bytes); }
      catch { throw new Error('Could not unlock this credential. Enter it again or sign in manually.'); }
      value = { website: record.website, username: record.username, password: decrypted.result };
      decrypted.result = '';
      return await callback(value);
    } finally { bytes.fill(0); if (value) value.password = ''; }
  }
}
function validSecretName(name) { return typeof name === 'string' && /^[a-z0-9][a-z0-9-]{0,95}$/.test(name); }
