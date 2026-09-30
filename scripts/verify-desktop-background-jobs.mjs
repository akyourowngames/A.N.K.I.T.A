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

const require = createRequire(import.meta.url), ROOT = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const HOST = '127.0.0.1', MODEL = 'scheduled-browser-verification'; // Disposable test server/model only.
const APP_TIMEOUT_MS = 45_000, ACTION_TIMEOUT_MS = 15_000, CLEANUP_RETRIES = 10, CLEANUP_DELAY_MS = 100;
const STATE_POLL_MS = 100; // Node polling awaits IPC promises; browser predicate polling treats promises as truthy.
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-desktop-jobs-'));
const config = path.join(directory, 'config'), userData = path.join(directory, 'user-data'); fs.mkdirSync(config);
const requests = [], posts = [], errors = [];
let base, holdResolve, appOutput, application, appProcess;
let hold = false;
const server = http.createServer(async (request, response) => {
  if (request.url === '/v1/models') { response.setHeader('content-type', 'application/json'); response.end(JSON.stringify({ data: [{ id: MODEL, context_length: 131072 }] })); return; }
  if (request.url === '/v1/chat/completions') {
    try {
      const chunks = []; for await (const chunk of request) chunks.push(chunk);
      const body = JSON.parse(Buffer.concat(chunks).toString()); requests.push(body);
      const user = body.messages.findLast(message => message.role === 'user');
      const prompt = typeof user?.content === 'string' ? user.content : user?.content?.find(part => part.type === 'text')?.text || '';
      const job = prompt.startsWith('[Scheduled run:');
      const delivery = prompt.startsWith('Scheduled run result (data):');
      const tools = body.messages.filter(message => message.role === 'tool' && message.tool_call_id?.startsWith('job-'));
      const last = tools.at(-1)?.content || '';
      console.log(`FIXTURE_ROUND: job=${job}; step=${tools.length}; posts=${posts.length}`);
      const ref = label => last.split('\n').find(line => line.includes(label) && line.includes('[ref='))?.match(/\[ref=([^\]]+)\]/)?.[1];
      let delta;
      if (delivery) {
        assert.equal(body.tools, undefined, 'The owning teammate writes without running the browser again');
        const observation = JSON.parse(prompt.slice(prompt.indexOf('\n') + 1));
        delta = { content: `I checked ${observation.job}. ${observation.result} The browser proof is attached.` };
      } else if (!job) delta = { content: 'Foreground chat remains available.' };
      else {
        if (hold && tools.length === 1) await new Promise(resolve => { holdResolve = resolve; });
        const phases = [
          { action: 'open', url: `${base}/form` },
          { action: 'fill_form', fields: [{ ref: ref('Message'), text: 'Scheduled once' }] },
          { action: 'act', op: 'click', ref: ref('Publish') },
          { action: 'read' },
          { action: 'screenshot' },
        ];
        if (tools.length < phases.length) delta = { tool_calls: [{ index: 0, id: `job-${tools.length}`, type: 'function', function: { name: 'browser', arguments: JSON.stringify(phases[tools.length]) } }] };
        else { assert.match(tools.at(-2).content, /Published Scheduled once/); delta = { content: 'Published the scheduled update once and checked the page confirmation.' }; }
      }
      response.writeHead(200, { 'content-type': 'text/event-stream' });
      response.end(`data: ${JSON.stringify({ model: MODEL, choices: [{ index: 0, delta, finish_reason: delta.tool_calls ? 'tool_calls' : 'stop' }], usage: { prompt_tokens: 20, completion_tokens: 10, total_tokens: 30 } })}\n\ndata: [DONE]\n\n`);
    } catch (error) { errors.push(error.message); response.writeHead(500); response.end(error.message); }
    return;
  }
  if (request.url?.startsWith('/publish')) { posts.push(request.url); response.writeHead(200, { 'content-type': 'text/html' }); response.end('<title>Published</title><main>Published Scheduled once</main>'); return; }
  response.writeHead(200, { 'content-type': 'text/html' }); response.end('<title>Scheduled form</title><form action="/publish"><label>Message <input name="message"></label><button>Publish</button></form>');
});
await new Promise(resolve => server.listen(0, HOST, resolve)); base = `http://${HOST}:${server.address().port}`;
new DesktopSettingsStore(path.join(config, 'desktop-settings.json')).update({ provider: 'custom', model: MODEL, customApiBase: `${base}/v1`, customApiKey: '', composioApiKey: '', profileSetupDone: true, username: 'Verification', timeZone: 'UTC' });
fs.writeFileSync(path.join(config, 'config.env'), 'ALLOW_PRIVATE_HOSTS=1\nMEMORY_CONSOLIDATION=0\nAUTO_APPROVE=1\n');
try {
  const packaged = process.argv.includes('--packaged');
  if (packaged) await build({ targets: Platform.current().createTarget('dir'), publish: 'never', projectDir: ROOT, config: { extends: path.join(ROOT, 'desktop/packaging/electron-builder.yml'), directories: { output: path.join(directory, 'package') }, electronDist: path.dirname(require('electron')), npmRebuild: false, win: { signAndEditExecutable: false }, afterPack: context => { appOutput = context.appOutDir; } } });
  const executablePath = packaged ? path.join(appOutput, fs.readdirSync(appOutput).find(name => name.endsWith('.exe'))) : require('electron');
  const env = { ...process.env, CONFIG_DIR: config, TOOL_PROVIDER: '', TOOL_MODEL: '', TOOL_API_BASE: '', TOOL_API_KEY: '', ALLOW_PRIVATE_HOSTS: '1' }; delete env.ELECTRON_RUN_AS_NODE; delete env.ANKITA_DESKTOP_DEV_URL;
  application = await electron.launch({ executablePath, args: [...(packaged ? [] : [ROOT]), `--user-data-dir=${userData}`], cwd: config, env, timeout: APP_TIMEOUT_MS });
  appProcess = application.process();
  appProcess.stderr?.on('data', chunk => { const text = chunk.toString(); if (/Error|uncaught/i.test(text)) console.log(text.slice(0, 400)); });
  const page = await application.firstWindow(); page.setDefaultTimeout(ACTION_TIMEOUT_MS); const pageErrors = []; page.on('pageerror', error => pageErrors.push(error.message));
  await page.waitForFunction(() => Boolean(window.ankita));
  const initialized = await page.evaluate(() => window.ankita.invoke('initialize'));
  console.log(`APP_OPEN_OK: model=${initialized.settings.model}; jobs=${initialized.jobs.length}`);
  assert.equal(initialized.settings.model, MODEL);
  await page.evaluate(() => window.ankita.invoke('browserPluginSetEnabled', { mode: 'isolated', enabled: true }));
  await page.getByRole('button', { name: 'Scheduled jobs', exact: true }).click();
  await page.evaluate(() => window.ankita.invoke('scheduleAdd', { name: 'Scheduled post', cron: 'daily 09:00', prompt: 'Publish the test update and verify it.', threadId: 'chief', browserPolicy: 'scoped' }));
  await page.getByRole('button', { name: /^Scheduled post/ }).click();
  await page.getByRole('button', { name: 'Edit task settings' }).click();
  const sheet = page.getByRole('complementary', { name: 'Scheduled jobs', exact: true });
  await sheet.getByLabel('Name', { exact: true }).fill('Scheduled post');
  await sheet.getByLabel('Schedule', { exact: true }).fill('daily 09:00');
  await sheet.getByLabel('Task instructions').fill('Publish the test update and verify it.');
  await sheet.getByRole('button', { name: 'Save job', exact: true }).click();
  await sheet.getByRole('button', { name: 'Run now', exact: true }).waitFor();
  let jobs = await page.evaluate(() => window.ankita.invoke('scheduleList'));
  const id = jobs[0].id;
  await sheet.getByRole('button', { name: 'Run now', exact: true }).click();
  await sheet.getByRole('button', { name: 'Close job settings' }).click();
  await page.getByRole('button', { name: 'Close scheduled tasks' }).click();
  const approval = page.getByRole('region', { name: 'Scheduled post needs approval', exact: true }); await approval.waitFor();
  assert.equal(await page.locator('.approval-dialog').count(), 0);
  const approvalBounds = await approval.boundingBox(), composerBounds = await page.locator('.jobs-composer').boundingBox();
  assert.ok(approvalBounds && composerBounds && approvalBounds.y + approvalBounds.height <= composerBounds.y, 'Inline approval buttons are visible above the composer without scrolling');
  assert.equal(await page.getByRole('textbox', { name: 'Message Chief', exact: true }).isEnabled(), true);
  await page.screenshot({ path: path.join(directory, 'inline-approval.png') });
  await approval.getByRole('button', { name: 'Always for this job' }).click();
  await page.waitForFunction(() => document.querySelector('.scheduled-result')?.textContent.includes('Published the scheduled update once'));
  await page.locator('.assistant-message').getByText('I checked Scheduled post. Published the scheduled update once and checked the page confirmation. The browser proof is attached.', { exact: true }).waitFor();
  assert.equal(await page.locator('.assistant-message .scheduled-result.compact').count(), 1);
  jobs = await page.evaluate(() => window.ankita.invoke('scheduleList')); assert.equal(jobs[0].lastStatus, 'ok'); assert.equal(jobs[0].running, false); assert.equal(posts.length, 1); assert.ok(jobs[0].lastReceipt.proof.screenshot);
  assert.deepEqual(jobs[0].allow.sites, [`${base}/*`]);
  console.log('DESKTOP_JOB_POST_OK: actual Agent + 6 HTTP/SSE rounds + real headless Chromium + one confirmed form submission + screenshot proof');
  console.log('INLINE_APPROVAL_OK: routine grant persisted; no foreground approval modal; composer remains enabled');
  await page.getByRole('button', { name: 'Scheduled jobs', exact: true }).click();
  await page.getByRole('button', { name: /^Scheduled post/ }).click();
  await page.getByRole('button', { name: 'Edit task settings' }).click();
  await sheet.locator('select').first().selectOption(id);
  await sheet.getByRole('button', { name: 'Pause', exact: true }).click();
  await sheet.getByRole('button', { name: 'Resume', exact: true }).waitFor();
  assert.equal(await sheet.getByRole('checkbox', { name: 'Enabled', exact: true }).isChecked(), false, 'Pause is reflected in the permission form before a subsequent Save');
  await sheet.getByRole('button', { name: 'Resume', exact: true }).click();
  await sheet.getByRole('button', { name: 'Pause', exact: true }).waitFor();
  assert.equal(await sheet.getByRole('checkbox', { name: 'Enabled', exact: true }).isChecked(), true);
  await sheet.getByRole('button', { name: 'Close job settings' }).click();
  await page.getByRole('button', { name: 'Close scheduled tasks' }).click();
  console.log('JOB_EDIT_CONTROLS_OK: Pause and Resume update both durable state and the form');
  hold = true;
  const priorRunId = jobs[0].lastReceipt.runId;
  await page.evaluate(id => window.ankita.invoke('scheduleRunNow', { id }), id);
  await page.waitForFunction(() => document.querySelector('.jobs-pill-toggle')?.textContent.includes('running'));
  await page.getByRole('button', { name: /^Jobs/ }).click();
  await page.getByRole('button', { name: 'Watch live', exact: true }).click();
  await page.getByRole('img', { name: /Live browser page/ }).waitFor();
  assert.equal(await page.locator('.browser-run-card').count(), 0, 'Watching a job does not duplicate its preview in the foreground transcript');
  assert.equal(await page.getByRole('complementary', { name: 'Live browser' }).innerText().then(text => text.includes('[ref=')), false);
  await page.screenshot({ path: path.join(directory, 'job-watch-live.png') });
  await page.getByRole('textbox', { name: 'Message Chief', exact: true }).fill('Is chat still available?');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await page.locator('.transcript').getByText('Foreground chat remains available.', { exact: true }).waitFor();
  console.log('CHAT_JOB_ISOLATION_OK: foreground model reply completed while the browser worker was held in a separate turn');
  const single = await page.evaluate(id => window.ankita.invoke('scheduleRunNow', { id }), id); assert.match(single.notice, /already running/);
  await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close());
  assert.equal(await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible()), false);
  hold = false; holdResolve?.();
  const deadline = Date.now() + APP_TIMEOUT_MS;
  do { jobs = await page.evaluate(() => window.ankita.invoke('scheduleList')); if (jobs[0].lastReceipt?.runId !== priorRunId && !jobs[0].running) break; await delay(STATE_POLL_MS); } while (Date.now() < deadline);
  assert.notEqual(jobs[0].lastReceipt?.runId, priorRunId, 'hidden job settled with its own receipt'); assert.equal(jobs[0].running, false); assert.equal(jobs[0].lastStatus, 'ok'); assert.equal(posts.length, 2);
  await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].show());
  await page.reload(); await page.getByRole('button', { name: 'Scheduled jobs', exact: true }).waitFor();
  await page.waitForFunction(() => document.querySelectorAll('.scheduled-result').length === 2);
  assert.equal(await page.locator('.assistant-message .scheduled-result.compact').count(), 2);
  assert.equal(await page.locator('.assistant-message').filter({ hasText: 'I checked Scheduled post.' }).count(), 2);
  console.log('TRAY_RELOAD_DELIVERY_OK: close hid the app; job finished in tray; two idempotent proof cards restored after renderer reload');
  await page.getByRole('button', { name: 'Scheduled jobs', exact: true }).click();
  await page.getByRole('button', { name: /^Scheduled post/ }).click();
  await page.getByRole('button', { name: 'Edit task settings' }).click();
  await sheet.locator('select').first().selectOption(id);
  await sheet.getByText('Execution and background settings', { exact: true }).click();
  await sheet.getByRole('button', { name: 'Pause all jobs', exact: true }).click();
  await sheet.getByRole('button', { name: 'Resume', exact: true }).waitFor();
  assert.equal(await sheet.getByRole('checkbox', { name: 'Enabled', exact: true }).isChecked(), false);
  await sheet.getByRole('button', { name: 'Save job', exact: true }).click();
  jobs = await page.evaluate(() => window.ankita.invoke('scheduleList')); assert.equal(jobs[0].enabled, false, 'Saving after Pause all keeps the routine paused');
  await sheet.getByRole('button', { name: 'Delete job', exact: true }).click();
  assert.equal((await page.evaluate(() => window.ankita.invoke('scheduleList'))).length, 0);
  await sheet.getByRole('button', { name: 'Close job settings' }).click();
  await page.getByRole('button', { name: 'Close scheduled tasks' }).click();
  console.log('JOB_MANAGEMENT_OK: Pause all stays paused after Save; Delete removes the routine');
  assert.equal(JSON.parse(fs.readFileSync(path.join(config, 'desktop-settings.json'))).settings.provider, 'custom', 'tray notice preserves provider configuration');
  assert.deepEqual(errors, []); assert.deepEqual(pageErrors, []);
  const runtime = await application.evaluate(({ app }) => ({ packaged: app.isPackaged, path: app.getAppPath() }));
  // Suppress only the new-process spawn; exercise the actual recovery IPC,
  // quit handlers, engine drain and lock release in the app under test.
  await application.evaluate(({ app }) => { app.relaunch = () => {}; });
  const exited = new Promise(resolve => appProcess.once('exit', resolve));
  await page.evaluate(() => window.ankita.appAction('relaunch')).catch(() => {}); await exited;
  assert.equal(fs.existsSync(path.join(config, 'scheduler.lock')), false, 'Recovery relaunch drains scheduler and releases ownership before restart');
  console.log('RECOVERY_RELAUNCH_OK: real IPC quit path released scheduler ownership');
  console.log(`DESKTOP_BACKGROUND_JOBS_OK: packaged=${runtime.packaged}; requests=${requests.length}; posts=${posts.length}; artifacts=${directory}`);
} finally {
  hold = false; holdResolve?.(); if (appProcess?.exitCode === null) await application.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  if (!process.argv.includes('--keep-artifacts')) await fs.promises.rm(directory, { recursive: true, force: true, maxRetries: CLEANUP_RETRIES, retryDelay: CLEANUP_DELAY_MS });
}
