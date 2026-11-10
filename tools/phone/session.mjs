import fs from 'node:fs';
import path from 'node:path';
import { McpStore } from '../../src/integrations/mcp-store.mjs';
import { MCP_FILE } from '../../src/core/config.mjs';
import { formatToolResult, toolResultText } from '../../src/integrations/mcp-client.mjs';
import {
  PHONE_MCP_ID, PHONE_MCP_COMMAND, PHONE_MCP_ARGS, PHONE_ENV, PHONE_DOCS, PHONE_LABEL, PHONE_MCP_TOOLS,
  PHONE_REQUEST_TIMEOUT_MS, PHONE_INIT_TIMEOUT_MS, PHONE_SCREENSHOT_DIRECTORY,
  PHONE_SCREENSHOT_MAX_BYTES, PHONE_DEFAULT_SCREENSHOT_MAX_PX, PHONE_TEMP_ROOT,
  PHONE_ACTIONS, PHONE_ACTION_NAMES, PHONE_DESTRUCTIVE_ACTIONS,
  rawCall, parseDevices, describeDevices, deviceExists, phoneScreenshotReceipt, phoneScreenshotName,
  phoneSetupHint,
} from '../../src/integrations/phone-control.mjs';
import {
  ADB_MDNS_TIMEOUT_MS, ADB_PAIR_TIMEOUT_MS, ADB_CONNECT_TIMEOUT_MS, ADB_DEVICES_TIMEOUT_MS,
  findAdb, runProcess, parseMdnsServices, requirePairingCode, requireAddress, pickService, explainAdbFailure,
} from '../../src/integrations/phone-wireless.mjs';

/**
 * Live phone control for one host process.
 *
 * Same shape as the browser manager: a module-level singleton that connects
 * lazily, remembers the selected device, and is closed once at shutdown. The
 * MCP server behind it is hidden from the MCP list, because this class - not
 * the user - owns its record, approval and lifecycle.
 */

const CONNECT_APPROVAL_NOTE = 'This downloads and runs the phone-control bridge, then lets the assistant read and drive a connected phone.';

/** The exact command a connect would run, shown in the approval prompt. */
export function connectApprovalText() {
  return [
    `Start phone control\n\n  command: ${PHONE_MCP_COMMAND} ${PHONE_MCP_ARGS.join(' ')}\n\n${CONNECT_APPROVAL_NOTE}`,
    phoneSetupHint(),
    `Docs: ${PHONE_DOCS}`,
  ].join('\n');
}
export class PhoneSession {
  constructor({ mcp = null, mcpFile = MCP_FILE, env = process.env, platform = process.platform, exists = fs.existsSync, exec = runProcess } = {}) {
    this.mcp = mcp;
    this.mcpFile = mcpFile;
    this.env = env;
    this.platform = platform;
    this.exists = exists;
    this.exec = exec; // Injected in tests; never a shell.
    this.adbPath = null;
    this.device = null; // Selected device id; mobile-mcp has no implicit current device.
    this.devices = null; // Last device list, so `use` cannot name a device that was never seen.
    this.wirelessAddress = null; // Last wireless endpoint, so a dropped link can be restored without asking.
    this.connecting = null;
    this.connectionProblem = null; // Last start failure, reported verbatim instead of thrown at the model.
  }

  get connected() { return Boolean(this.mcp?.has?.(PHONE_MCP_ID)); }

  /** The workspace root for artifacts, taken from the live call context. */
  root(ctx = {}) { return path.resolve(ctx.workspacePath || ctx.cwd || process.cwd()); }

  /** A temp path the MCP server is always allowed to write, copied into the workspace afterwards. */
  nextScreenshotPath() {
    return path.join(PHONE_TEMP_ROOT, `ankita-${phoneScreenshotName()}`);
  }

  async ensureConnected(ctx = {}) {
    if (this.connected) return;
    if (this.connecting) return this.connecting;
    if (!this.mcp) throw new Error('Phone control needs a connected MCP manager in this session.');
    this.connecting = this.connect(ctx).finally(() => { this.connecting = null; });
    return this.connecting;
  }

  /**
   * Connects through the same MCP manager every other server uses.
   *
   * The record is written hidden and manual-start so the daemon's reconcile
   * loop never spawns a phone bridge the user did not ask for on this call. The
   * approval is bound to the command hash, so a version change asks again.
   */
  async connect(ctx = {}) {
    const store = new McpStore(this.mcpFile || MCP_FILE).load();
    const previous = store.find(PHONE_MCP_ID);
    if (previous) store.remove(PHONE_MCP_ID);
    const record = store.add({
      id: PHONE_MCP_ID,
      name: PHONE_LABEL,
      command: PHONE_MCP_COMMAND,
      args: [...PHONE_MCP_ARGS],
      env: { ...PHONE_ENV },
      hidden: true,
      manualStart: true,
      allowedTools: PHONE_MCP_TOOLS,
      terminateTree: true,
    });
    store.markApproved(PHONE_MCP_ID);
    try {
      await this.mcp.connect({
        ...record,
        signal: ctx.signal,
        requestTimeoutMs: PHONE_REQUEST_TIMEOUT_MS,
        initTimeoutMs: PHONE_INIT_TIMEOUT_MS,
      });
      store.markConnected(PHONE_MCP_ID, true, null);
      this.connectionProblem = null;
    } catch (error) {
      store.setEnabled(PHONE_MCP_ID, false);
      store.markConnected(PHONE_MCP_ID, false, error.message);
      this.connectionProblem = `Error: phone control could not start: ${error.message}. ${phoneSetupHint()}`;
      throw new Error(this.connectionProblem.slice('Error: '.length));
    }
  }

  /** Calls one allow-listed mobile-mcp tool and returns its native result. */
  async call(tool, args = {}, ctx = {}) {
    const found = this.mcp?.findTool?.(`mcp__${PHONE_MCP_ID}__${tool}`);
    if (!found) {
      const available = this.mcp?.servers?.get?.(PHONE_MCP_ID)?.tools?.map(t => t.name) || [];
      throw new Error(`This phone bridge does not offer ${tool}${available.length ? ` (it offers: ${available.join(', ')})` : ''}.`);
    }
    return this.mcp.callToolResult(`mcp__${PHONE_MCP_ID}__${tool}`, args, { signal: ctx.signal });
  }

  async text(tool, args, ctx) {
    const result = await this.call(tool, args, ctx);
    const text = formatToolResult({ text: toolResultText(result?.raw ?? result), isError: result?.isError });
    if (result?.isError) throw new Error(text);
    return text;
  }

  /** The public entry point used by the `phone` tool. */
  async run(args = {}, ctx = {}) {
    const action = String(args.action || '').toLowerCase();
    if (!PHONE_ACTION_NAMES.includes(action)) {
      return `Error: unknown phone action "${action || '(none)'}". Use one of: ${PHONE_ACTION_NAMES.join(', ')}.`;
    }

    if (action === 'disconnect') return this.disconnect();
    if (action === 'use') return this.use(args);
    if (action === 'wireless') return this.wirelessScan(ctx);
    if (action === 'wireless_pair') return this.wirelessPair(args, ctx);
    if (action === 'wireless_connect') return this.wirelessConnect(args, ctx);
    if (action === 'devices') return this.guarded(() => this.listDevices(ctx));

    await this.ensureConnected(ctx).catch(() => {});
    if (!this.connected) return this.connectionProblem;
    if (!this.device) {
      const listed = await this.listDevices(ctx);
      const parsed = this.devices || [];
      if (!parsed.length) return listed;
      if (parsed.length > 1) return `${listed}\n\nSeveral phones are available. Pick one with action="use" and its exact id before doing anything else.`;
    }

    if (action === 'raw') return this.raw(args, ctx);
    if (action === 'screenshot') return this.screenshot(args, ctx);
    return this.curated(action, args, ctx);
  }

  /** Runs a listing step and turns a connection failure into a readable error. */
  async guarded(run) {
    try {
      await this.ensureConnected();
      return await run();
    } catch (error) {
      return `Error: ${error.message}`;
    }
  }

  async listDevices(ctx) {
    await this.ensureConnected(ctx);
    let text = await this.text('mobile_list_available_devices', {}, ctx);
    let devices = parseDevices(text);
    // A wireless phone drops after sleep or a router blip. One silent reconnect
    // is cheaper for the user than being told to run adb by hand.
    if (devices && devices.length === 0 && this.wirelessAddress) {
      if (await this.reviveWireless(ctx)) {
        text = await this.text('mobile_list_available_devices', {}, ctx);
        devices = parseDevices(text);
        if (devices?.length) ctx.reconnectedWireless = this.wirelessAddress;
      }
    }
    if (devices) {
      this.devices = devices;
      if (this.device && !deviceExists(devices, this.device)) this.device = null;
      // One attached phone needs no ceremony: select it so the next action works.
      if (!this.device && devices.length === 1) this.device = devices[0].id;
    }
    const listed = devices ? describeDevices(devices) : text;
    if (!devices?.length) {
      return `No local phone, emulator or simulator is available.\n${text}\n\nStart an Android emulator, plug in a phone with USB debugging on, or set up wireless debugging with action="wireless".`;
    }
    return `Available phones:\n${listed}${this.device ? `\n\nActive: ${this.device}` : ''}${ctx.reconnectedWireless ? `\n(reconnected ${ctx.reconnectedWireless} automatically)` : ''}`;
  }

  /** All adb work goes through here so tests can inject a runner and no code spells out a path. */
  async adb(args, { input = null, timeoutMs = ADB_DEVICES_TIMEOUT_MS, signal } = {}) {
    const command = this.adbPath ||= findAdb({ env: this.env, platform: this.platform, exists: this.exists });
    if (!command) return { code: -1, stdout: '', stderr: 'adb was not found. Install Android SDK Platform Tools, or set ANDROID_HOME to your SDK folder.' };
    return this.exec(command, args, { input, timeoutMs, signal });
  }

  /** One mDNS query, shared by scan and pair so pairing never asks the daemon twice. */
  async scanMdns(ctx = {}) {
    const result = await this.adb(['mdns', 'services'], { timeoutMs: ADB_MDNS_TIMEOUT_MS, signal: ctx.signal });
    return { error: result.code === -1 && /not found/.test(result.stderr) ? result.stderr : null, services: parseMdnsServices(result.stdout) };
  }

  /**
   * Finds a phone offering wireless debugging.
   *
   * Android advertises two mDNS services: one that accepts a pairing code and
   * one that accepts `adb connect`. They use different ports, which is why
   * pairing then connecting by hand goes wrong so often.
   */
  async wirelessScan(ctx = {}) {
    const { error, services } = await this.scanMdns(ctx);
    if (error) return `Error: ${error}`;
    const pairing = services.filter(service => service.kind === 'pairing');
    const connect = services.filter(service => service.kind === 'connect');
    if (!pairing.length && !connect.length) {
      return [
        'No phone is advertising wireless debugging on this network.',
        'On the phone, open Settings → Developer options → Wireless debugging and turn it on.',
        'To pair a new phone, tap "Pair device with pairing code" and leave that dialog open, then ask me again.',
        'Both devices must be on the same Wi-Fi network.',
      ].join('\n');
    }
    const lines = ['Wireless phones found:'];
    for (const service of pairing) lines.push(`  pairing ${service.address}`);
    for (const service of connect) lines.push(`  connect ${service.address}`);
    if (pairing.length) {
      lines.push('', 'This phone is ready to pair. Tell me the six-digit code shown on it and I will connect it.');
    } else {
      lines.push('', 'No pairing dialog is open. If the phone was already paired, use action="wireless_connect".');
    }
    if (connect.length === 1) this.wirelessAddress = connect[0].address; // Remember only an unambiguous phone.
    return lines.join('\n');
  }

  /** Pairs with the phone whose dialog is open. The code is the only thing the user must supply. */
  async wirelessPair(args = {}, ctx = {}) {
    let code, address;
    try {
      code = requirePairingCode(args.code || args.pairingCode);
      if (args.address) address = requireAddress(args.address);
    } catch (error) {
      return `Error: ${error.message}`;
    }
    const { error, services } = await this.scanMdns(ctx);
    if (error) return `Error: ${error}`;
    const chosen = address || pickService(services, 'pairing')?.address;
    if (!chosen) {
      return 'Error: I could not find exactly one phone waiting to pair. Keep the "Pair device with pairing code" dialog open on the phone and try again; if several phones are shown, pass the pairing address.';
    }
    // The code goes over stdin so it never appears in the process list.
    const result = await this.adb(['pair', chosen], { input: `${code}\n`, timeoutMs: ADB_PAIR_TIMEOUT_MS, signal: ctx.signal });
    const output = `${result.stdout}\n${result.stderr}`.trim();
    if (!/successfully paired/i.test(output)) return `Error: ${explainAdbFailure(output, { step: 'pair' })}`;
    // Android advertises the connect endpoint alongside the pairing one, so the
    // user does not have to read a second port off the phone.
    let connect = pickService(services, 'connect');
    if (!connect) {
      // The connect endpoint can start advertising only after pairing finishes,
      // so scan once more rather than making the user read a port.
      connect = pickService((await this.scanMdns(ctx)).services, 'connect');
    }
    if (connect) {
      const connected = await this.adb(['connect', connect.address], { timeoutMs: ADB_CONNECT_TIMEOUT_MS, signal: ctx.signal });
      if (/connected to/i.test(`${connected.stdout}${connected.stderr}`)) {
        this.wirelessAddress = connect.address;
        return `Paired and connected. The phone is now available.\n  address: ${connect.address}\n\nCall action="devices" to start using it.`;
      }
    }
    return 'Paired successfully, but the phone did not accept the connection yet. Keep the Wireless debugging screen open on the phone and ask me to reconnect; I will find it over the network.';
  }

  /** Connects to an already-paired phone. Remembers the address so a dropped link can be restored later. */
  async wirelessConnect(args = {}, ctx = {}) {
    let address;
    try { address = requireAddress(args.address || this.wirelessAddress || ''); }
    catch { return 'Error: Give the phone\'s "IP address & port" from its Wireless debugging screen, or run action="wireless" first so I can find it.'; }
    const result = await this.adb(['connect', address], { timeoutMs: ADB_CONNECT_TIMEOUT_MS, signal: ctx.signal });
    const output = `${result.stdout}${result.stderr}`.trim();
    if (/connected to/i.test(output)) {
      this.wirelessAddress = address;
      return `Connected to ${address}. Call action="devices" to start using it.`;
    }
    return `Error: ${explainAdbFailure(output, { step: 'connect' })}`;
  }

  /** After a drop, try the address we already know once. Silent when there is nothing to try. */
  async reviveWireless(ctx = {}) {
    if (!this.wirelessAddress) return false;
    const result = await this.adb(['connect', this.wirelessAddress], { timeoutMs: ADB_CONNECT_TIMEOUT_MS, signal: ctx.signal });
    return /connected to/i.test(`${result.stdout}${result.stderr}`);
  }

  use(args = {}) {
    const id = String(args.device || args.id || args.name || '').trim();
    if (!id) return 'Error: device is required. Call action="devices" and pass the exact id.';
    if (!deviceExists(this.devices, id)) {
      return `Error: "${id}" was not in the last device list. Call action="devices" and copy an exact id; do not guess.`;
    }
    this.device = id;
    return `Active phone: ${id}`;
  }

  async curated(action, args, ctx) {
    let mapped;
    try {
      mapped = PHONE_ACTIONS[action](args, this);
    } catch (error) {
      return `Error: ${error.message}`;
    }
    return this.text(mapped.tool, mapped.args, ctx);
  }

  async raw(args, ctx) {
    let mapped;
    try {
      mapped = rawCall(args, this);
    } catch (error) {
      return `Error: ${error.message}`;
    }
    if (mapped.error) return `Error: ${mapped.error}`;
    return this.text(mapped.tool, mapped.args, ctx);
  }

  /**
   * Saves to a temp file, then copies into the workspace artifact folder.
   *
   * mobile-mcp only writes inside its own cwd or the system temp directory, and
   * the bridge's cwd is not the user's workspace. So the capture lands in temp
   * first and the workspace copy - the one the model and UI can read - is made
   * here, size-checked, with the receipt the host turns into an attached image.
   */
  async screenshot(args, ctx) {
    // The bridge writes to temp; the workspace copy below is the artifact the
    // host attaches and the UI can preview.
    const temp = this.nextScreenshotPath();
    const maxSize = Number(args.maxSize) > 0 ? Number(args.maxSize) : PHONE_DEFAULT_SCREENSHOT_MAX_PX;
    await this.text('mobile_save_screenshot', { device: this.device, saveTo: temp, maxSize }, ctx);
    const stat = fs.existsSync(temp) ? fs.statSync(temp) : { size: 0, isFile: () => false };
    if (!stat.isFile() || stat.size <= 0 || stat.size > PHONE_SCREENSHOT_MAX_BYTES) {
      try { fs.rmSync(temp, { force: true }); } catch {}
      return `Error: the phone returned an unusable screenshot (${stat.size} bytes).`;
    }
    const folder = path.join(this.root(ctx), PHONE_SCREENSHOT_DIRECTORY);
    fs.mkdirSync(folder, { recursive: true });
    const name = phoneScreenshotName();
    const dest = path.join(folder, name);
    fs.copyFileSync(temp, dest);
    try { fs.rmSync(temp, { force: true }); } catch {}
    const receipt = phoneScreenshotReceipt({ relativePath: path.posix.join(PHONE_SCREENSHOT_DIRECTORY, name), bytes: stat.size, device: this.device });
    return JSON.stringify({ ...receipt, note: 'Latest capture only. Re-read the screen with action="see" before the next tap.' });
  }

  async disconnect() {
    if (!this.mcp?.has?.(PHONE_MCP_ID)) {
      this.device = null;
      return 'Phone control is not connected.';
    }
    await this.mcp.disconnect(PHONE_MCP_ID);
    this.device = null;
    return 'Phone control disconnected.';
  }

  /** Called at process shutdown. Never throws: teardown must not block exit. */
  async close() {
    try { await this.mcp?.disconnect?.(PHONE_MCP_ID); } catch {}
  }
}

/**
 * One session per MCP manager, because that manager owns the live connection.
 * A module-level singleton would bind to whichever host imported it first and
 * then serve a dead or foreign connection to every later one.
 */
const sessions = new WeakMap();
export function phoneSessionFor(mcp) {
  if (!mcp) return null;
  let session = sessions.get(mcp);
  if (!session) { session = new PhoneSession({ mcp }); sessions.set(mcp, session); }
  return session;
}

/** The session for whatever manager this call context carries. */
export function phoneSession(ctx = {}) {
  return ctx.phoneSession || phoneSessionFor(ctx.mcp);
}

/** Pure check used by the tool descriptor and by tests: which actions change the phone. */
export function isDestructive(action) { return PHONE_DESTRUCTIVE_ACTIONS.includes(String(action || '')); }
