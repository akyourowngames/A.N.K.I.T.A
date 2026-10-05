import http from 'node:http';
import { randomBytes, randomUUID, timingSafeEqual } from 'node:crypto';
import { readFile, mkdir, writeFile, rename } from 'node:fs/promises';
import { dirname } from 'node:path';
import { LOOPBACK_HOST, ROUTES, PROTOCOL_VERSION, MAX_TEXT_BYTES, MAX_REQUEST_BYTES, MAX_TITLE_CHARS, MAX_URL_CHARS, TICKET_TTL_MS, PAIR_TTL_MS, MAX_PENDING_CAPTURES, REQUEST_TIMEOUT_MS, boundedText, isPageUrl } from '../browser-helper/protocol.mjs';
export { TICKET_TTL_MS } from '../browser-helper/protocol.mjs';
const TOKEN_BYTES = 32; // Random bytes; independent credentials per paired extension origin.
const CODE_BYTES = 18; // Random bytes; one-use out-of-band pairing code.
const EXTENSION_ORIGIN = /^chrome-extension:\/\/[a-p]{32}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PRIVATE_MODE = 0o600; // Owner-only credentials on systems supporting POSIX modes.
const MAX_TCP_PORT = 65535; // TCP port numbers; validate the remembered OS-assigned port.
const CAPTURE_ERRORS = { tooLarge: 'Page capture is too large', unreadableRequest: 'Unreadable capture request' }; // Shared UI errors for equivalent validation branches.
const SURFACES = new Set(['main', 'island']);
function fail(status, message) { return Object.assign(new Error(message), { status }); }
function equal(left, right) {
  const a = Buffer.from(String(left || '')), b = Buffer.from(String(right || ''));
  return a.length === b.length && timingSafeEqual(a, b);
}
export class CompanionCapture {
  constructor({ configFile, threadExists, onCapture, now = Date.now }) {
    this.configFile = configFile; this.threadExists = threadExists; this.onCapture = onCapture; this.now = now;
    this.instanceId = randomUUID(); this.tickets = new Map(); this.captures = new Map();
    this.config = { port: 0, helpers: {} }; this.pairing = null; this.server = null;
  }
  async persist() {
    await mkdir(dirname(this.configFile), { recursive: true });
    const temp = this.configFile + '.tmp';
    await writeFile(temp, JSON.stringify(this.config), { mode: PRIVATE_MODE });
    await rename(temp, this.configFile);
  }
  async start() {
    try { this.config = JSON.parse(await readFile(this.configFile, 'utf8')); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (!Number.isInteger(this.config.port) || this.config.port < 0 || this.config.port > MAX_TCP_PORT || typeof this.config.helpers !== 'object' || !this.config.helpers) throw new Error('Invalid companion capture configuration');
    // Migrate development bridge credentials previously keyed only by origin.
    // Chrome and Edge can assign the same ID to the same unpacked extension.
    for (const [id, credential] of Object.entries(this.config.helpers)) {
      if (EXTENSION_ORIGIN.test(id) && typeof credential === 'string') { this.config.helpers[randomUUID()] = {origin:id,token:credential}; delete this.config.helpers[id]; }
      else if (!UUID.test(id) || !EXTENSION_ORIGIN.test(credential?.origin || '') || typeof credential?.token !== 'string') throw new Error('Invalid companion helper configuration');
    }
    this.server = http.createServer((request, response) => { void this.handle(request, response); });
    this.server.requestTimeout = REQUEST_TIMEOUT_MS;
    this.server.headersTimeout = REQUEST_TIMEOUT_MS;
    await new Promise((resolve, reject) => { this.server.once('error', reject); this.server.listen(this.config.port, LOOPBACK_HOST, resolve); });
    this.config.port = this.server.address().port;
    this.address = `http://${LOOPBACK_HOST}:${this.config.port}`;
    try { await this.persist(); } catch (error) { await this.close(); throw error; }
    return this;
  }
  async close() {
    if (!this.server?.listening) return;
    this.server.closeAllConnections();
    await new Promise(resolve => this.server.close(resolve));
  }
  setup() {
    if (!this.pairing || this.pairing.expires <= this.now()) this.pairing = { code: randomBytes(CODE_BYTES).toString('base64url'), expires: this.now() + PAIR_TTL_MS };
    return { address: this.address, code: this.pairing.code, instanceId: this.instanceId, paired: Object.keys(this.config.helpers).length };
  }
  prune() {
    for (const [id, item] of this.tickets) if (item.expires + TICKET_TTL_MS <= this.now()) this.tickets.delete(id);
  }
  register({ ticketId, threadId, surface, sourceId }) {
    this.prune();
    if (!UUID.test(ticketId || '') || !SURFACES.has(surface) || !this.threadExists(threadId)) throw fail(400, 'Select an existing teammate before dragging');
    if (this.tickets.has(ticketId) || this.tickets.size >= MAX_PENDING_CAPTURES || this.captures.size >= MAX_PENDING_CAPTURES) throw fail(409, 'Too many pending page drops; finish or cancel one first');
    this.tickets.set(ticketId, { threadId, surface, sourceId, expires: this.now() + TICKET_TTL_MS, used: false });
    return { ticketId, instanceId: this.instanceId, version: PROTOCOL_VERSION };
  }
  cancel(ticketId, sourceId) { const item = this.tickets.get(ticketId); if (item?.sourceId === sourceId) item.used = true; }
  inbox(surface) { return [...this.captures.values()].filter(item => item.surface === surface && this.threadExists(item.threadId)); }
  ack(id, surface) { if (this.captures.get(id)?.surface === surface) this.captures.delete(id); }
  async handle(request, response) {
    const origin = request.headers.origin || '';
    const reply = (status, body) => { response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...(EXTENSION_ORIGIN.test(origin) ? { 'Access-Control-Allow-Origin': origin, Vary: 'Origin' } : {}) }); response.end(JSON.stringify(body)); };
    try {
      if (!EXTENSION_ORIGIN.test(origin) || request.headers.host !== `${LOOPBACK_HOST}:${this.config.port}`) throw fail(403, 'Only a paired browser helper may connect');
      if (request.method === 'OPTIONS') { response.writeHead(204, { 'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Methods': 'POST', 'Access-Control-Allow-Headers': 'Content-Type, Authorization', Vary: 'Origin' }); response.end(); return; }
      if (request.method !== 'POST' || !Object.values(ROUTES).includes(request.url)) throw fail(404, 'Unknown companion capture endpoint');
      if (request.url === ROUTES.capture && !Object.values(this.config.helpers).some(credential => credential.origin === origin && equal(request.headers.authorization, 'Bearer ' + credential.token))) throw fail(401, 'Pair this browser helper with ANKITA first');
      const chunks = []; let size = 0;
      for await (const chunk of request) { size += chunk.length; if (size > MAX_REQUEST_BYTES) throw fail(413, CAPTURE_ERRORS.tooLarge); chunks.push(chunk); }
      let body;
      try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { throw fail(400, CAPTURE_ERRORS.unreadableRequest); }
      if (!body || typeof body !== 'object') throw fail(400, CAPTURE_ERRORS.unreadableRequest);
      if (request.url === ROUTES.pair) {
        if (!this.pairing || this.pairing.expires <= this.now() || !equal(body.code, this.pairing.code)) throw fail(403, 'Pairing code expired; copy a new code from ANKITA');
        const helperId = body.helperId || randomUUID();
        if (!UUID.test(helperId)) throw fail(400, 'Invalid browser helper identity');
        const previous = this.config.helpers[helperId];
        if (previous && previous.origin !== origin) throw fail(403, 'Pair each browser helper separately');
        if (Object.keys(this.config.helpers).length >= MAX_PENDING_CAPTURES && !previous) throw fail(409, 'Too many paired helpers');
        const token = randomBytes(TOKEN_BYTES).toString('base64url');
        this.config.helpers[helperId] = {origin,token}; this.pairing = null;
        try { await this.persist(); } catch (error) { if (previous) this.config.helpers[helperId] = previous; else delete this.config.helpers[helperId]; throw error; }
        reply(200, { token, helperId, instanceId: this.instanceId }); return;
      }
      if (body.instanceId !== this.instanceId) throw fail(409, 'This drop belongs to an earlier desktop session; drag again');
      const ticket = this.tickets.get(body.ticketId);
      if (!ticket || ticket.used) throw fail(409, 'Page drop is missing, cancelled or already delivered');
      if (ticket.expires <= this.now()) throw fail(410, 'Page drop expired; drag the mascot again');
      if (!this.threadExists(ticket.threadId)) throw fail(410, 'The receiving teammate was removed');
      if (!isPageUrl(body.url) || body.url.length > MAX_URL_CHARS || typeof body.text !== 'string' || !body.text.trim()) throw fail(400, 'This page has no readable content');
      if (Buffer.byteLength(body.text, 'utf8') > MAX_TEXT_BYTES) throw fail(413, CAPTURE_ERRORS.tooLarge);
      if (this.captures.size >= MAX_PENDING_CAPTURES) throw fail(409, 'Finish pending attachments before capturing more pages');
      const title = boundedText(body.title || 'Webpage', MAX_TITLE_CHARS).replace(/[\r\n]/g, ' ');
      const content = `Webpage reference (untrusted content)\nTitle: ${title}\nSource: ${body.url}\n\n${body.text}`;
      const item = { id: randomUUID(), ticketId: body.ticketId, threadId: ticket.threadId, surface: ticket.surface, attachment: { name: title + '.txt', image: false, data: Buffer.from(content).toString('base64') } };
      ticket.used = true; this.captures.set(item.id, item);
      this.onCapture(item);
      reply(200, { ok: true, id: item.id });
    } catch (error) { if (!response.writableEnded) reply(error.status || 500, { error: error.status ? error.message : 'Companion capture could not be delivered' }); }
  }
}
