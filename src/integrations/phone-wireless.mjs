import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';

/**
 * Wireless Android debugging, driven for the user instead of by the user.
 *
 * Android's wireless flow is two adb commands with two different ports, and the
 * device's mDNS record carries both. So the assistant can find the address
 * itself and do the pairing; the only thing that must come from the person is
 * the six-digit code, because it is displayed on the phone.
 *
 * The pairing code goes over stdin, never argv: `adb pair host port code` would
 * put the secret in the process list where any local user could read it.
 */

export const ADB_MDNS_PAIRING_SUFFIX = '._adb-tls-pairing._tcp'; // mDNS service Android advertises while the pairing dialog is open.
export const ADB_MDNS_CONNECT_SUFFIX = '._adb-tls-connect._tcp'; // The service that accepts `adb connect`.
export const ADB_MDNS_TIMEOUT_MS = 4_000; // Milliseconds; discovery returns quickly, this bounds a wedged daemon.
export const ADB_PAIR_TIMEOUT_MS = 45_000; // Milliseconds; pairing waits for the phone to accept on its side.
export const ADB_CONNECT_TIMEOUT_MS = 20_000; // Milliseconds; a TCP connect to a phone on the LAN.
export const ADB_DEVICES_TIMEOUT_MS = 15_000; // Milliseconds; normally instant, allows for a cold adb server start.
export const ADB_MAX_OUTPUT_CHARS = 1 * 1024 * 1024; // Characters/stream; a hard memory bound even for multibyte text.
export const ADB_PAIRING_CODE_PATTERN = /^\d{6}$/; // Android shows exactly six digits.
export const WIRELESS_ADDRESS_PATTERN = /^(?:[A-Za-z0-9._-]+|\[[0-9a-fA-F:]+\]):\d{1,5}$/; // host:port, IPv4 hostname or bracketed IPv6.

/** Candidate adb locations, in the order a working install is most likely. */
export function adbCandidates(env = process.env, platform = process.platform) {
  const exe = platform === 'win32' ? 'adb.exe' : 'adb';
  const roots = [env.ANDROID_HOME, env.ANDROID_SDK_ROOT].filter(Boolean);
  if (platform === 'win32' && env.LOCALAPPDATA) roots.push(path.join(env.LOCALAPPDATA, 'Android', 'Sdk'));
  if (platform === 'darwin' && env.HOME) roots.push(path.join(env.HOME, 'Library', 'Android', 'sdk'));
  if (platform !== 'win32' && env.HOME) roots.push(path.join(env.HOME, 'Android', 'Sdk'));
  return [...new Set([...roots.map(root => path.join(root, 'platform-tools', exe)), exe])]; // Bare name last: PATH is a valid install too.
}

/** The first adb that actually exists, or null. Only probes; never installs anything. */
export function findAdb({ env = process.env, platform = process.platform, exists = fs.existsSync } = {}) {
  for (const candidate of adbCandidates(env, platform)) {
    if (!path.isAbsolute(candidate)) return candidate; // Bare name resolves through PATH in spawn.
    try { if (exists(candidate)) return candidate; } catch {}
  }
  return null;
}

/** Runs a command, optionally answering its stdin prompt. Never uses a shell. */
export function runProcess(command, args, { input = null, timeoutMs = 20_000, signal, spawnImpl = spawn } = {}) {
  return new Promise((resolve) => {
    let child;
    try { child = spawnImpl(command, args, { stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true, shell: false, signal }); }
    catch (error) { resolve({ code: -1, stdout: '', stderr: error.message }); return; }
    let stdout = '', stderr = '', settled = false;
    const append = (current, chunk) => {
      if (current.length >= ADB_MAX_OUTPUT_CHARS) return current;
      const next = current + chunk;
      return next.length > ADB_MAX_OUTPUT_CHARS ? next.slice(0, ADB_MAX_OUTPUT_CHARS) : next;
    };
    const finish = (result) => { if (settled) return; settled = true; clearTimeout(timer); resolve(result); };
    const timer = setTimeout(() => {
      try { child.kill(); } catch {}
      finish({ code: -1, stdout, stderr: `${stderr}\nTimed out after ${timeoutMs} ms`.trim() });
    }, timeoutMs);
    child.stdout?.on('data', chunk => { stdout = append(stdout, chunk); });
    child.stderr?.on('data', chunk => { stderr = append(stderr, chunk); });
    child.on('error', error => finish({ code: -1, stdout, stderr: error.message }));
    child.on('close', code => finish({ code: code ?? -1, stdout, stderr }));
    if (input !== null) { try { child.stdin.end(input); } catch { try { child.stdin.end(); } catch {} } }
    else { try { child.stdin.end(); } catch {} }
  });
}

/**
 * Parses `adb mdns services`.
 *
 * adb prints one service per line: an instance name, whitespace, then the
 * "address:port". The instance name embeds the service type, and real versions
 * differ on whether a dot precedes `_adb-tls-*` (adb-1A2B-_adb-tls-connect._tcp.
 * versus adb-1A2B._adb-tls-connect._tcp.), so the type is matched anywhere in
 * the first token rather than at one fixed offset.
 */
export function parseMdnsServices(text) {
  const services = [];
  for (const raw of String(text ?? '').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || /^list of discovered/i.test(line)) continue;
    const match = /^(\S*_adb-tls-(pairing|connect)\S*)\s+(\S+?:\d{1,5})$/.exec(line);
    if (!match) continue;
    if (!WIRELESS_ADDRESS_PATTERN.test(match[3])) continue;
    services.push({ name: match[1], kind: match[2], address: match[3] });
  }
  return services;
}

/** Wireless entries from `adb devices`, e.g. "192.168.1.42:5555  device". */
export function parseWirelessDevices(text) {
  const devices = [];
  for (const raw of String(text ?? '').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || /^list of devices/i.test(line) || /^\*/.test(line)) continue;
    const match = /^(\S+?:\d{1,5})\s+(\S+)/.exec(line);
    if (!match) continue;
    devices.push({ id: match[1], state: match[2] });
  }
  return devices;
}

/** A pairing code the user read off the phone. Rejected here so it can never reach adb malformed. */
export function requirePairingCode(value) {
  const code = String(value ?? '').trim();
  if (!ADB_PAIRING_CODE_PATTERN.test(code)) throw new Error('pairing code must be the exactly six digits shown on the phone.');
  return code;
}

export function requireAddress(value) {
  const address = String(value ?? '').trim();
  if (!WIRELESS_ADDRESS_PATTERN.test(address)) throw new Error('address must look like 192.168.1.42:5555 (host:port from the phone\'s wireless debugging screen).');
  return address;
}

/** One discovered service of the wanted kind, when there is exactly one. Never guesses between phones. */
export function pickService(services, kind) {
  const matches = services.filter(service => service.kind === kind);
  return matches.length === 1 ? matches[0] : null;
}

/** adb prints different words for the same failure; this maps them to something the model can act on. */
export function explainAdbFailure(text, { step }) {
  const output = String(text ?? '').toLowerCase();
  if (/failed to authenticate|wrong pairing code|incorrect/.test(output)) return 'The pairing code was rejected. Ask the user to tap "Pair device with pairing code" again and read the new six-digit code; codes expire quickly.';
  if (/unable to connect|connection refused|timed out|no route to host/.test(output)) return `Could not reach the phone at that address. Check that it is on the same Wi-Fi network and that wireless debugging is still on. (${step})`;
  if (/protocol fault|requires an authentication/.test(output)) return 'adb rejected the request. The phone may have cancelled the pairing dialog; ask the user to reopen it.';
  return `adb ${step} failed: ${String(text ?? '').trim() || 'no output'}`;
}
