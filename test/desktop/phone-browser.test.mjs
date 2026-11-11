import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import https from 'node:https';
import { createPublicKey, createHash } from 'node:crypto';
import { chromium } from 'playwright';

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-phone-browser-'));
process.env.CONFIG_DIR = path.join(directory, 'profile'); // Fixture profile before runtime imports: never touch the user's accounts.
test.after(() => fs.rmSync(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));
const { DesktopEngine } = await import('../../desktop/electron/engine.mjs');
const { Agent } = await import('../../src/core/agent.mjs');
const { PhonePairing } = await import('../../desktop/electron/phone-pairing.mjs');
const { PHONE_PAIRING_ROOT, PHONE_CLIENT_ROOT, PHONE_SESSION_KEY } = await import('../../desktop/shared/phone-pairing.mjs');
const LOOPBACK = '127.0.0.1';
const TIMEOUT_MS = 15000; // Local browser and real HTTPS fixture deadline.
const SAFE_STORAGE = { isAsyncEncryptionAvailable: async () => true, encryptStringAsync: async value => Buffer.from(`fixture:${value}`), decryptStringAsync: async value => ({ result: value.toString().replace(/^fixture:/, '') }) };
const SELECTED = 'Take the late train.';
const RESUMED_SELECTION = 'Bring the updated ticket.';
const ORIGINAL_GOAL = 'Finish the phone handoff.';
const toolCall = (id, file, content) => ({ id, function: { name: 'write_file', arguments: JSON.stringify({ path: file, content }) } });
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitFor(check) {
  const end = Date.now() + TIMEOUT_MS;
  while (Date.now() < end) { if (await check()) return; await pause(25); }
  throw new Error('Timed out waiting for the actual phone service state');
}
async function trustedPage(service) {
  return new Promise((resolve, reject) => {
    https.get(`https://${LOOPBACK}:${service.port}${PHONE_CLIENT_ROOT}`, { ca: service.certificate().pem, rejectUnauthorized: true }, response => {
      const chunks = []; response.on('data', chunk => chunks.push(chunk)); response.on('end', () => resolve({ status: response.statusCode, body: Buffer.concat(chunks).toString() }));
    }).on('error', reject);
  });
}
async function trustedIntercept(service, request) {
  return new Promise((resolve, reject) => {
    https.get(request.url(), { headers: request.headers(), ca: service.certificate().pem, rejectUnauthorized: true }, response => {
      const chunks = []; response.on('data', chunk => chunks.push(chunk)); response.on('end', () => resolve({ status: response.statusCode, headers: response.headers, body: Buffer.concat(chunks) }));
    }).on('error', reject);
  });
}

test('phone browser pairs, reviews context, approves real work, resumes the same task and loses revoked access', async t => {
  const workspace = path.join(directory, 'workspace'); fs.mkdirSync(workspace);
  const profile = path.join(directory, 'desktop'); fs.mkdirSync(profile);
  const engine = new DesktopEngine({ teammateFile: path.join(profile, 'teammates.json'), settingsFile: path.join(profile, 'settings.json'),
    sessionsDir: path.join(profile, 'sessions'), projectsFile: path.join(profile, 'projects.json'), channelsFile: path.join(profile, 'channels.json'),
    credentialFile: path.join(profile, 'credentials.json'), composioFile: path.join(profile, 'composio.json'), composioGrantsFile: path.join(profile, 'grants.json'),
    AgentClass: Agent, config: { provider: 'fixture', model: 'fixture-model', tools: true, autoApprove: false, contextWindow: 131072, maxTokens: 1000, memoryRecallChars: 0, memoryConsolidation: false },
    bootstrap: async () => ({ client: {}, models: [{ id: 'fixture-model' }], model: 'fixture-model', provider: { name: 'fixture' } }),
    mcp: { reconcile: async () => {}, ensureComposio: async () => {}, summaries: () => [], specs: () => [], alwaysOnIds: () => [], has: () => false, closeAll: async () => {} } });
  let browser, service;
  t.after(async () => { await browser?.close(); await service?.close(); await engine.close(); });
  await engine.init(); const owner = engine.listTeammates()[0].id, other = engine.createTeammate({ name: 'Private owner' }).id;
  const agent = engine.agentFor(owner); agent.setProject('', null, workspace);
  let seenSelection = false, seenResume = false, round = 0, activeGoal = '';
  agent.streamTurn = async () => {
    const current = JSON.stringify(agent.messages.findLast(message => message.role === 'user')?.content);
    if (activeGoal !== current) { activeGoal = current; round = 0; }
    round++;
    if (current.includes('Save my reviewed selection')) {
      assert.match(current, /Take the late train\./, 'the actual Agent receives the explicitly reviewed excerpt'); seenSelection = true;
      if (round === 1) return { content: '', toolCalls: [toolCall('phone-save', 'phone-reviewed.txt', SELECTED)] };
      return { content: 'Saved your selected note.', toolCalls: [] };
    }
    if (current.includes(ORIGINAL_GOAL)) {
      assert.match(current, /Bring the updated ticket\./, 'resumed worker receives fresh, reviewed context');
      assert.match(current, /Original desktop source/, 'original task context survives the handoff'); seenResume = true;
      if (round === 1) return { content: '', toolCalls: [toolCall('phone-resume', 'phone-resumed.txt', RESUMED_SELECTION)] };
      return { content: 'Finished the original handoff.', toolCalls: [] };
    }
    if (current.includes('Cancel this pending write')) {
      if (round === 1) return { content: '', toolCalls: [toolCall('phone-cancel', 'must-not-exist.txt', 'denied')] };
      return { content: 'Cancelled.', toolCalls: [] };
    }
    return { content: 'A desktop conversation is ready.', toolCalls: [] };
  };
  engine.agentFor(other).streamTurn = async () => ({ content: 'PRIVATE_OTHER_OWNER', toolCalls: [] });
  await engine.send(owner, 'A desktop conversation is ready.'); await engine.waitForTurn(owner);
  await engine.send(other, 'PRIVATE_OTHER_OWNER'); await engine.waitForTurn(other);
  const task = engine.assistant().tasks.create({ ownerId: owner, goal: ORIGINAL_GOAL, workspacePath: agent.workspacePath,
    context: { references: [{ name: 'Original desktop source', excerpt: 'Review the existing route first.', digest: 'fixture-source' }], notice: 'Fixture explicitly attached reference', omitted: 0 } });
  engine.assistant().tasks.start(task.id, { ownerId: owner }); engine.assistant().tasks.finish(task.id, { status: 'interrupted' });
  service = new PhonePairing({ engine, safeStorage: SAFE_STORAGE, configFile: path.join(profile, 'phone-pairing.json'), devicesFile: path.join(profile, 'phone-devices.json'), addresses: ['192.0.2.10'], hostname: 'phone-fixture' });
  await service.start(); assert.equal(service.state, 'ready');
  const strict = await trustedPage(service); assert.equal(strict.status, 200); assert.match(strict.body, /Pair this phone/);
  // Test-only pin for this disposable leaf. Production/browser code never disables TLS.
  // Full CA chain and hostname verification run above and in phone-pairing.test.mjs.
  const spki = createHash('sha256').update(createPublicKey(service.leaf.certPem).export({ type: 'spki', format: 'der' })).digest('base64');
  browser = await chromium.launch({ headless: true, args: [`--ignore-certificate-errors-spki-list=${spki}`] });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, ignoreHTTPSErrors: false });
  const page = await context.newPage(); page.setDefaultTimeout(TIMEOUT_MS); const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const origin = `https://${LOOPBACK}:${service.port}`;
  const invitation = await service.createInvitation(), url = new URL(invitation.browserUrl); url.hostname = LOOPBACK;
  await page.goto(url.toString());
  await page.getByRole('heading', { name: 'Pair this phone', exact: true }).waitFor();
  if (process.env.ANKITA_PHONE_BROWSER_ARTIFACT_DIR) { fs.mkdirSync(process.env.ANKITA_PHONE_BROWSER_ARTIFACT_DIR, { recursive: true }); await page.screenshot({ path: path.join(process.env.ANKITA_PHONE_BROWSER_ARTIFACT_DIR, 'phone-pair.png'), fullPage: true }); }
  assert.equal(await page.evaluate(() => location.hash), '', 'invitation fragment is removed on arrival');
  await page.getByLabel('Phone name', { exact: true }).fill('Fixture phone browser');
  await page.getByRole('button', { name: 'Request pairing', exact: true }).click();
  await waitFor(() => service.snapshot().pending.length === 1);
  assert.equal(await page.locator('#workspace').isVisible(), false);
  assert.equal(await page.evaluate(key => sessionStorage.getItem(key), PHONE_SESSION_KEY), null, 'no token before desktop owner approval');
  await service.respondPairing(service.snapshot().pending[0].requestId, true, owner);
  await page.getByRole('heading', { name: 'Conversation', exact: true }).waitFor();
  await page.locator('#history').getByText('A desktop conversation is ready.').first().waitFor();
  assert.equal((await page.locator('body').innerText()).includes('PRIVATE_OTHER_OWNER'), false);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'phone viewport has no horizontal overflow');
  assert.equal(await page.evaluate(() => Object.keys(localStorage).length), 0, 'credentials never go into cross-tab local storage');
  console.log('PHONE_BROWSER_PAIR_HISTORY_OK: desktop approval, assigned history, 390px layout, no localStorage key');

  await page.getByLabel('Request', { exact: true }).fill('Save my reviewed selection');
  await page.locator('#context-editor summary').click();
  await page.getByLabel('Source name', { exact: true }).fill('Selected route'); await page.getByLabel('Selected text', { exact: true }).fill(SELECTED);
  await page.getByRole('button', { name: 'Send request', exact: true }).click();
  await page.getByRole('status').filter({ hasText: 'Review the selected context and check the box' }).waitFor();
  assert.equal(fs.existsSync(path.join(workspace, 'phone-reviewed.txt')), false);
  await page.getByRole('button', { name: 'Review selected context', exact: true }).click();
  await page.locator('#preview-text').getByText(SELECTED, { exact: true }).waitFor();
  await page.getByLabel('I reviewed this context', { exact: true }).check();
  if (process.env.ANKITA_PHONE_BROWSER_ARTIFACT_DIR) await page.screenshot({ path: path.join(process.env.ANKITA_PHONE_BROWSER_ARTIFACT_DIR, 'phone-context.png'), fullPage: true });
  await page.getByRole('button', { name: 'Send request', exact: true }).click();
  await page.getByRole('heading', { name: 'Permission needed', exact: true }).waitFor();
  assert.equal(fs.existsSync(path.join(workspace, 'phone-reviewed.txt')), false, 'actual tool waits for approval');
  await page.getByRole('button', { name: 'Allow once', exact: true }).click();
  await waitFor(() => fs.existsSync(path.join(workspace, 'phone-reviewed.txt')));
  await page.locator('#run-status').getByText('completed', { exact: true }).waitFor();
  assert.equal(fs.readFileSync(path.join(workspace, 'phone-reviewed.txt'), 'utf8'), SELECTED); assert.ok(seenSelection);
  const selectedTask = engine.assistant().tasks.list({ ownerId: owner }).find(item => item.goal === 'Save my reviewed selection');
  assert.equal(selectedTask.surface, 'phone'); assert.equal(selectedTask.context.references[0].excerpt, SELECTED); assert.equal(selectedTask.steps[0].phase, 'settled');
  console.log('PHONE_BROWSER_CONTEXT_APPROVAL_OK: reviewed one-request text reaches real Agent, write waits for approval, saved receipt and context');

  await page.getByLabel('Request', { exact: true }).fill('A new request without context'); await page.getByRole('button', { name: 'Send request', exact: true }).click();
  await waitFor(() => engine.assistant().tasks.list({ ownerId: owner }).some(item => item.goal === 'A new request without context' && item.status === 'completed'));
  assert.equal(engine.assistant().tasks.list({ ownerId: owner }).find(item => item.goal === 'A new request without context').context, null);
  await page.locator('#run-status').getByText('completed', { exact: true }).waitFor();
  await page.reload(); await page.getByRole('heading', { name: 'Conversation', exact: true }).waitFor();
  await page.locator('#tasks article').filter({ hasText: ORIGINAL_GOAL }).getByRole('button', { name: 'Review and continue' }).click();
  await page.locator('#context-editor summary').click();
  await page.getByLabel('Source name', { exact: true }).fill('Fresh ticket'); await page.getByLabel('Selected text', { exact: true }).fill(RESUMED_SELECTION);
  await page.getByRole('button', { name: 'Review selected context', exact: true }).click(); await page.getByLabel('I reviewed this context', { exact: true }).check();
  await page.getByRole('button', { name: 'Continue saved request', exact: true }).click();
  await page.getByRole('heading', { name: 'Permission needed', exact: true }).waitFor(); assert.equal(fs.existsSync(path.join(workspace, 'phone-resumed.txt')), false);
  await page.getByRole('button', { name: 'Allow once', exact: true }).click();
  await waitFor(() => engine.assistant().tasks.get(task.id).status === 'completed'); assert.ok(seenResume);
  const resumed = engine.assistant().tasks.get(task.id); assert.equal(resumed.goal, ORIGINAL_GOAL); assert.equal(resumed.attempt, 2);
  assert.deepEqual(new Set(resumed.context.references.map(item => item.name)), new Set(['Fresh ticket.txt', 'Original desktop source']));
  assert.equal(fs.readFileSync(path.join(workspace, 'phone-resumed.txt'), 'utf8'), RESUMED_SELECTION);
  console.log('PHONE_BROWSER_RESUME_OK: tab reload, original task/goal/context, fresh reviewed context, ordinary approval and real file receipt');

  await page.locator('#run-status').getByText('completed', { exact: true }).waitFor();
  await page.getByLabel('Request', { exact: true }).fill('Cancel this pending write'); await page.getByRole('button', { name: 'Send request', exact: true }).click();
  await page.getByRole('heading', { name: 'Permission needed', exact: true }).waitFor(); await page.getByRole('button', { name: 'Stop this request', exact: true }).click();
  await page.locator('#run-status').getByText('cancelled', { exact: true }).waitFor(); assert.equal(fs.existsSync(path.join(workspace, 'must-not-exist.txt')), false);
  const device = service.snapshot().devices[0]; await service.revokeDevice(device.id);
  await page.getByRole('button', { name: 'Refresh work', exact: true }).click(); await page.getByRole('heading', { name: 'Pair this phone', exact: true }).waitFor();
  assert.equal(await page.evaluate(key => sessionStorage.getItem(key), PHONE_SESSION_KEY), null);
  let releaseClaim, claimFetched;
  const claimReady = new Promise(resolve => { claimFetched = resolve; });
  const claimRelease = new Promise(resolve => { releaseClaim = resolve; });
  await page.route(`**${PHONE_PAIRING_ROOT}/pair/*`, async route => {
    const response = await trustedIntercept(service, route.request()); const body = JSON.parse(response.body.toString());
    if (body.token) { claimFetched(); await claimRelease; }
    await route.fulfill(response);
  });
  const inviteAgain = await service.createInvitation(); await page.getByLabel('Phone name', { exact: true }).fill('Second tab connection'); await page.getByLabel('Pairing code', { exact: true }).fill(inviteAgain.code);
  await page.getByRole('button', { name: 'Request pairing', exact: true }).click(); await waitFor(() => service.snapshot().pending.length === 1);
  await service.respondPairing(service.snapshot().pending[0].requestId, true, owner); await claimReady;
  await page.getByRole('button', { name: 'Forget this tab’s connection', exact: true }).click(); releaseClaim();
  await page.waitForResponse(response => response.url().includes(`${PHONE_PAIRING_ROOT}/pair/`) && response.status() === 200);
  await pause(100);
  assert.equal(await page.locator('#workspace').isVisible(), false, 'a late token claim cannot reconnect a forgotten tab');
  assert.equal(await page.evaluate(key => sessionStorage.getItem(key), PHONE_SESSION_KEY), null);
  await page.unroute(`**${PHONE_PAIRING_ROOT}/pair/*`); await service.revokeDevice(service.snapshot().devices[0].id);
  const finalInvite = await service.createInvitation(); await page.getByLabel('Pairing code', { exact: true }).fill(finalInvite.code); await page.getByRole('button', { name: 'Request pairing', exact: true }).click();
  await waitFor(() => service.snapshot().pending.length === 1); await service.respondPairing(service.snapshot().pending[0].requestId, true, owner); await page.getByRole('heading', { name: 'Conversation', exact: true }).waitFor();
  const separate = await browser.newContext({ ignoreHTTPSErrors: false }); const separatePage = await separate.newPage(); await separatePage.goto(`${origin}${PHONE_CLIENT_ROOT}`);
  await separatePage.getByRole('heading', { name: 'Pair this phone', exact: true }).waitFor(); assert.equal(await separatePage.locator('#workspace').isVisible(), false); await separate.close();
  await page.getByRole('button', { name: 'Disconnect and forget', exact: true }).click(); await page.getByRole('heading', { name: 'Pair this phone', exact: true }).waitFor();
  assert.equal(service.snapshot().devices.length, 0); assert.deepEqual(errors, []);
  console.log('PHONE_BROWSER_REVOKE_OK: actual cancellation, desktop revoke clears tab key, separate browser context has no access, phone disconnect revokes');
});
