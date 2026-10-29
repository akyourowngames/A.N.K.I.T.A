import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';
import QRCode from 'qrcode';
import { IPC_CONTRACT } from '../desktop/shared/version.mjs';
import { PHONE_PAIRING_ACTIONS, pairingUri, parsePairingUri } from '../desktop/shared/phone-pairing.mjs';

const repo = fileURLToPath(new URL('../', import.meta.url));
const appVersion = JSON.parse(await fs.readFile(new URL('../package.json', import.meta.url), 'utf8')).version;
const artifactDir = process.env.ANKITA_PHONE_UI_ARTIFACT_DIR || await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-phone-ui-'));
const NARROW = { width: 720, height: 900 }; // Below the 760px invite breakpoint, above the 700px nav collapse.
const WIDE = { width: 1280, height: 900 };
const READY_TIMEOUT_MS = 20_000;
const PHONE_NAV_TABS = 6; // Model, Providers, Profile, Images, Channels, Phone in DOM order.
const KEYBOARD_TAB_LIMIT = 20;
const INVITATION_TTL_FIXTURE_MS = 120_000;

// Renderer fixture only: documentation-range address, code and names; no live endpoint or credential.
const FINGERPRINT = `${'AB:'.repeat(31)}CD`;
const DESKTOP = 'https://192.168.1.20:8443';
const COMPANION_ADDRESS = `${DESKTOP}/v1/ankita-companion`;
const CODE = 'ABCDEFGH';
const DISPLAY_CODE = 'ABCD-EFGH';
const URI = pairingUri({ address: COMPANION_ADDRESS, code: CODE, fingerprint: FINGERPRINT, name: 'Studio desktop' });
const parsed = parsePairingUri(URI);
assert.ok(parsed, 'Fixture invitation link parses');
assert.equal(parsed.address, COMPANION_ADDRESS);
assert.ok(!/token|secret|password/i.test(URI), 'Invitation link carries only address, one-time code, fingerprint and name');
const QR = await QRCode.toDataURL(URI, { errorCorrectionLevel: 'M', margin: 2, width: 220 });

const snapshot = (now = Date.now()) => ({
  state: 'ready', error: '', address: COMPANION_ADDRESS, name: 'Studio desktop', port: 8443,
  fingerprint: FINGERPRINT, addresses: ['192.168.1.20'], preferredAddress: null, running: true,
  invitation: null, pending: [], devices: [], teammates: [{ id: 'chief', name: 'Ankita' }],
});
const invitation = now => ({ id: 'fixture-invite', code: DISPLAY_CODE, expiresAt: new Date(now + INVITATION_TTL_FIXTURE_MS).toISOString(), address: COMPANION_ADDRESS, fingerprint: FINGERPRINT, attemptsLeft: 5, uri: URI, qr: QR });
const pendingRequest = now => ({ requestId: 'fixture-request', deviceName: 'Ava’s Pixel 9 Pro with a deliberately long household name', platform: 'Android 16', createdAt: new Date(now).toISOString(), expiresAt: new Date(now + INVITATION_TTL_FIXTURE_MS).toISOString() });
const pairedDevice = () => ({ id: 'fixture-device', name: 'Ava’s Pixel 9 Pro', platform: 'Android 16', createdAt: new Date().toISOString(), lastSeenAt: new Date().toISOString(), online: true, activeRun: null, teammateId: 'chief', teammateName: 'Ankita' });

const server = await createServer({ configFile: path.join(repo, 'desktop/vite.config.ts'), server: { port: 0, strictPort: false } });
let browser;
try {
  await server.listen();
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: NARROW, deviceScaleFactor: 1 });
  page.setDefaultTimeout(READY_TIMEOUT_MS);
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.addInitScript(({ version, contract, qr, uri, invitation, pending, device, address, fingerprint }) => {
    const listeners = new Set();
    const current = {
      state: 'ready', error: '', address, name: 'Studio desktop', port: 8443, fingerprint,
      addresses: ['192.168.1.20'], preferredAddress: null, running: true,
      invitation: null, pending: [], devices: [], teammates: [{ id: 'chief', name: 'Ankita' }],
    };
    const emit = event => { for (const listener of listeners) listener(event); };
    const broadcast = () => emit({ type: 'phone-pairing-changed', snapshot: structuredClone(current) });
    const preferences = { provider: 'custom', model: 'fixture-model', customApiBase: 'http://127.0.0.1:9/v1', profileSetupDone: true, username: 'Verification', timeZone: 'UTC', appearance: 'graphite' };
    const settings = { username: 'Verification', provider: 'Custom', model: 'fixture-model', tools: [] };
    window.__phone = {
      current,
      invitation: null,
      update(patch) { Object.assign(current, structuredClone(patch)); broadcast(); },
      get pending() { return pending; },
      get device() { return device; },
      get invitationFixture() { return invitation; },
    };
    window.ankita = {
      invoke: async (action, payload) => {
        if (action === 'initialize') return { teammates: [{ id: 'chief', name: 'Ankita', color: '#c8b187', emoji: '✦', persona: 'Verification teammate', projectId: null, model: null, createdAt: '', updatedAt: '', lastMessage: 'Ready', lastMessageAt: null }], models: [], settings, preferences, version, contract, chrome: 'native', jobs: [] };
        if (action === 'listProjects' || action === 'scheduleList' || action === 'approvalList') return [];
        if (action === 'loadThread') return [];
        if (action === 'saveDesktopSettings') return { preferences, settings, models: [] };
        if (action === 'phonePairingStatus') return structuredClone(current);
        if (action === 'phonePairingInvite') {
          const expiresAt = window.__phone.expireNextInvite ? new Date(Date.now() - 1000).toISOString() : invitation.expiresAt;
          window.__phone.invitation = { ...structuredClone(invitation), expiresAt };
          current.invitation = { id: invitation.id, code: invitation.code, expiresAt, address: invitation.address, fingerprint: invitation.fingerprint, attemptsLeft: invitation.attemptsLeft };
          broadcast();
          return { ...window.__phone.invitation, qr, uri };
        }
        if (action === 'phonePairingCancelInvite') { window.__phone.invitation = null; current.invitation = null; broadcast(); return structuredClone(current); }
        if (action === 'phonePairingSelectAddress' || action === 'phonePairingAssign' || action === 'phonePairingRestart') return structuredClone(current);
        if (action === 'phonePairingRevoke') { current.devices = current.devices.filter(item => item.id !== payload?.deviceId); broadcast(); return structuredClone(current); }
        if (action === 'phonePairingRespond') { current.pending = current.pending.filter(item => item.requestId !== payload?.requestId); broadcast(); return structuredClone(current); }
        return null;
      },
      onEvent: callback => { listeners.add(callback); return () => listeners.delete(callback); },
      onMenuCommand: () => () => {},
      onUpdateEvent: () => () => {},
      updateAction: async () => false,
      appAction: async () => null,
      windowAction: async () => true,
      openExternal: async () => {},
    };
  }, { version: appVersion, contract: IPC_CONTRACT, qr: QR, uri: URI, invitation: invitation(Date.now()), pending: pendingRequest(Date.now()), device: pairedDevice(), address: COMPANION_ADDRESS, fingerprint: FINGERPRINT });
  await page.goto(`${server.resolvedUrls.local[0]}`);
  await page.getByRole('heading', { name: 'Ankita' }).first().waitFor();

  // Keyboard-only path: Ctrl+, opens Settings; the dialog takes focus; Tab reaches Phone; Enter selects it.
  await page.keyboard.press('Control+,');
  const dialog = page.locator('.settings-window');
  await dialog.waitFor();
  assert.equal(await page.evaluate(() => document.activeElement?.classList.contains('settings-window')), true, 'Settings dialog owns initial keyboard focus');
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), 'Model');
  for (let index = 1; index < PHONE_NAV_TABS; index++) await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), 'Phone', 'Tab order reaches the Phone section');
  await page.keyboard.press('Enter');
  await page.getByRole('heading', { name: 'Pair a phone', exact: true }).waitFor();
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), 'Phone', 'Activating with Enter keeps focus on the selected section');
  await page.getByRole('button', { name: 'Create pairing code', exact: true }).waitFor();

  let reached = false;
  for (let index = 0; index < KEYBOARD_TAB_LIMIT && !reached; index++) {
    await page.keyboard.press('Tab');
    reached = await page.evaluate(() => document.activeElement?.textContent?.trim() === 'Create pairing code');
  }
  assert.equal(reached, true, 'Tab order reaches Create pairing code');
  await page.keyboard.press('Enter');
  await page.locator('.phone-qr img').waitFor();
  assert.match(await page.locator('.phone-code').innerText(), /^ABCD-EFGH$/);
  assert.match(await page.locator('.phone-expiry').innerText(), /^Expires in \d+:\d{2} · 5 attempts left$/);
  assert.equal(await page.locator('.phone-invite-address').innerText(), COMPANION_ADDRESS);
  assert.ok(!(await page.locator('.phone-invite-address').innerText()).includes('127.0.0.1'), 'The invitation never advertises loopback');
  const qr = await page.locator('.phone-qr img').evaluate(image => ({ source: image.currentSrc || image.src, width: image.naturalWidth, complete: image.complete }));
  assert.match(qr.source, /^data:image\/png;base64,/, 'QR is rendered from in-memory bytes, not a remote image service');
  assert.ok(qr.complete && qr.width > 0, 'QR image decodes in the renderer');
  const narrowGeometry = await page.evaluate(() => {
    const layout = document.querySelector('.phone-invite-layout');
    const content = document.querySelector('.settings-scroll');
    const invite = document.querySelector('.phone-invite');
    const qr = document.querySelector('.phone-qr');
    const bounds = invite.getBoundingClientRect();
    return { columns: getComputedStyle(layout).gridTemplateColumns, scrollWidth: content.scrollWidth, clientWidth: content.clientWidth, inviteRight: bounds.right, windowWidth: innerWidth, qrWidth: qr.getBoundingClientRect().width, qrContentWidth: invite.clientWidth };
  });
  assert.equal(narrowGeometry.columns.trim().split(/\s+/).length, 1, `Narrow invitation stacks vertically (${narrowGeometry.columns})`);
  assert.ok(narrowGeometry.scrollWidth <= narrowGeometry.clientWidth + 1, `Narrow settings have no horizontal overflow (${narrowGeometry.scrollWidth}/${narrowGeometry.clientWidth})`);
  assert.ok(narrowGeometry.inviteRight <= narrowGeometry.windowWidth, 'Invitation card stays inside the window');
  assert.ok(narrowGeometry.qrWidth <= narrowGeometry.qrContentWidth, 'QR fits its card');
  await page.screenshot({ path: path.join(artifactDir, 'narrow-invite.png') });
  console.log('NARROW_INVITE_OK: stacked QR/copy layout, local data-URL QR, one-time code and HTTPS LAN address');

  await page.evaluate(() => window.__phone.update({
    invitation: { id: window.__phone.invitationFixture.id, code: 'ABCD-EFGH', expiresAt: window.__phone.invitationFixture.expiresAt, address: window.__phone.current.address, fingerprint: window.__phone.current.fingerprint, attemptsLeft: 5 },
    pending: [window.__phone.pending],
    devices: [window.__phone.device],
  }));
  await page.getByRole('heading', { name: 'Waiting for approval', exact: true }).waitFor();
  await page.getByText('Ava’s Pixel 9 Pro with a deliberately long household name', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Approve phone', exact: true }).waitFor();
  const longNameOverflow = await page.evaluate(() => { const content = document.querySelector('.settings-scroll'); return content.scrollWidth <= content.clientWidth + 1; });
  assert.equal(longNameOverflow, true, 'Long device names wrap without horizontal overflow');
  await page.getByRole('button', { name: 'Disconnect', exact: true }).click();
  await page.getByText('Disconnect and forget this phone?', { exact: true }).waitFor();
  await page.screenshot({ path: path.join(artifactDir, 'narrow-revoke.png') });
  await page.getByRole('button', { name: 'Keep', exact: true }).click();
  assert.equal(await page.locator('.phone-device-row').count(), 1, 'Keep preserves the paired phone');
  await page.getByRole('button', { name: 'Disconnect', exact: true }).click();
  await page.getByRole('button', { name: 'Disconnect', exact: true }).last().click();
  await page.getByText('No phones paired', { exact: true }).waitFor();
  console.log('DEVICE_STATES_OK: pending approval, long-name wrapping, two-step revoke and honest empty state');

  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: 'Create pairing code', exact: true }).waitFor();
  await page.evaluate(() => { window.__phone.expireNextInvite = true; });
  await page.getByRole('button', { name: 'Create pairing code', exact: true }).click();
  await page.getByText('This code expired. Create a new one.', { exact: true }).waitFor();
  assert.equal(await page.locator('.phone-expiry.expired').count(), 1, 'Expired invitations are visually distinct');
  console.log('EXPIRED_INVITE_OK: elapsed invitations state that the code expired');

  await page.setViewportSize(WIDE);
  await page.evaluate(() => { window.__phone.expireNextInvite = false; });
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: 'Create pairing code', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.phone-invite-layout') && getComputedStyle(document.querySelector('.phone-invite-layout')).gridTemplateColumns.trim().split(/\s+/).length === 2);
  await page.screenshot({ path: path.join(artifactDir, 'wide-invite.png') });
  console.log('WIDE_INVITE_OK: QR and instructions return to two columns on a wide window');

  await page.evaluate(() => window.__phone.update({ state: 'offline', running: false, error: 'No network connection was found.', invitation: null }));
  await page.getByRole('heading', { name: 'This computer is offline', exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: 'Create pairing code' }).count(), 0, 'Offline state never offers a code that cannot be reached');
  await page.screenshot({ path: path.join(artifactDir, 'wide-offline.png') });
  console.log('OFFLINE_STATE_OK: no unusable pairing code while offline');
  assert.deepEqual(pageErrors, []);
  console.log(`PHONE_SETTINGS_UI_OK: keyboard-only navigation, responsive invite and device states; artifacts=${artifactDir}`);
} finally {
  await browser?.close();
  await server.close();
  if (!process.argv.includes('--keep-artifacts')) {
    assert.equal(path.dirname(await fs.realpath(artifactDir)), await fs.realpath(os.tmpdir()), 'Cleanup stays inside the temporary directory');
    await fs.rm(artifactDir, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  }
}
