import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import { _electron as electron } from 'playwright';
import { build, Platform } from 'electron-builder';
import { DesktopSettingsStore } from '../desktop/electron/settings.mjs';
import { complexLoginFixture, LOGIN_USER, LOGIN_PASSWORD } from './fixtures/complex-login.mjs';

const require = createRequire(import.meta.url), ROOT = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const HOST = '127.0.0.1', MODEL = 'assistant-features-fixture';
const TIMEOUT_MS = 60_000, POLL_MS = 100;
const FAKE_KEY = 'ghp_aB3cD4eF5gH6iJ7kL8mN9oP0qR1sT2uV3wX4';
const FAKE_GENERIC_KEY = FAKE_KEY.slice('ghp_'.length), FAKE_PASSWORD = 'short-fixture-password'; // Synthetic values test unlabeled echoes and named generic save intent.
const REPORT = 'Complex scheduled report';
const JOB_PROMPT = 'Sign in through the saved account, publish exactly one test report, and verify its confirmation.\nRead fresh controls on every step. Do not repeat a completed submission.'; // Fixture instructions shown verbatim in job details/editor.
const SCHEDULED_USAGE = { prompt_tokens: 63000, completion_tokens: 472, total_tokens: 63472 }; // Reproduces the user's cumulative-input cutoff on every scheduled model round.
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-assistant-features-'));
const config = path.join(directory, 'config'); fs.mkdirSync(config);
const fixture = await complexLoginFixture();
const requests = [], errors = [];
let releaseScheduled, scheduledStarted, gateScheduled = true, malformedSelections = 0;
const scheduledGate = new Promise(resolve => { releaseScheduled = resolve; });
const scheduledBegan = new Promise(resolve => { scheduledStarted = resolve; });
const ref = (text, label) => text.split('\n').find(line => line.includes(label) && line.includes('[ref='))?.match(/\[ref=([^\]]+)\]/)?.[1];
const server = http.createServer(async (request, response) => {
  if (request.url === '/models') { response.setHeader('content-type', 'application/json'); return response.end(JSON.stringify({ data: [{ id: MODEL, context_length: 131072 }] })); }
  if (request.url !== '/chat/completions') { response.statusCode = 404; return response.end(); }
  try {
    const chunks = []; for await (const chunk of request) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString()); requests.push(body);
    const textOf = message => typeof message.content === 'string' ? message.content : message.content?.find(part => part.type === 'text')?.text || '';
    const start = body.messages.findLastIndex(message => message.role === 'user' && /FEATURE:|\[Scheduled run:|Scheduled run result \(data\):|Save this as my/.test(textOf(message)));
    const prompt = textOf(body.messages[start]);
    const results = body.messages.slice(start + 1).filter(message => message.role === 'tool' && message.tool_call_id?.startsWith('feature-'));
    const phase = results.length;
    let snapshot = String(results.at(-1)?.content || '');
    if (/^Error/.test(snapshot)) console.error(`FEATURE_BROWSER_ERROR: ${snapshot.split('\n')[0]}`);
    try { snapshot = JSON.parse(snapshot.split('\n')[0]).snapshot || snapshot; } catch {}
    let name, args, content;
    if (prompt.startsWith('Scheduled run result (data):')) {
      assert.equal(body.tools, undefined, 'The owning teammate writes the result without tools');
      const observation = JSON.parse(prompt.slice(prompt.indexOf('\n') + 1));
      content = observation.status === 'ok'
        ? `I checked ${observation.job}: ${observation.result} The browser proof is attached below.`
        : `I could not complete ${observation.job}: ${observation.result}`;
    } else if (prompt.startsWith('[Scheduled run:')) {
      if (gateScheduled) { gateScheduled = false; scheduledStarted(); await scheduledGate; }
      const mfa = prompt.includes('MFA test');
      name = 'browser';
      if (!phase) args = { action: 'open', url: `${fixture.base}/${mfa ? 'mfa' : 'begin'}` };
      else if (ref(snapshot, 'Account email')) args = { action: 'login', website: fixture.base, credential_fields: [{ ref: ref(snapshot, 'Account email'), credential: 'username' }], submit_ref: ref(snapshot, 'Continue') };
      else if (ref(snapshot, 'Account password')) args = { action: 'login', website: fixture.base, credential_fields: [{ ref: ref(snapshot, 'Account password'), credential: 'password' }], submit_ref: ref(snapshot, 'Sign in') };
      else if (snapshot.includes('Verification code')) { name = 'schedule'; args = { action: 'needs_input', reason: 'A fresh authenticator code is required.' }; }
      else if (ref(snapshot, 'Report text')) args = snapshot.includes(`value=${REPORT}`) ? { action: 'act', op: 'click', ref: ref(snapshot, 'Publish report') } : { action: 'fill_form', fields: [{ ref: ref(snapshot, 'Report text'), text: REPORT }] };
      else if (!snapshot.includes('Report published once')) args = { action: 'read' };
      else { name = null; content = `Confirmed ${REPORT}.`; }
      if (!mfa && phase === 1 && args?.action === 'login') {
        args = { action: 'login', website: fixture.base, credential_fields: [{ ref: ref(snapshot, 'Account email'), credential: 'username' }, { ref: ref(snapshot, 'Continue'), credential: 'submit' }] };
        malformedSelections++; // Replay the observed model schema mistake once per run, before any private fill.
      }
    } else if (prompt.includes('FEATURE: create')) {
      if (!phase) { name = 'schedule'; args = { action: 'add', name: 'Daily workspace report', description: 'Sign in and publish the workspace report every morning.', cron: 'daily 09:00', prompt: `${JOB_PROMPT}\nWebsite: ${fixture.base}/begin` }; }
      else content = 'Your daily report is scheduled.';
    } else if (prompt.includes('FEATURE: update')) {
      const job = body.messages.filter(message => message.role === 'tool').map(message => { try { return JSON.parse(String(message.content).split('\n')[0]).job; } catch { return null; } }).find(Boolean);
      if (!phase) { name = 'schedule'; args = { action: 'update', id: job.id, patch: { cron: 'weekdays 10:30' } }; }
      else content = 'Updated the same task.';
    } else content = `Received securely. ${prompt}`;
    const delta = name ? { tool_calls: [{ index: 0, id: `feature-${requests.length}`, type: 'function', function: { name, arguments: JSON.stringify(args) } }] } : { content };
    response.writeHead(200, { 'content-type': 'text/event-stream' });
    response.end(`data: ${JSON.stringify({ model: MODEL, choices: [{ index: 0, delta, finish_reason: name ? 'tool_calls' : 'stop' }], usage: prompt.startsWith('[Scheduled run:') ? SCHEDULED_USAGE : { prompt_tokens: 30, completion_tokens: 10, total_tokens: 40 } })}\n\ndata: [DONE]\n\n`);
  } catch (error) { errors.push(error.message); console.error(`FEATURE_FIXTURE_ERROR: ${error.message}`); response.statusCode = 500; response.end('Fixture failed'); }
});
await new Promise(resolve => server.listen(0, HOST, resolve));
new DesktopSettingsStore(path.join(config, 'desktop-settings.json')).update({ provider: 'custom', model: MODEL, customApiBase: `http://${HOST}:${server.address().port}`, customApiKey: '', composioApiKey: '', profileSetupDone: true, username: 'Verification', timeZone: 'UTC' });
fs.writeFileSync(path.join(config, 'config.env'), 'ALLOW_PRIVATE_HOSTS=1\nMEMORY_CONSOLIDATION=0\nAUTO_APPROVE=1\n');
fs.writeFileSync(path.join(config, 'daemon.log'), `Legacy job log ${FAKE_KEY}`);
const old = path.join(config, 'sessions'); fs.mkdirSync(old); fs.writeFileSync(path.join(old, 'old.json'), JSON.stringify({ messages: [{ role: 'user', content: FAKE_KEY }] }));
let application, appOutput;
try {
  const packaged = process.argv.includes('--packaged');
  if (packaged) await build({ targets: Platform.current().createTarget('dir'), publish: 'never', projectDir: ROOT, config: { extends: path.join(ROOT, 'desktop/packaging/electron-builder.yml'), directories: { output: path.join(directory, 'package') }, electronDist: path.dirname(require('electron')), npmRebuild: false, win: { signAndEditExecutable: false }, afterPack: context => { appOutput = context.appOutDir; } } });
  const executablePath = packaged ? path.join(appOutput, fs.readdirSync(appOutput).find(name => name.endsWith('.exe'))) : require('electron');
  const env = { ...process.env, CONFIG_DIR: config, TOOL_PROVIDER: '', TOOL_MODEL: '', TOOL_API_BASE: '', TOOL_API_KEY: '', ALLOW_PRIVATE_HOSTS: '1' }; delete env.ELECTRON_RUN_AS_NODE; delete env.ANKITA_DESKTOP_DEV_URL;
  application = await electron.launch({ executablePath, args: [...(packaged ? [] : [ROOT]), `--user-data-dir=${path.join(directory, 'user-data')}`], cwd: config, env, timeout: TIMEOUT_MS });
  const page = await application.firstWindow(); page.setDefaultTimeout(TIMEOUT_MS);
  const pageErrors = []; page.on('pageerror', error => pageErrors.push(error.message));
  await page.waitForFunction(() => Boolean(window.ankita)); await page.evaluate(() => window.ankita.invoke('initialize'));
  await page.evaluate(() => window.ankita.invoke('browserPluginSetEnabled', { mode: 'isolated', enabled: true }));
  const send = async text => { await page.evaluate(async text => {
    let finish, fail;
    const done = new Promise((resolve, reject) => { finish = resolve; fail = reject; });
    const off = window.ankita.onEvent(event => { if (event.threadId === 'chief' && event.type === 'turn-end') finish(); if (event.threadId === 'chief' && event.type === 'error') fail(new Error(event.message)); });
    try { await window.ankita.invoke('send', { id: 'chief', text }); await done; } finally { off(); }
  }, text); };
  const settle = async id => { const limit = Date.now() + TIMEOUT_MS; do { const jobs = await page.evaluate(() => window.ankita.invoke('scheduleList')); const job = jobs.find(job => job.id === id); if (job?.lastReceipt && !job.running) return job; await delay(POLL_MS); } while (Date.now() < limit); throw new Error('Scheduled task did not settle'); };
  await page.getByRole('textbox', { name: 'Message Chief', exact: true }).waitFor();
  await send('FEATURE: create the daily workspace report');
  await page.getByRole('region', { name: 'Scheduled task Daily workspace report' }).waitFor();
  let jobs = await page.evaluate(() => window.ankita.invoke('scheduleList')); assert.equal(jobs.length, 1); assert.equal(jobs[0].enabled, true); assert.equal(jobs[0].browserPolicy, 'autonomous'); assert.equal(fixture.audit.posts.length, 0);
  assert.equal(await page.locator('.routine-sheet').count(), 0, 'Model creation opens no manual form');
  await send('FEATURE: update the same task to weekdays 10:30');
  await page.waitForFunction(() => document.querySelectorAll('.scheduled-task-card').length === 2);
  jobs = await page.evaluate(() => window.ankita.invoke('scheduleList')); assert.equal(jobs.length, 1); assert.equal(jobs[0].cron, '30 10 * * 1-5');
  assert.match(await page.locator('.jobs-pill-toggle').innerText(), /Next .*UTC/, 'Next-run label uses job timezone rather than a giant minute count');
  await page.getByRole('button', { name: 'View scheduled task' }).last().click();
  const panel = page.getByRole('complementary', { name: 'Upcoming scheduled jobs' }); await panel.waitFor();
  assert.ok((await panel.locator('.upcoming-job').boundingBox()).height < 65);
  assert.equal(await panel.getByRole('region', { name: 'Task instructions' }).locator('p').innerText(), jobs[0].prompt);
  assert.ok((await panel.innerText()).includes('Until complete'));
  await panel.getByRole('button', { name: 'Edit task settings' }).click();
  const settings = page.getByRole('complementary', { name: 'Scheduled jobs' }); await settings.waitFor();
  assert.equal(await settings.getByLabel('Task instructions').inputValue(), jobs[0].prompt);
  await settings.getByText('Execution and background settings', { exact: true }).click();
  assert.equal(await settings.getByRole('combobox', { name: /^Execution/ }).inputValue(), 'complete');
  await settings.getByRole('button', { name: 'Close job settings' }).click(); await panel.waitFor();
  await page.screenshot({ path: path.join(directory, 'scheduled-tasks.png') });
  await panel.getByRole('button', { name: 'Close scheduled tasks' }).click();
  console.log('MODEL_TASK_CARDS_OK: one active job; model update; two compact cards; thin upcoming list; no manual creation form');
  await page.evaluate(({ website, username, password }) => window.ankita.invoke('secureStoreSave', { website, username, password }), { website: fixture.base, username: LOGIN_USER, password: LOGIN_PASSWORD });
  await page.keyboard.press('Control+k'); await page.getByRole('dialog', { name: 'Command palette' }).waitFor();
  const search = page.getByRole('combobox', { name: 'Search commands, skills and jobs' }); await search.fill('Daily workspace');
  await page.waitForFunction(() => { const selected = document.querySelector('[role=option][aria-selected=true]'); return selected?.textContent.includes('Daily workspace report') && !selected.disabled; });
  await page.screenshot({ path: path.join(directory, 'command-palette.png') }); await search.press('Enter');
  await scheduledBegan;
  await page.getByRole('button', { name: 'Plugins', exact: true }).click();
  assert.equal((await page.evaluate(() => window.ankita.invoke('scheduleList')))[0].running, true);
  releaseScheduled();
  let completed = await settle(jobs[0].id);
  if (completed.lastStatus !== 'ok') for (const file of fs.readdirSync(path.join(config, 'sessions', 'jobs'))) { const log = JSON.parse(fs.readFileSync(path.join(config, 'sessions', 'jobs', file), 'utf8')); console.error(JSON.stringify(log.audit)); }
  assert.equal(completed.lastStatus, 'ok', completed.lastSummary); assert.equal(fixture.audit.posts.length, 1); assert.ok(completed.lastReceipt.proof.screenshot);
  assert.ok(completed.spend.tokens > 60000); assert.equal(completed.enabled, true);
  assert.equal(await page.getByRole('button', { name: 'Plugins', exact: true }).getAttribute('aria-current'), 'page');
  await page.locator('.teammate-row').filter({ hasText: 'Chief' }).click();
  await page.locator('.assistant-message').getByText(`I checked ${jobs[0].name}: Confirmed ${REPORT}. The browser proof is attached below.`, { exact: true }).waitFor();
  const deliveredMessage = page.locator('.assistant-message').filter({ hasText: `I checked ${jobs[0].name}` }).last();
  assert.equal(await deliveredMessage.locator('.scheduled-result.compact').count(), 1);
  assert.equal(await deliveredMessage.locator('.job-proof').getAttribute('open'), null, 'Worker details stay collapsed under the teammate reply');
  await page.reload(); await page.waitForFunction(() => Boolean(window.ankita));
  await page.locator('.assistant-message').getByText(`I checked ${jobs[0].name}: Confirmed ${REPORT}. The browser proof is attached below.`, { exact: true }).waitFor();
  assert.equal(await page.locator('.assistant-message .scheduled-result.compact').count(), 1, 'The teammate reply and proof restore together');
  console.log('MAIN_TEAMMATE_DELIVERY_OK: tool-free model reply, compact evidence, reload persistence');
  console.log('SCHEDULED_COMPLETION_UI_OK: cumulative usage exceeded old ceiling; navigation to Plugins preserved the running job; exact task prompt visible and editable');
  assert.equal(await page.locator('.job-approval-card').count(), 0); assert.equal(await page.locator('.approval-dialog').count(), 0);
  fixture.expire();
  await page.evaluate(id => window.ankita.invoke('scheduleRunNow', { id }), jobs[0].id);
  const previous = completed.lastReceipt.runId;
  const limit = Date.now() + TIMEOUT_MS;
  do { completed = await settle(jobs[0].id); if (completed.lastReceipt.runId !== previous) break; await delay(POLL_MS); } while (Date.now() < limit);
  if (completed.lastStatus !== 'ok') for (const file of fs.readdirSync(path.join(config, 'sessions', 'jobs'))) { const log = JSON.parse(fs.readFileSync(path.join(config, 'sessions', 'jobs', file), 'utf8')); console.error(JSON.stringify(log.audit)); }
  assert.equal(completed.lastStatus, 'ok'); assert.equal(fixture.audit.posts.length, 2); assert.equal(fixture.audit.passwords, 2); assert.equal(fixture.audit.wrongCredentials, 0); assert.equal(fixture.audit.leakedQueries, 0);
  assert.equal(malformedSelections, 2);
  console.log('CREDENTIAL_SELECTION_RECOVERY_OK: 2 malformed login calls returned fresh refs; model corrected them; exactly 2 posts');
  console.log('COMPLEX_SCHEDULED_LOGIN_OK: private username-first + iframe password + CSRF + replaced control + expired session; exactly 2 posts; no browser site dialogs');
  const mfa = await page.evaluate(base => window.ankita.invoke('scheduleAdd', { name: 'MFA test', cron: '@daily', prompt: 'MFA test', browserPolicy: 'autonomous', threadId: 'chief' }), fixture.base);
  await page.evaluate(id => window.ankita.invoke('scheduleRunNow', { id }), mfa.id);
  assert.equal((await settle(mfa.id)).lastStatus, 'skipped-needs-foreground'); assert.equal(fixture.audit.mfa, 1); assert.equal(fixture.audit.posts.length, 2);
  console.log('MFA_NEEDS_FOREGROUND_OK: typed stop receipt; no guessed code, password dialog or extra post');
  await send(`Save this as my Github API key: ${FAKE_KEY}`);
  await page.waitForFunction(() => document.querySelector('.secret-toast')?.textContent.includes('Saved securely'));
  const named = await page.evaluate(() => window.ankita.invoke('secretList')); assert.equal(named[0].name, 'github-api-key');
  await send(`DB_PASSWORD=${FAKE_PASSWORD}`);
  await send(`Save this as my OpenAI key: ${FAKE_GENERIC_KEY}`);
  const allNamed = await page.evaluate(() => window.ankita.invoke('secretList'));
  assert.deepEqual(allNamed.map(item => item.name).sort(), ['github-api-key', 'openai-key']);
  assert.ok(requests.some(body => JSON.stringify(body.messages).includes(FAKE_KEY)), 'Raw input remains usable in the live model turn');
  const exported = path.join(directory, 'chat.md');
  await application.evaluate(({ dialog }, file) => { dialog.showSaveDialog = async () => ({ canceled: false, filePath: file }); }, exported);
  await page.evaluate(() => window.ankita.invoke('exportChat', { id: 'chief' }));
  assert.ok(!fs.readFileSync(exported, 'utf8').includes(FAKE_KEY));
  assert.match(fs.readFileSync(exported, 'utf8'), /STORED:keychain:github-api-key/);
  function inspect(folder) { for (const entry of fs.readdirSync(folder, { withFileTypes: true })) { const file = path.join(folder, entry.name); if (entry.isDirectory()) inspect(file); else if (/\.(?:json|jsonl|md|log)$/.test(entry.name)) { const text = fs.readFileSync(file, 'utf8'); for (const secret of [FAKE_KEY, FAKE_GENERIC_KEY, FAKE_PASSWORD, LOGIN_PASSWORD]) assert.ok(!text.includes(secret), file); } } }
  inspect(config);
  console.log('SECRET_BOUNDARIES_OK: real OS encryption; named reference; first-launch migration; session/journal/job log/export contain no fake key or password');
  await page.keyboard.press('Control+k'); await search.waitFor(); await search.fill('Settings');
  await page.waitForFunction(() => { const selected = document.querySelector('[role=option][aria-selected=true]'); return selected?.textContent.startsWith('Settings') && !selected.disabled; });
  await search.press('ArrowDown'); await search.press('ArrowUp'); await search.press('Enter');
  await page.locator('.settings-window').waitFor();
  assert.deepEqual(errors, []); assert.deepEqual(pageErrors, []);
  console.log(`DESKTOP_ASSISTANT_FEATURES_OK: packaged=${packaged}; modelCalls=${requests.length}; artifacts=${directory}`);
} finally {
  releaseScheduled();
  await application?.close(); await fixture.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  if (!process.argv.includes('--keep-artifacts')) {
    assert.equal(path.dirname(fs.realpathSync(directory)), fs.realpathSync(os.tmpdir()), 'Cleanup stays inside the temporary directory');
    await fs.promises.rm(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  }
}
