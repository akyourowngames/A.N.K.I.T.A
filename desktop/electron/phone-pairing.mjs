import https from 'node:https';
import { randomBytes, randomUUID, createHash, createPrivateKey, timingSafeEqual, X509Certificate } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { networkInterfaces, hostname as osHostname } from 'node:os';
import forge from 'node-forge';
import QRCode from 'qrcode';
import {
  PHONE_PAIRING_PROTOCOL_VERSION, PHONE_PAIRING_ROOT,
  INVITATION_TTL_MS, INVITATION_CODE_ALPHABET, INVITATION_CODE_LENGTH,
  MAX_INVITATION_ATTEMPTS, PENDING_APPROVAL_TTL_MS, MAX_PENDING_PAIRINGS,
  DEVICE_TOKEN_BYTES, PAIR_SECRET_BYTES, MAX_PAIRED_DEVICES, DEVICE_ONLINE_WINDOW_MS,
  MAX_DEVICE_NAME_CHARS, MAX_PLATFORM_CHARS,
  RUN_TIMEOUT_MS, RUN_RETENTION_MS, MAX_RUNS, MAX_RUN_EVENTS, MAX_PROMPT_CHARS,
  MAX_REPLY_CHARS, MAX_EVENT_DETAIL_CHARS, MAX_REQUEST_BYTES,
  PAIRING_CONFIG_FILE, PAIRING_DEVICES_FILE, PAIRING_CERTIFICATE_FILE, PAIRING_SERVICE_NAME,
  PAIRING_STATUS, PAIRING_STATE,
  normalizePairingCode, formatPairingCode, pairingUri,
} from '../shared/phone-pairing.mjs';

const CONFIG_VERSION = 1; // On-disk pairing configuration schema.
const DEVICES_VERSION = 1; // On-disk paired-device schema.
const PRIVATE_MODE = 0o600; // Owner-only files on platforms with POSIX permissions.
const LOOPBACK_IPV4 = '127.0.0.1'; // Included in the certificate so local smoke tests can verify TLS.
const TLS_KEY_BITS = 2048; // RSA key size for the local certificate authority and leaf.
const TLS_VALIDITY_DAYS = 3650; // Long-lived local CA; the phone owner installs it explicitly.
const TLS_RENEW_BEFORE_MS = 30 * 24 * 60 * 60 * 1000; // Regenerate the leaf a month before expiry.
const IPV4_FAMILY = 4;
const PRIVATE_IPV4 = /^(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)/;
const VIRTUAL_INTERFACE = /vethernet|virtualbox|vmware|hyper-v|loopback|tailscale|zerotier|docker|wsl/i;
const DNS_SAN = /^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$/i;
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/; // 32 random bytes, base64url without padding.
const SHA256_HEX = /^[0-9a-f]{64}$/;
const REQUEST_SOCKET_TIMEOUT_MS = 15000;
const QR_WIDTH_PX = 320;
const QR_MARGIN_MODULES = 2;
const QR_DARK = '#13161a';
const QR_LIGHT = '#ffffff';
const ROUTE_PAIR = `${PHONE_PAIRING_ROOT}/pair`;
const ROUTE_REVOKE = `${PHONE_PAIRING_ROOT}/pair/revoke`;
const ROUTE_CAPABILITIES = `${PHONE_PAIRING_ROOT}/capabilities`;
const ROUTE_RUNS = `${PHONE_PAIRING_ROOT}/runs`;
const PAIR_ROUTE = new RegExp(`^${PHONE_PAIRING_ROOT}/pair/([0-9a-f-]{36})$`);
const RUN_ROUTE = new RegExp(`^${PHONE_PAIRING_ROOT}/runs/([0-9a-f-]{36})$`);
const APPROVAL_ROUTE = new RegExp(`^${PHONE_PAIRING_ROOT}/runs/([0-9a-f-]{36})/approvals/([0-9a-f-]{36})$`);

function httpError(status, message) { return Object.assign(new Error(message), { status }); }
function fingerprint(pem) { return new X509Certificate(pem).fingerprint256; }
function randomSerial() { const bytes = randomBytes(16); bytes[0] &= 0x7f; return bytes.toString('hex'); } // Positive X.509 serial.
function tokenHash(token) { return createHash('sha256').update(token).digest('hex'); }
function equal(left, right) {
  const a = Buffer.from(String(left || '')), b = Buffer.from(String(right || ''));
  return a.length === b.length && timingSafeEqual(a, b);
}
function safeName(value, limit) { return String(value || '').replace(/[\u0000-\u001f\u007f]/g, ' ').trim().slice(0, limit); }
function iso(value) { return value ? new Date(value).toISOString() : null; }
function uniqueAddresses(values) { return [...new Set(values.filter(Boolean))]; }

/** LAN addresses a phone could plausibly reach; loopback and virtual adapters are excluded. */
export function lanAddresses(interfaces = networkInterfaces()) {
  const physical = [], other = [];
  for (const [name, entries] of Object.entries(interfaces || {})) {
    for (const entry of entries || []) {
      if (entry.internal || Number(entry.family) !== IPV4_FAMILY || entry.address.startsWith('169.254.')) continue;
      (VIRTUAL_INTERFACE.test(name) ? other : physical).push(entry.address);
    }
  }
  const rank = list => [...new Set(list)].sort((a, b) => Number(PRIVATE_IPV4.test(b)) - Number(PRIVATE_IPV4.test(a)));
  return uniqueAddresses([...rank(physical), ...rank(other)]);
}

function certificateAuthority() {
  const keys = forge.pki.rsa.generateKeyPair(TLS_KEY_BITS);
  const certificate = forge.pki.createCertificate();
  certificate.publicKey = keys.publicKey;
  certificate.serialNumber = randomSerial();
  certificate.validity.notBefore = new Date(Date.now() - 60 * 60 * 1000);
  certificate.validity.notAfter = new Date(Date.now() + TLS_VALIDITY_DAYS * 24 * 60 * 60 * 1000);
  const subject = [{ name: 'commonName', value: `${PAIRING_SERVICE_NAME} pairing CA` }, { name: 'organizationName', value: 'Ankita' }];
  certificate.setSubject(subject);
  certificate.setIssuer(subject);
  certificate.setExtensions([
    { name: 'basicConstraints', cA: true, critical: true },
    { name: 'keyUsage', keyCertSign: true, cRLSign: true, critical: true },
    { name: 'subjectKeyIdentifier' },
  ]);
  certificate.sign(keys.privateKey, forge.md.sha256.create());
  return { certPem: forge.pki.certificateToPem(certificate), keyPem: forge.pki.privateKeyToPem(keys.privateKey) };
}

function leafCertificate({ caCertPem, caKeyPem, addresses, hostname }) {
  const caCertificate = forge.pki.certificateFromPem(caCertPem);
  const caKey = forge.pki.privateKeyFromPem(caKeyPem);
  const keys = forge.pki.rsa.generateKeyPair(TLS_KEY_BITS);
  const certificate = forge.pki.createCertificate();
  certificate.publicKey = keys.publicKey;
  certificate.serialNumber = randomSerial();
  certificate.validity.notBefore = new Date(Date.now() - 60 * 60 * 1000);
  certificate.validity.notAfter = new Date(Date.now() + TLS_VALIDITY_DAYS * 24 * 60 * 60 * 1000);
  certificate.setSubject([{ name: 'commonName', value: PAIRING_SERVICE_NAME }, { name: 'organizationName', value: 'Ankita' }]);
  certificate.setIssuer(caCertificate.subject.attributes);
  const altNames = [...uniqueAddresses([LOOPBACK_IPV4, ...addresses])].map(ip => ({ type: 7, ip }));
  for (const name of [hostname, `${hostname}.local`, 'localhost']) if (DNS_SAN.test(name || '')) altNames.push({ type: 2, value: name });
  certificate.setExtensions([
    { name: 'basicConstraints', cA: false, critical: true },
    { name: 'keyUsage', digitalSignature: true, keyEncipherment: true, critical: true },
    { name: 'extKeyUsage', serverAuth: true },
    { name: 'subjectAltName', altNames },
    { name: 'subjectKeyIdentifier' },
    { name: 'authorityKeyIdentifier' },
  ]);
  certificate.sign(caKey, forge.md.sha256.create());
  return { certPem: forge.pki.certificateToPem(certificate), keyPem: forge.pki.privateKeyToPem(keys.privateKey) };
}

async function writePrivate(file, value) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const temp = `${file}.${randomUUID()}.tmp`;
  try {
    await fs.writeFile(temp, value, { mode: PRIVATE_MODE, flag: 'wx' });
    await fs.rename(temp, file);
  } finally { await fs.rm(temp, { force: true }).catch(() => {}); }
}

/**
 * LAN pairing and run bridge. It owns the HTTPS server, invitation/approval
 * state and per-phone tokens; the desktop engine keeps owning the assistant,
 * tool approvals and thread history.
 */
export class PhonePairing {
  constructor({ configFile, devicesFile, safeStorage, engine, emit = () => {}, addresses, hostname = osHostname(), now = Date.now, platform = process.platform }) {
    if (!engine) throw new Error('Phone pairing needs the desktop engine');
    this.configFile = configFile;
    this.devicesFile = devicesFile;
    this.safeStorage = safeStorage;
    this.engine = engine;
    this.emit = emit;
    this.addressProvider = addresses ? () => addresses : () => lanAddresses();
    this.hostname = hostname;
    this.now = now;
    this.platform = platform;
    this.state = PAIRING_STATE.STARTING;
    this.error = null;
    this.server = null;
    this.port = 0;
    this.addresses = [];
    this.preferredAddress = null;
    this.ca = null;
    this.leaf = null;
    this.invitation = null;
    this.invitationTimer = null;
    this.pending = new Map();
    this.pendingTimers = new Map();
    this.devices = [];
    this.runs = new Map();
    this.saveTail = Promise.resolve();
    this.lastSeenWrites = new Map();
    this.closed = false;
  }

  async available() {
    try {
      return Boolean(this.safeStorage?.encryptStringAsync && this.safeStorage?.decryptStringAsync &&
        await this.safeStorage.isAsyncEncryptionAvailable() &&
        !(this.platform === 'linux' && this.safeStorage.getSelectedStorageBackend?.() === 'basic_text'));
    } catch { return false; }
  }

  async #encrypt(value) {
    const bytes = await this.safeStorage.encryptStringAsync(value);
    try { return bytes.toString('base64'); } finally { bytes.fill(0); }
  }

  async #decrypt(encoded) {
    const bytes = Buffer.from(String(encoded || ''), 'base64');
    try { return (await this.safeStorage.decryptStringAsync(bytes)).result; } finally { bytes.fill(0); }
  }

  async #loadConfig() {
    let data;
    try { data = JSON.parse(await fs.readFile(this.configFile, 'utf8')); }
    catch (error) { if (error.code === 'ENOENT') return null; throw new Error('The phone pairing configuration could not be read.'); }
    if (data?.version !== CONFIG_VERSION || !Number.isInteger(data.port) || data.port < 0 || data.port > 65535 ||
        typeof data.caCert !== 'string' || typeof data.caKey !== 'string' || !data.caCert || !data.caKey ||
        typeof data.leafCert !== 'string' || typeof data.leafKey !== 'string' || !data.leafCert || !data.leafKey ||
        (data.address !== null && typeof data.address !== 'string') ||
        !Array.isArray(data.addresses) || data.addresses.some(item => typeof item !== 'string')) throw new Error('The phone pairing configuration is invalid.');
    return data;
  }

  async #loadDevices() {
    let data;
    try { data = JSON.parse(await fs.readFile(this.devicesFile, 'utf8')); }
    catch (error) { if (error.code === 'ENOENT') return []; throw new Error('The paired-phone list could not be read.'); }
    if (data?.version !== DEVICES_VERSION || !Array.isArray(data.devices) || data.devices.length > MAX_PAIRED_DEVICES) throw new Error('The paired-phone list is invalid.');
    for (const device of data.devices) {
      if (typeof device?.id !== 'string' || typeof device.name !== 'string' || typeof device.platform !== 'string' ||
          typeof device.teammateId !== 'string' || !SHA256_HEX.test(device.tokenHash || '') || typeof device.createdAt !== 'string' ||
          (device.lastSeenAt !== null && typeof device.lastSeenAt !== 'string') || typeof device.revokedAt !== 'undefined') throw new Error('The paired-phone list is invalid.');
    }
    return data.devices;
  }

  async #saveDevices() {
    const payload = JSON.stringify({ version: DEVICES_VERSION, devices: this.devices });
    this.saveTail = this.saveTail.catch(() => {}).then(() => writePrivate(this.devicesFile, payload));
    return this.saveTail;
  }

  async #saveConfig() {
    const config = {
      version: CONFIG_VERSION, port: this.port,
      caCert: this.ca.certPem, caKey: await this.#encrypt(this.ca.keyPem),
      leafCert: this.leaf.certPem, leafKey: await this.#encrypt(this.leaf.keyPem),
      addresses: this.addresses, address: this.preferredAddress || null,
    };
    await writePrivate(this.configFile, JSON.stringify(config));
  }

  async #ensureCertificates(config) {
    const hostname = this.hostname;
    let ca = null;
    if (config) {
      try {
        const caKeyPem = await this.#decrypt(config.caKey), certificate = new X509Certificate(config.caCert);
        if (caKeyPem && certificate.validToDate.getTime() > this.now() + TLS_RENEW_BEFORE_MS && certificate.checkPrivateKey(createPrivateKey(caKeyPem))) {
          ca = { certPem: config.caCert, keyPem: caKeyPem };
        }
      } catch { ca = null; }
    }
    ca ||= certificateAuthority();

    let leaf = null;
    if (config) {
      try {
        const certificate = new X509Certificate(config.leafCert);
        const coversAddresses = JSON.stringify(config.addresses) === JSON.stringify(this.addresses);
        if (coversAddresses && certificate.checkIssued(new X509Certificate(config.caCert)) &&
            certificate.validToDate.getTime() > this.now() + TLS_RENEW_BEFORE_MS) leaf = { certPem: config.leafCert, keyPem: await this.#decrypt(config.leafKey) };
      } catch { leaf = null; }
    }
    leaf ||= leafCertificate({ caCertPem: ca.certPem, caKeyPem: ca.keyPem, addresses: this.addresses, hostname });
    return { ca, leaf };
  }

  async start() {
    if (this.server) return this;
    this.closed = false;
    this.state = PAIRING_STATE.STARTING; this.error = null;
    try {
      if (!await this.available()) {
        this.state = PAIRING_STATE.UNSUPPORTED;
        this.error = 'Secure OS encryption is unavailable, so the desktop cannot store its pairing certificate.';
        this.emitChanged(); return this;
      }
      this.addresses = uniqueAddresses(this.addressProvider());
      if (!this.addresses.length) {
        this.state = PAIRING_STATE.OFFLINE;
        this.error = 'Connect this computer to Wi-Fi or Ethernet so a phone can reach it.';
        this.emitChanged(); return this;
      }
      this.devices = await this.#loadDevices();
      const config = await this.#loadConfig();
      this.preferredAddress = this.addresses.includes(config?.address) ? config.address : null;
      const { ca, leaf } = await this.#ensureCertificates(config);
      this.ca = ca; this.leaf = leaf;
      const tls = { key: leaf.keyPem, cert: `${leaf.certPem}\n${ca.certPem}`, minVersion: 'TLSv1.2' };
      this.server = https.createServer(tls, (request, response) => { void this.#handle(request, response); });
      this.server.requestTimeout = REQUEST_SOCKET_TIMEOUT_MS;
      this.server.headersTimeout = REQUEST_SOCKET_TIMEOUT_MS;
      const requestedPort = config?.port ?? 0;
      try { await this.#listen(requestedPort); }
      catch (error) { if (error.code !== 'EADDRINUSE' || !requestedPort) throw error; await this.#listen(0); }
      this.port = this.server.address().port;
      await this.#saveConfig();
      this.state = PAIRING_STATE.READY;
    } catch (error) {
      this.state = PAIRING_STATE.ERROR;
      this.error = this.#clean(error.message || String(error), 240);
      await this.#stopServer();
    }
    this.emitChanged();
    return this;
  }

  async #listen(port) {
    await new Promise((resolve, reject) => {
      const onError = error => { this.server.off('listening', onListening); reject(error); };
      const onListening = () => { this.server.off('error', onError); resolve(); };
      this.server.once('error', onError);
      this.server.once('listening', onListening);
      this.server.listen(port, '0.0.0.0');
    });
  }

  async restart() {
    await this.close({ keepClosed: true });
    return this.start();
  }

  async close({ keepClosed = false } = {}) {
    this.closed = !keepClosed;
    for (const run of this.runs.values()) this.#cancelRun(run);
    this.runs.clear();
    this.#clearInvitation();
    for (const timer of this.pendingTimers.values()) clearTimeout(timer);
    this.pendingTimers.clear(); this.pending.clear();
    await this.saveTail.catch(() => {});
    await this.#stopServer();
  }

  async #stopServer() {
    const server = this.server;
    this.server = null;
    if (!server?.listening) return;
    server.closeAllConnections?.();
    await new Promise(resolve => server.close(resolve));
  }

  get address() {
    const address = this.preferredAddress && this.addresses.includes(this.preferredAddress) ? this.preferredAddress : this.addresses[0];
    return address ? `https://${address}:${this.port}${PHONE_PAIRING_ROOT}` : null;
  }

  fingerprint() { return this.ca ? fingerprint(this.ca.certPem) : null; }

  certificate() {
    return this.ca ? { pem: this.ca.certPem, fingerprint: fingerprint(this.ca.certPem), fileName: PAIRING_CERTIFICATE_FILE } : null;
  }

  #teammates() { try { return this.engine.listTeammates(); } catch { return []; } }

  #deviceView(device) {
    const teammate = this.#teammates().find(item => item.id === device.teammateId);
    const lastSeen = device.lastSeenAt ? Date.parse(device.lastSeenAt) : 0;
    const active = [...this.runs.values()].find(run => run.deviceId === device.id && !run.finished);
    return {
      id: device.id, name: device.name, platform: device.platform,
      teammateId: device.teammateId, teammateName: teammate?.name || 'Removed teammate',
      createdAt: device.createdAt, lastSeenAt: device.lastSeenAt || null,
      online: Boolean(lastSeen && this.now() - lastSeen < DEVICE_ONLINE_WINDOW_MS),
      activeRun: active ? active.status : null,
    };
  }

  #invitationView() {
    if (!this.invitation) return null;
    const code = formatPairingCode(this.invitation.code);
    return {
      id: this.invitation.id, code, expiresAt: iso(this.invitation.expiresAt),
      address: this.address, fingerprint: this.fingerprint(), attemptsLeft: MAX_INVITATION_ATTEMPTS - this.invitation.attempts,
    };
  }

  snapshot() {
    return {
      state: this.state, error: this.error,
      address: this.address, name: this.hostname, port: this.port || null,
      fingerprint: this.fingerprint(), addresses: [...this.addresses], preferredAddress: this.preferredAddress,
      running: this.state === PAIRING_STATE.READY,
      invitation: this.#invitationView(),
      pending: [...this.pending.values()].filter(item => item.status === PAIRING_STATUS.PENDING).map(item => ({
        requestId: item.requestId, deviceName: item.deviceName, platform: item.platform,
        createdAt: iso(item.createdAt), expiresAt: iso(item.expiresAt),
      })),
      devices: this.devices.map(device => this.#deviceView(device)),
      teammates: this.#teammates().map(item => ({ id: item.id, name: item.name })),
    };
  }

  emitChanged() {
    if (this.closed) return;
    try { this.emit({ type: 'phone-pairing-changed', snapshot: this.snapshot() }); } catch {}
  }

  #clearInvitation() {
    if (this.invitationTimer) clearTimeout(this.invitationTimer);
    this.invitationTimer = null; this.invitation = null;
  }

  async createInvitation() {
    if (this.state !== PAIRING_STATE.READY || !this.address) throw new Error('Phone pairing is not available on this computer yet.');
    this.#clearInvitation();
    const bytes = randomBytes(INVITATION_CODE_LENGTH);
    const code = [...bytes].map(byte => INVITATION_CODE_ALPHABET[byte % INVITATION_CODE_ALPHABET.length]).join('');
    const invitation = { id: randomUUID(), code, attempts: 0, expiresAt: this.now() + INVITATION_TTL_MS };
    this.invitation = invitation;
    this.invitationTimer = setTimeout(() => { if (this.invitation === invitation) { this.#clearInvitation(); this.emitChanged(); } }, INVITATION_TTL_MS + 25);
    this.invitationTimer.unref?.();
    const uri = pairingUri({ address: this.address, code, fingerprint: this.fingerprint(), name: this.hostname });
    const qr = await QRCode.toDataURL(uri, { errorCorrectionLevel: 'M', margin: QR_MARGIN_MODULES, width: QR_WIDTH_PX, color: { dark: QR_DARK, light: QR_LIGHT } });
    this.emitChanged();
    return { ...this.#invitationView(), uri, qr };
  }

  cancelInvitation() {
    this.#clearInvitation();
    this.emitChanged();
    return true;
  }

  selectAddress(address) {
    if (address !== null && !this.addresses.includes(address)) throw new Error('That address is not available on this computer.');
    this.preferredAddress = address;
    this.#saveConfig().catch(() => {});
    this.emitChanged();
    return this.snapshot();
  }

  async respondPairing(requestId, approve, teammateId = null) {
    const pending = this.pending.get(String(requestId || ''));
    if (!pending || pending.status !== PAIRING_STATUS.PENDING) throw new Error('This pairing request is no longer waiting.');
    if (pending.expiresAt <= this.now()) { this.#expirePending(pending); throw new Error('This pairing request expired. Generate a new code.'); }
    if (!approve) {
      pending.status = PAIRING_STATUS.REJECTED;
      this.#clearPendingTimer(pending.requestId);
      this.emitChanged();
      return { status: PAIRING_STATUS.REJECTED };
    }
    const teammate = this.#teammates().find(item => item.id === teammateId) || this.#teammates()[0];
    if (!teammate) throw new Error('Create a teammate before approving this phone.');
    if (this.devices.length >= MAX_PAIRED_DEVICES) throw new Error('Remove a paired phone before adding another.');
    const token = randomBytes(DEVICE_TOKEN_BYTES).toString('base64url');
    pending.status = PAIRING_STATUS.APPROVED;
    pending.teammateId = teammate.id;
    pending.token = token;
    this.emitChanged();
    return { status: PAIRING_STATUS.APPROVED, teammate: { id: teammate.id, name: teammate.name } };
  }

  async revokeDevice(deviceId) {
    const device = this.devices.find(item => item.id === deviceId);
    if (!device) throw new Error('That phone is not paired.');
    for (const run of this.runs.values()) if (run.deviceId === device.id) this.#cancelRun(run);
    this.devices = this.devices.filter(item => item.id !== device.id);
    await this.#saveDevices();
    this.emitChanged();
    return true;
  }

  async assignDevice(deviceId, teammateId) {
    const device = this.devices.find(item => item.id === deviceId);
    if (!device) throw new Error('That phone is not paired.');
    if (!this.#teammates().some(item => item.id === teammateId)) throw new Error('Choose an existing teammate.');
    device.teammateId = teammateId;
    await this.#saveDevices();
    this.emitChanged();
    return this.snapshot();
  }

  #newPairingRequest({ deviceName, platform }) {
    for (const [id, item] of this.pending) if (item.status !== PAIRING_STATUS.PENDING && this.now() - item.createdAt > PENDING_APPROVAL_TTL_MS * 2) this.pending.delete(id);
    if ([...this.pending.values()].filter(item => item.status === PAIRING_STATUS.PENDING).length >= MAX_PENDING_PAIRINGS) throw httpError(409, 'Finish the earlier pairing request first.');
    const requestId = randomUUID();
    const secret = randomBytes(PAIR_SECRET_BYTES).toString('base64url');
    const pending = {
      requestId, secret, deviceName: safeName(deviceName, MAX_DEVICE_NAME_CHARS) || 'Phone',
      platform: safeName(platform, MAX_PLATFORM_CHARS) || 'unknown',
      createdAt: this.now(), expiresAt: this.now() + PENDING_APPROVAL_TTL_MS,
      status: PAIRING_STATUS.PENDING, teammateId: null, token: null,
    };
    this.pending.set(requestId, pending);
    const timer = setTimeout(() => { if (this.pending.get(requestId) === pending) this.#expirePending(pending); }, PENDING_APPROVAL_TTL_MS + 25);
    timer.unref?.();
    this.pendingTimers.set(requestId, timer);
    this.emitChanged();
    try { this.emit({ type: 'phone-pairing-request', requestId, deviceName: pending.deviceName, platform: pending.platform }); } catch {}
    return pending;
  }

  #clearPendingTimer(requestId) {
    const timer = this.pendingTimers.get(requestId);
    if (timer) clearTimeout(timer);
    this.pendingTimers.delete(requestId);
  }

  #expirePending(pending) {
    if (pending.status === PAIRING_STATUS.CLAIMED) return;
    pending.status = PAIRING_STATUS.EXPIRED;
    pending.token = null;
    this.#clearPendingTimer(pending.requestId);
    this.emitChanged();
  }

  async #claimPairing(requestId, secret) {
    const pending = this.pending.get(requestId);
    if (!pending || !equal(pending.secret, secret)) throw httpError(404, 'Pairing request was not found.');
    if (pending.status === PAIRING_STATUS.CLAIMED) return { status: PAIRING_STATUS.CLAIMED };
    if (pending.status === PAIRING_STATUS.APPROVED) {
      if (pending.expiresAt <= this.now()) { this.#expirePending(pending); return { status: PAIRING_STATUS.EXPIRED }; }
      const token = pending.token;
      if (!token) return { status: PAIRING_STATUS.EXPIRED };
      const device = {
        id: randomUUID(), name: pending.deviceName, platform: pending.platform,
        teammateId: pending.teammateId, tokenHash: tokenHash(token),
        createdAt: new Date(this.now()).toISOString(), lastSeenAt: null,
      };
      this.devices.push(device);
      pending.status = PAIRING_STATUS.CLAIMED;
      pending.token = null;
      this.#clearPendingTimer(pending.requestId);
      await this.#saveDevices();
      this.emitChanged();
      return { status: PAIRING_STATUS.CLAIMED, token, device: { id: device.id, name: device.name } };
    }
    return { status: pending.status };
  }

  #authenticate(request) {
    const header = String(request.headers.authorization || '');
    const token = header.startsWith('Bearer ') ? header.slice(7) : '';
    if (!TOKEN_PATTERN.test(token)) return null;
    const hash = Buffer.from(tokenHash(token), 'hex');
    const device = this.devices.find(item => { const stored = Buffer.from(item.tokenHash, 'hex'); return stored.length === hash.length && timingSafeEqual(stored, hash); });
    if (!device) return null;
    device.lastSeenAt = new Date(this.now()).toISOString();
    const lastWrite = this.lastSeenWrites.get(device.id) || 0;
    if (this.now() - lastWrite > DEVICE_ONLINE_WINDOW_MS) {
      this.lastSeenWrites.set(device.id, this.now());
      void this.#saveDevices().catch(() => {});
    }
    return device;
  }

  #clean(value, limit = MAX_EVENT_DETAIL_CHARS) {
    const redacted = (() => { try { return this.engine.secretHistory?.clean?.(String(value ?? '')) ?? String(value ?? ''); } catch { return String(value ?? ''); } })();
    return redacted.slice(0, limit);
  }

  #pushEvent(run, event) {
    if (run.events.length >= MAX_RUN_EVENTS) run.events.splice(0, run.events.length - MAX_RUN_EVENTS + 1);
    run.events.push({ sequence: ++run.sequence, ...event, ...(typeof event.detail === 'string' ? { detail: event.detail.slice(0, MAX_EVENT_DETAIL_CHARS) } : {}) });
  }

  #flushText(run) {
    if (!run.textBuffer) return;
    const text = run.textBuffer; run.textBuffer = '';
    this.#pushEvent(run, { type: 'message', detail: text });
  }

  #finishRun(run, status) {
    if (run.finished) return;
    this.#flushText(run);
    run.finished = Date.now();
    run.status = status;
    run.pending = null;
    if (run.timer) clearTimeout(run.timer);
    run.timer = null;
    run.unsubscribe?.();
    run.unsubscribe = null;
    this.#pushEvent(run, { type: 'done', detail: status });
    for (const [id, item] of this.runs) if (item.finished && Date.now() - item.finished > RUN_RETENTION_MS) this.runs.delete(id);
    this.emitChanged();
  }

  #cancelRun(run) {
    if (run.finished) return;
    run.cancelled = true;
    if (this.engine.turnIds?.get(run.threadId) === run.turnId) { try { this.engine.cancel(run.threadId); } catch {} }
    this.#finishRun(run, 'cancelled');
  }

  #onEngineEvent(run, event) {
    if (run.finished || event.threadId !== run.threadId) return;
    if (run.turnId && event.turnId && event.turnId !== run.turnId) return;
    switch (event.type) {
      case 'turn-start':
        run.turnId ||= event.turnId || null;
        this.#pushEvent(run, { type: 'status', detail: 'Working on your request' });
        break;
      case 'assistant-delta':
        run.textBuffer += String(event.text || '');
        run.replyText = (run.replyText + String(event.text || '')).slice(0, MAX_REPLY_CHARS);
        if (run.textBuffer.length >= 160) this.#flushText(run);
        break;
      case 'message-end':
        this.#flushText(run);
        break;
      case 'tool-call':
        this.#flushText(run);
        run.toolNames.set(event.callId, event.name);
        this.#pushEvent(run, { type: 'tool', name: event.name, detail: typeof event.args === 'string' ? event.args : JSON.stringify(event.args ?? {}) });
        break;
      case 'tool-result':
        this.#flushText(run);
        this.#pushEvent(run, { type: 'tool-result', name: run.toolNames.get(event.callId) || 'tool', detail: String(event.text || ''), failed: Boolean(event.isError) });
        break;
      case 'approval-request':
        if (event.routineId) break;
        this.#flushText(run);
        run.pending = { id: event.requestId, name: event.toolName, detail: this.#clean(event.detail) };
        if (!run.finished) run.status = 'waiting';
        this.#pushEvent(run, { type: 'approval', name: event.toolName, detail: this.#clean(event.detail) });
        this.emitChanged();
        break;
      case 'error':
        this.#flushText(run);
        run.error = this.#clean(event.message);
        this.#pushEvent(run, { type: 'error', detail: run.error, failed: true });
        break;
      case 'turn-end':
        if (run.turnId && event.turnId !== run.turnId) break;
        this.#flushText(run);
        break;
      default:
        break;
    }
  }

  async #startRun(device, prompt) {
    const teammate = this.#teammates().find(item => item.id === device.teammateId);
    if (!teammate) throw httpError(409, 'Choose an existing teammate for this phone in desktop Settings.');
    if (this.engine.turns?.has(device.teammateId)) throw httpError(409, 'The desktop assistant is busy with another reply on this teammate.');
    if ([...this.runs.values()].some(run => run.deviceId === device.id && !run.finished)) throw httpError(409, 'This phone already has a running request.');
    if (this.runs.size >= MAX_RUNS) for (const [id, run] of this.runs) if (run.finished) this.runs.delete(id);
    await this.engine.init();
    const run = {
      id: randomUUID(), deviceId: device.id, threadId: device.teammateId, turnId: null,
      status: 'running', sequence: 0, events: [], textBuffer: '', replyText: '', reply: '',
      pending: null, error: null, finished: null, cancelled: false, timer: null,
      unsubscribe: null, toolNames: new Map(),
    };
    run.unsubscribe = this.engine.onEvent?.(event => this.#onEngineEvent(run, event)) || null;
    this.runs.set(run.id, run);
    run.timer = setTimeout(() => this.#cancelRun(run), RUN_TIMEOUT_MS);
    run.timer.unref?.();
    let started;
    try { started = await this.engine.send(device.teammateId, prompt, null, { surface: 'phone' }); }
    catch (error) {
      run.error = this.#clean(error.message || String(error));
      this.#finishRun(run, 'failed');
      throw httpError(409, run.error);
    }
    run.turnId = started?.turnId || run.turnId;
    const answer = this.engine.waitForTurn(device.teammateId);
    void Promise.resolve(answer).then(reply => {
      if (run.finished) return;
      run.reply = this.#clean(typeof reply === 'string' && reply.trim() ? reply : run.replyText, MAX_REPLY_CHARS);
      this.#finishRun(run, 'completed');
    }).catch(error => {
      if (run.finished) return;
      run.error ||= this.#clean(error?.message || String(error));
      this.#finishRun(run, 'failed');
    });
    return run;
  }

  #runView(run, after) {
    if (run.pending && !this.engine.approvals?.pending?.has(run.pending.id)) {
      run.pending = null;
      if (run.status === 'waiting' && !run.finished) run.status = 'running';
    }
    this.#flushText(run);
    return {
      id: run.id, status: run.status, pending: run.pending, reply: run.reply,
      ...(run.error ? { error: run.error } : {}),
      events: run.events.filter(event => event.sequence > after),
    };
  }

  async #readBody(request) {
    const type = String(request.headers['content-type'] || '').split(';')[0].trim().toLowerCase();
    if (type !== 'application/json') throw httpError(415, 'Send JSON to this endpoint.');
    const chunks = []; let size = 0;
    for await (const chunk of request) {
      size += chunk.length;
      if (size > MAX_REQUEST_BYTES) throw httpError(413, 'The request is too large.');
      chunks.push(chunk);
    }
    try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
    catch { throw httpError(400, 'The request could not be read.'); }
  }

  async #handle(request, response) {
    const reply = (status, data) => {
      if (response.headersSent) return;
      response.writeHead(status, {
        'content-type': 'application/json', 'cache-control': 'no-store', 'x-content-type-options': 'nosniff',
        'referrer-policy': 'no-referrer', 'content-security-policy': "default-src 'none'",
      });
      response.end(JSON.stringify(data));
    };
    try {
      // A browser page must not be able to drive this LAN service (DNS rebinding / CSRF).
      if (request.headers.origin) throw httpError(403, 'Pair phones from the Ankita app, not a web page.');
      const url = new URL(request.url || '/', 'https://pairing.invalid');
      const pathname = url.pathname.replace(/\/+$/, '') || '/';
      if (pathname === ROUTE_PAIR && request.method === 'POST') {
        const input = await this.#readBody(request);
        if (!input || typeof input !== 'object' || Object.keys(input).some(key => !['code', 'deviceName', 'platform'].includes(key))) throw httpError(400, 'Unsupported pairing request.');
        const code = normalizePairingCode(input.code);
        const invitation = this.invitation;
        if (!invitation || invitation.expiresAt <= this.now()) { this.#clearInvitation(); throw httpError(410, 'This pairing code expired. Generate a new one on the computer.'); }
        if (!code || !equal(code, invitation.code)) {
          invitation.attempts++;
          if (invitation.attempts >= MAX_INVITATION_ATTEMPTS) this.#clearInvitation();
          this.emitChanged();
          throw httpError(403, 'That pairing code is not correct. Check the computer and try again.');
        }
        this.#clearInvitation();
        if (typeof input.deviceName !== 'string' || typeof input.platform !== 'string') throw httpError(400, 'Name this phone first.');
        const pending = this.#newPairingRequest({ deviceName: input.deviceName, platform: input.platform });
        reply(202, { status: PAIRING_STATUS.PENDING, requestId: pending.requestId, secret: pending.secret, expiresAt: iso(pending.expiresAt) });
        return;
      }
      const claim = pathname.match(PAIR_ROUTE);
      if (claim && request.method === 'GET') {
        const secret = String(request.headers['x-pair-secret'] || '');
        if (!secret || secret.length > 128) throw httpError(401, 'Pairing request secret is missing.');
        reply(200, await this.#claimPairing(claim[1], secret));
        return;
      }
      if (pathname === ROUTE_REVOKE && request.method === 'POST') {
        const device = this.#authenticate(request);
        if (!device) throw httpError(401, 'Pair this phone with the desktop first.');
        await this.revokeDevice(device.id);
        reply(200, { revoked: true });
        return;
      }
      const device = this.#authenticate(request);
      if (!device) throw httpError(401, 'Pair this phone with the desktop first.');
      if (pathname === ROUTE_CAPABILITIES && request.method === 'GET') {
        const teammate = this.#teammates().find(item => item.id === device.teammateId);
        reply(200, {
          version: PHONE_PAIRING_PROTOCOL_VERSION, tools: ['desktop_run'], approvals: true,
          device: { id: device.id, name: device.name }, teammate: teammate ? { id: teammate.id, name: teammate.name } : null,
          app: { name: PAIRING_SERVICE_NAME }, computer: this.hostname, fingerprint: this.fingerprint(),
        });
        return;
      }
      if (pathname === ROUTE_RUNS && request.method === 'POST') {
        const input = await this.#readBody(request);
        if (!input || input.version !== PHONE_PAIRING_PROTOCOL_VERSION || typeof input.prompt !== 'string' || !input.prompt.trim() || input.prompt.length > MAX_PROMPT_CHARS || Object.keys(input).some(key => !['version', 'prompt'].includes(key))) throw httpError(400, 'Unsupported desktop request.');
        const run = await this.#startRun(device, input.prompt.trim());
        reply(202, { id: run.id });
        return;
      }
      const runMatch = pathname.match(RUN_ROUTE);
      if (runMatch) {
        const run = this.runs.get(runMatch[1]);
        if (!run || run.deviceId !== device.id) throw httpError(404, 'Desktop request was not found.');
        if (request.method === 'DELETE') { this.#cancelRun(run); reply(200, { cancelled: true }); return; }
        if (request.method === 'GET') {
          const after = Number(url.searchParams.get('after') || 0);
          if (!Number.isSafeInteger(after) || after < 0) throw httpError(400, 'Invalid event cursor.');
          reply(200, this.#runView(run, after));
          return;
        }
      }
      const approval = pathname.match(APPROVAL_ROUTE);
      if (approval && request.method === 'POST') {
        const input = await this.#readBody(request);
        if (!input || typeof input.allow !== 'boolean' || Object.keys(input).length !== 1) throw httpError(400, 'Invalid approval.');
        const run = this.runs.get(approval[1]);
        if (!run || run.deviceId !== device.id) throw httpError(404, 'Desktop request was not found.');
        if (!run.pending || run.pending.id !== approval[2] || run.finished) throw httpError(409, 'This approval is no longer pending.');
        const accepted = this.engine.respondApproval(approval[2], input.allow ? 'yes' : 'no');
        if (!accepted) throw httpError(409, 'This approval is no longer pending.');
        run.pending = null;
        if (run.status === 'waiting') run.status = 'running';
        reply(200, { accepted: true });
        return;
      }
      throw httpError(404, 'Unknown desktop operation.');
    } catch (error) {
      reply(error.status || 500, { error: error.status ? error.message : 'The desktop request could not be processed.' });
    }
  }
}

export { PAIRING_CONFIG_FILE, PAIRING_DEVICES_FILE, PAIRING_CERTIFICATE_FILE };
