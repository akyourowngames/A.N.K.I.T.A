import http from 'node:http';
import { BrowserControl } from './browser-control.mjs';
import { CONTROL_ROUTES, CONTROL_MAX_RESULT_BYTES, CONTROL_ACCESS_REMOVED, CONTROL_REPAIR_MESSAGE } from '../browser-helper/control-protocol.mjs';
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
  constructor({ configFile, threadExists, onCapture, onBrowserChange = () => {}, now = Date.now }) {
    this.configFile = configFile; this.threadExists = threadExists; this.onCapture = onCapture; this.now = now;
    this.instanceId = randomUUID(); this.tickets = new Map(); this.captures = new Map();
    this.config = { port: 0, helpers: {} }; this.pairings = new Map(); this.server = null;
    this.onBrowserChange = onBrowserChange;
    this.browser = new BrowserControl({ activeHelper: () => {
      const id = this.config.controlHelperId, helper = this.config.helpers[id];
      return helper?.control ? { id, paused: helper.paused, resumeVersion: helper.resumeVersion } : null;
    }, onChange: onBrowserChange, now });
  }
  async persist() {
    const contents = JSON.stringify(this.config);
    const write = async () => {
      await mkdir(dirname(this.configFile), { recursive: true });
      const temp = this.configFile + '.tmp';
      await writeFile(temp, contents, { mode: PRIVATE_MODE });
      await rename(temp, this.configFile);
    };
    // Desktop settings and the companion can change grants together; serialize atomic replacements.
    this.persisting = (this.persisting || Promise.resolve()).catch(() => {}).then(write);
    return this.persisting;
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
    this.browser.close();
    if (this.gateway) { await (await this.gateway).close(); this.gateway = null; }
    if (!this.server?.listening) return;
    this.server.closeAllConnections();
    await new Promise(resolve => this.server.close(resolve));
  }
  setup({ control = false } = {}) {
    if (!this.pairings.has(control) || this.pairings.get(control).expires <= this.now()) this.pairings.set(control, { code: randomBytes(CODE_BYTES).toString('base64url'), expires: this.now() + PAIR_TTL_MS, control });
    return { address: this.address, code: this.pairings.get(control).code, instanceId: this.instanceId, paired: Object.keys(this.config.helpers).length, control };
  }
  browserStatus() { return this.browser.status(); }
  browserGateway() {
    this.gateway ||= import('./browser-extension-gateway.mjs').then(({ createBrowserExtensionGateway }) => createBrowserExtensionGateway(this.browser)).catch(error => { this.gateway = null; throw error; });
    return this.gateway;
  }
  async pauseBrowser(paused) {
    const helper = this.config.helpers[this.config.controlHelperId];
    if (helper?.control) { helper.paused = paused === true; if (!paused) helper.resumeVersion = (helper.resumeVersion || 0) + 1; await this.persist(); this.browser.interrupt(); }
    return this.browserStatus();
  }
  async revokeBrowser() {
    const helper = this.config.helpers[this.config.controlHelperId];
    if (helper) { delete helper.control; delete helper.paused; }
    delete this.config.controlHelperId;
    await this.persist(); this.browser.interrupt(); return this.browserStatus();
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
      if (request.method !== 'POST' || ![...Object.values(ROUTES), ...Object.values(CONTROL_ROUTES)].includes(request.url)) throw fail(404, 'Unknown companion capture endpoint');
      const credential = Object.entries(this.config.helpers).find(([, item]) => item.origin === origin && equal(request.headers.authorization, 'Bearer ' + item.token));
      if (request.url !== ROUTES.pair && !credential) throw Object.assign(fail(401, 'Pair this browser helper with ANKITA first'), Object.values(CONTROL_ROUTES).includes(request.url) ? { code: CONTROL_ACCESS_REMOVED } : {});
      const chunks = []; let size = 0;
      for await (const chunk of request) { size += chunk.length; if (size > (Object.values(CONTROL_ROUTES).includes(request.url) ? CONTROL_MAX_RESULT_BYTES : MAX_REQUEST_BYTES)) throw fail(413, CAPTURE_ERRORS.tooLarge); chunks.push(chunk); }
      let body;
      try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { throw fail(400, CAPTURE_ERRORS.unreadableRequest); }
      if (!body || typeof body !== 'object') throw fail(400, CAPTURE_ERRORS.unreadableRequest);
      if (request.url === ROUTES.pair) {
        const pairing = [...this.pairings.values()].find(item => item.expires > this.now() && equal(body.code, item.code));
        if (!pairing) throw fail(403, 'Pairing code expired; copy a new code from ANKITA');
        const helperId = body.helperId || randomUUID();
        if (!UUID.test(helperId)) throw fail(400, 'Invalid browser helper identity');
        const previous = this.config.helpers[helperId];
        if (previous && previous.origin !== origin) throw fail(403, 'Pair each browser helper separately');
        if (Object.keys(this.config.helpers).length >= MAX_PENDING_CAPTURES && !previous) throw fail(409, 'Too many paired helpers');
        const token = randomBytes(TOKEN_BYTES).toString('base64url');
        const control = pairing.control === true, previousControlId = this.config.controlHelperId;
        this.config.helpers[helperId] = { origin, token, ...(control ? { control: true } : {}) };
        if (control) this.config.controlHelperId = helperId;
        this.pairings.delete(control);
        try { await this.persist(); } catch (error) { if (previous) this.config.helpers[helperId] = previous; else delete this.config.helpers[helperId]; this.config.controlHelperId = previousControlId; throw error; }
        if (control) { this.browser.interrupt(); this.onBrowserChange(); }
        reply(200, { token, helperId, instanceId: this.instanceId, control }); return;
      }
      if (Object.values(CONTROL_ROUTES).includes(request.url)) {
        const [helperId, helper] = credential;
        if (!helper.control || helperId !== body.helperId || this.config.controlHelperId !== helperId) throw Object.assign(fail(403, CONTROL_REPAIR_MESSAGE), { code: CONTROL_ACCESS_REMOVED });
        if (request.url === CONTROL_ROUTES.status) { reply(200, this.browserStatus()); return; }
        if (request.url === CONTROL_ROUTES.resume) { reply(200, await this.pauseBrowser(false)); return; }
        if (request.url === CONTROL_ROUTES.revoke) { reply(200, await this.revokeBrowser()); return; }
        if (request.url === CONTROL_ROUTES.disconnect) { reply(200, await this.pauseBrowser(true)); return; }
        if (request.url === CONTROL_ROUTES.connect) { reply(200, this.browser.connect(helperId, body.clientId)); return; }
        if (request.url === CONTROL_ROUTES.claim) { reply(200, this.browser.claim(helperId, body)); return; }
        if (request.url === CONTROL_ROUTES.next) {
          const controller = new AbortController(), cancel = () => controller.abort();
          response.once('close', cancel);
          try { const next = await this.browser.next(helperId, body.sessionId, controller.signal); if (!response.destroyed) reply(200, next); }
          finally { response.removeListener('close', cancel); }
          return;
        }
        if (request.url === CONTROL_ROUTES.result) { reply(200, this.browser.result(helperId, body)); return; }
        throw fail(404, 'Unknown browser endpoint');
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
    } catch (error) { if (!response.writableEnded && !response.destroyed) reply(error.status || 500, { error: error.status ? error.message : 'Companion capture could not be delivered', ...(error.code === CONTROL_ACCESS_REMOVED ? { code: error.code } : {}) }); }
  }
}
