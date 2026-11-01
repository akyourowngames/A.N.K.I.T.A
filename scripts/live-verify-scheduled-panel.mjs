// Live verification: a real scheduled task on the real provider, watched in the
// jobs panel. Uses the tester's own .env (Kilo) — no model stub.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import { _electron as electron } from 'playwright';

const require = createRequire(import.meta.url);
const ROOT = path.resolve(fileURLToPath(new URL('..', import.meta.url))); // Repo root, not scripts/.
const executablePath = require('electron');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-live-jobs-'));
const config = path.join(dir, 'config'), userData = path.join(dir, 'user-data');
fs.mkdirSync(config, { recursive: true });
// Reuse the tester's provider credentials, but keep ALL app state (scheduler
// lock, sessions, jobs) inside this throwaway directory: CONFIG_DIR is honoured
// by the main process, so a live instance can never be disturbed.
fs.mkdirSync(config, { recursive: true });
const realEnv = path.join(ROOT, '.env');
if (fs.existsSync(realEnv)) fs.copyFileSync(realEnv, path.join(config, 'config.env'));

const STEP_MS = 150, LIMIT_MS = 240000; // Fast poll: the waiting state can be a couple of seconds.
const log = (...parts) => console.log(...parts);
let application, page;
const shots = (name) => path.join(ROOT, '.live-verify', name);

try {
  application = await electron.launch({ executablePath, args: [ROOT, `--user-data-dir=${userData}`], cwd: config,
    env: { ...process.env, CONFIG_DIR: config }, timeout: 60000 });
  page = await application.firstWindow();
  page.setDefaultTimeout(30000);
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.waitForFunction(() => Boolean(window.ankita));
  // Record engine events so a failed handoff reports its real reason.
  await page.evaluate(() => {
    window.__events = [];
    window.ankita.onEvent(event => {
      if (/routine|scheduler|error/.test(event.type)) window.__events.push({ type: event.type, detail: event.detail, reason: event.reason, message: event.message, status: event.status });
    });
  });

  const initialized = await page.evaluate(() => window.ankita.invoke('initialize'));
  log(`APP_OPEN_OK: provider=${initialized.settings.provider} model=${initialized.settings.model} jobs=${initialized.jobs.length}`);
  log(`TEAMMATES: ${JSON.stringify(initialized.teammates.map(t => ({ id: t.id, name: t.name })))}`);
  if (!initialized.teammates.length) throw new Error('No teammate exists; cannot own a job.');
  const owner = initialized.teammates[0].id;

  // A returning user has already finished first-run setup; this throwaway profile
  // has not, so mark it done exactly as the onboarding button does.
  await page.evaluate(() => window.ankita.invoke('saveDesktopSettings', { profileSetupDone: true }));
  await page.locator('.modal-backdrop').waitFor({ state: 'detached', timeout: 15000 }).catch(() => {});
  await delay(500);

  await page.getByRole('button', { name: 'Scheduled jobs', exact: true }).click();
  const job = await page.evaluate(({ owner }) => window.ankita.invoke('scheduleAdd', {
    name: 'Live panel check',
    cron: 'daily 09:00',
    prompt: 'Reply with the single sentence: the live scheduled run reached the panel.',
    threadId: owner,
    browserPolicy: 'scoped',
  }), { owner });
  log(`JOB_ADDED: ${JSON.stringify({ id: job.id || job.routine?.id, name: job.name || job.routine?.name })}`);
  const jobs = await page.evaluate(() => window.ankita.invoke('scheduleList'));
  const jobId = jobs.at(-1).id;

  // The waiting group only exists while the owning teammate is mid-turn, so hold
  // the chat busy with a slow request long enough for the job to finish first.
  const slowTurn = page.evaluate(owner => window.ankita.invoke('send', { id: owner,
    text: 'Write a detailed 300-word essay about the history of the printing press.' }), owner);
  slowTurn.catch(() => {});
  await delay(800);
  log('TURN_STARTED (chat busy)');

  await page.evaluate(id => window.ankita.invoke('scheduleRunNow', { id }), jobId);
  log('RUN_STARTED (real provider call, chat busy)');

  // Watch the panel's own DOM for the live row and then the waiting result.
  const started = Date.now();
  let sawLive = false, readyText = '';
  while (Date.now() - started < LIMIT_MS) {
    if (!sawLive) {
      const live = await page.locator('.job-live-run').count().catch(() => 0);
      const runningMeta = await page.locator('.upcoming-job').allInnerTexts().catch(() => []);
      if (live || runningMeta.some(text => /Running · step/.test(text))) {
        sawLive = true;
        log(`LIVE_ROW_SEEN: ${(runningMeta.find(text => /Running · step/.test(text)) || 'detail panel live row').replace(/\n/g, ' | ')}`);
      }
    }
    const group = page.locator('.jobs-group.ready');
    if (await group.count()) {
      readyText = await group.innerText();
      if (readyText.includes('Live panel check')) break;
    }
    await delay(STEP_MS);
  }
  fs.mkdirSync(path.join(ROOT, '.live-verify'), { recursive: true });
  await page.locator('.jobs-panel').screenshot({ path: shots('panel-after-run.png') }).catch(() => {});

  if (!readyText.includes('Live panel check') && !readyText.includes('RESULT')) throw new Error(`No waiting result appeared. Last group text: ${JSON.stringify(readyText)}`);
  log(`READY_GROUP: ${readyText.replace(/\n/g, ' | ')}`);
  log(`ENGINE_EVENTS: ${JSON.stringify(await page.evaluate(() => window.__events))}`);

  const row = page.locator('.jobs-delivery').filter({ hasText: 'Live panel check' }).first();
  await row.locator('.jobs-delivery-head').click();
  const body = await row.locator('.jobs-delivery-body').innerText();
  log(`EXPANDED_ROW: ${body.replace(/\n/g, ' | ').slice(0, 600)}`);
  await page.locator('.jobs-panel').screenshot({ path: shots('panel-expanded.png') });

  // Probe: once the busy turn ends, the waiting row must leave the group and the
  // result must appear in the chat. Nothing should stay stuck in "ready to post".
  log('PROBE: waiting for the busy turn to end');
  let cleared = false;
  const probeStart = Date.now();
  while (Date.now() - probeStart < 180000) {
    const ready = await page.locator('.jobs-delivery').count().catch(() => 0);
    if (ready === 0) { cleared = true; break; }
    await delay(300);
  }
  const thread = await page.evaluate(() => window.ankita.invoke('loadThread', { id: 'chief' })).catch(() => []);
  const posted = thread.some(item => item.role === 'assistant' && /reached the panel/i.test(item.content || ''));
  log(`PROBE_RESULT: waitingRowCleared=${cleared}; resultInChat=${posted}`);
  await page.locator('.jobs-panel').screenshot({ path: shots('panel-after-flush.png') }).catch(() => {});
  if (!cleared || !posted) throw new Error(`Probe failed: cleared=${cleared} posted=${posted}`);
  if (pageErrors.length) log(`PAGE_ERRORS: ${JSON.stringify(pageErrors)}`);
  log('LIVE_VERIFY_OK');
} catch (error) {
  log(`LIVE_VERIFY_FAILED: ${error.message}`);
  if (page) { try { fs.mkdirSync(path.join(ROOT, '.live-verify'), { recursive: true }); await page.locator('.jobs-panel').screenshot({ path: shots('panel-failure.png') }); } catch {} }
  process.exitCode = 1;
} finally {
  try { await application?.close(); } catch {}
}
