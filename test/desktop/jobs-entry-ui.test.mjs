import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';

const ROOT = fileURLToPath(new URL('../../desktop/renderer/', import.meta.url));
const ROUTE = '/jobs-entry-ui'; // Local preview; no scheduler or real account.

// One representative paused routine; states below are derived from it so the
// fixtures never drift apart.
const JOB = {
  id: 'job-fixture', name: 'Morning brief', description: 'Summarize the inbox.', kind: 'routine',
  cron: '0 9 * * 1-5', cronLabel: 'Every weekday at 9:00', prompt: 'Summarize the inbox.',
  threadId: 'fixture', deliveryThreadId: 'fixture',
  allow: { read: true, interact: true, login: false, sites: [], mode: 'isolated' },
  budget: { maxRunsPerDay: 4, maxTokensPerDay: 200000, maxMinutesPerDay: 20 },
  timeoutMs: 300000, headless: true, onNewRequest: 'pause-ask',
  enabled: false, ownerMissing: false, pausedReason: null, nextRunAt: null, nextRunIn: null,
  timeZone: 'UTC', running: false, step: 0, scope: null, needsApproval: false,
  lastStatus: 'ok', lastSummary: null,
};

async function chipText(page) {
  return page.locator('.jobs-header-chip span').innerText();
}

test('scheduled jobs live in the context-bar chip instead of a card above the composer', async t => {
  const vite = await createServer({ configFile: false, root: ROOT, server: { middlewareMode: true }, appType: 'custom' });
  const server = http.createServer(async (req, res) => {
    if (req.url !== ROUTE) return vite.middlewares(req, res);
    res.setHeader('content-type', 'text/html');
    res.end(await vite.transformIndexHtml(ROUTE, `<!doctype html><html data-theme="graphite"><body class="desktop-workbench"><div id="root"></div><script type="module">
      import React, { useState } from 'react'; import { createRoot } from 'react-dom/client';
      import { ChatPane } from '/src/components/ChatPane.tsx'; import '/src/styles.css'; import '/src/workbench.css';
      window.calls = [];
      window.ankita = { onEvent: () => () => {}, invoke: async action => { window.calls.push({ action }); return []; } };
      function Harness() {
        const [jobs, setJobs] = useState([]);
        window.showJobs = next => setJobs(next);
        const noop = () => {};
        return React.createElement(ChatPane, {
          teammate: { id: 'fixture', name: 'Research desk', persona: 'Your teammate', color: 'sage', projectId: null },
          messages: [], running: false, models: [], projects: [], defaultModel: '', provider: 'Copilot',
          chrome: 'custom', sidebarOpen: true, reviewOpen: false, subagents: {}, subagentOpen: false, commandsRevision: 0,
          jobs, onEditJob: id => window.calls.push({ action: 'editJob', id }),
          onToggleSidebar: noop, onToggleReview: noop, onOpenBrowser: noop, onProject: noop, onOpenProjects: noop,
          onSend: noop, onStop: noop, onModel: noop, onEdit: noop, onCreate: noop, onClear: noop, onDelete: noop,
          onToggleSubagent: noop, onOpenSubagent: noop, onCommand: noop,
        });
      }
      createRoot(document.getElementById('root')).render(React.createElement(Harness));
    </script></body></html>`));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true });
  t.after(async () => { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await vite.close(); });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } }), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}${ROUTE}`);

  await page.waitForFunction(() => document.querySelector('.jobs-header-chip span')?.textContent === 'Schedule');
  assert.equal(await page.locator('.jobs-pill').count(), 0, 'no jobs card sits above the composer');
  assert.equal(await page.locator('.jobs-composer').count(), 0, 'the composer is not wrapped in a jobs strip');
  assert.equal(await page.getByRole('textbox', { name: 'Message Research desk' }).count(), 1);

  await page.evaluate(job => window.showJobs([job]), JOB);
  await page.waitForFunction(() => document.querySelector('.jobs-header-chip span')?.textContent === '1 job · All paused');
  assert.equal(await page.locator('.jobs-pill').count(), 0);
  assert.equal(await page.locator('.jobs-header-chip .jobs-live-dot').count(), 0, 'a paused job needs no live dot');
  assert.match(await page.locator('.jobs-header-chip').getAttribute('title'), /^Scheduled jobs · 1 job · All paused$/);
  if (process.env.ANKITA_UI_CAPTURE_DIR) {
    fs.mkdirSync(process.env.ANKITA_UI_CAPTURE_DIR, { recursive: true });
    await page.screenshot({ path: path.join(process.env.ANKITA_UI_CAPTURE_DIR, 'jobs-header-entry.png') });
  }
  await page.getByRole('button', { name: 'Scheduled jobs' }).click();
  assert.equal(await page.evaluate(() => window.calls.filter(call => call.action === 'editJob').length), 1);
  assert.equal(await page.evaluate(() => window.calls.at(-1).id ?? null), null, 'the chip opens the task list');

  await page.evaluate(job => window.showJobs([{ ...job, enabled: true, nextRunAt: '2030-01-01T09:00:00.000Z' }]), JOB);
  await page.waitForFunction(() => /^1 job · Next /.test(document.querySelector('.jobs-header-chip span')?.textContent || ''));
  assert.match(await chipText(page), /^1 job · Next /);

  await page.evaluate(job => window.showJobs([{ ...job, enabled: true, running: true, step: 2, scope: 'run-scope' }]), JOB);
  await page.waitForFunction(() => document.querySelector('.jobs-header-chip span')?.textContent === '1 job · Running');
  assert.equal(await page.locator('.jobs-header-chip.running').count(), 1);
  assert.equal(await page.locator('.jobs-header-chip .jobs-live-dot').count(), 1, 'a live run keeps a pulsing dot');

  await page.evaluate(job => window.showJobs([{ ...job, needsApproval: true }]), JOB);
  await page.waitForFunction(() => document.querySelector('.jobs-header-chip span')?.textContent === '1 job · Needs attention');
  assert.equal(await page.locator('.jobs-header-chip.attention').count(), 1);

  await page.evaluate(job => window.showJobs([{ ...job, id: 'job-a', needsApproval: true }, { ...job, id: 'job-b', needsApproval: true }]), JOB);
  await page.waitForFunction(() => document.querySelector('.jobs-header-chip span')?.textContent === '2 jobs · 2 need attention');

  await page.evaluate(() => window.showJobs([]));
  await page.waitForFunction(() => document.querySelector('.jobs-header-chip span')?.textContent === 'Schedule');
  assert.equal(await page.locator('.jobs-header-chip .jobs-live-dot').count(), 0);
  assert.deepEqual(errors, []);
});
