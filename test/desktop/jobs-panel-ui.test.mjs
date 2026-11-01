import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';

const ROOT = fileURLToPath(new URL('../../desktop/renderer/', import.meta.url));
const ROUTE = '/jobs-panel-ui'; // Local preview with stubbed data; no process or provider.
const TEAMMATE = { id: 'fixture', name: 'Fixture', color: 'sage', projectId: null };
const baseJob = (patch = {}) => ({
  id: 'job-1', name: 'Morning inbox', cron: '* * * * *', cronLabel: 'Every minute', prompt: 'Read the inbox', threadId: 'fixture', deliveryThreadId: 'fixture',
  allow: { read: true, interact: true, login: false, sites: [], mode: 'isolated' }, budget: { maxRunsPerDay: 4, maxTokensPerDay: 1, maxMinutesPerDay: 1 },
  timeoutMs: 1000, headless: true, onNewRequest: 'pause-ask', enabled: true, ownerMissing: false, pausedReason: null,
  nextRunAt: '2026-11-01T09:00:00.000Z', nextRunIn: 1000, timeZone: 'UTC', running: false, step: 0, scope: null,
  needsApproval: false, lastStatus: 'ok', lastSummary: 'Read complete.', ...patch,
});
const PENDING = [
  { runId: 'r1', routineId: 'job-1', name: 'Morning inbox', status: 'ok', at: new Date(Date.now() - 120000).toISOString() },
  { runId: 'r2', routineId: 'job-2', name: 'Price watch', status: 'ok', at: new Date(Date.now() - 60000).toISOString() },
  { runId: 'r3', routineId: 'job-3', name: 'Weekly digest', status: 'ok', at: new Date(Date.now() - 30000).toISOString() },
];

async function open(t, jobs = [baseJob()], pending = PENDING) {
  const vite = await createServer({ configFile: false, root: ROOT, define: { __ANKITA_VERSION__: JSON.stringify('0.0.0-test') }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  const server = http.createServer(async (req, res) => {
    if (req.url !== ROUTE) return vite.middlewares(req, res);
    res.setHeader('content-type', 'text/html');
    res.end(await vite.transformIndexHtml(ROUTE, `<!doctype html><html data-theme="graphite"><body class="desktop-workbench"><div id="root"></div><script type="module">
      import React from 'react'; import {createRoot} from 'react-dom/client';
      import {JobsPanel} from '/src/components/JobsPanel.tsx';
      import '/src/styles.css'; import '/src/workbench.css';
      window.ankita = { invoke: async (action) => action === 'scheduleAwaySummary'
        ? { ran: 6, quiet: 2, needsYou: 1, readyToPost: ${pending.length} } : [] };
      createRoot(document.getElementById('root')).render(React.createElement(JobsPanel, {
        jobs: ${JSON.stringify(jobs)}, teammates: [${JSON.stringify(TEAMMATE)}], threadId: 'fixture', selectedId: null,
        pending: ${JSON.stringify(pending)}, onChoose: () => {}, onEdit: () => {}, onWatch: () => {}, onAsk: () => {}, onClose: () => {},
      }));
    </script></body></html>`));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true });
  t.after(async () => { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await vite.close(); });
  const page = await browser.newPage({ viewport: { width: 900, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}${ROUTE}`);
  await page.locator('.jobs-panel').waitFor();
  return { page, errors };
}

test('waiting results are listed in the jobs panel with one expandable row each', async t => {
  const { page, errors } = await open(t);
  const group = page.getByRole('region', { name: 'Results ready to post' });
  await group.waitFor();
  assert.match(await group.locator('.jobs-group-title').innerText(), /3 results ready/i, 'uppercase is styling only');
  const rows = group.locator('.jobs-delivery');
  assert.equal(await rows.count(), 3, 'every update keeps its own row');

  // Collapsed by default: the panel is quiet until asked.
  assert.equal(await group.locator('.jobs-delivery-body').count(), 0);
  const head = rows.first().locator('.jobs-delivery-head');
  await head.click();
  assert.equal(await group.locator('.jobs-delivery-body').count(), 1, 'clicking expands just that result');
  assert.equal(await head.getAttribute('aria-expanded'), 'true');

  if (process.env.ANKITA_UI_CAPTURE_DIR) {
    const { mkdirSync } = await import('node:fs');
    const { join } = await import('node:path');
    mkdirSync(process.env.ANKITA_UI_CAPTURE_DIR, { recursive: true });
    await page.locator('.jobs-panel').screenshot({ path: join(process.env.ANKITA_UI_CAPTURE_DIR, 'jobs-ready-to-post.png') });
  }
  assert.deepEqual(errors, []);
});

test('the away strip counts what happened without adding any chat messages', async t => {
  const { page, errors } = await open(t);
  const strip = page.getByRole('status', { name: 'While you were away' });
  await strip.waitFor();
  const text = await strip.innerText();
  assert.match(text, /6\s*ran/);
  assert.match(text, /2\s*quiet/);
  assert.match(text, /1\s*need you/);
  assert.deepEqual(errors, []);
});

test('a running job shows its step in the panel, and a deferred heartbeat says it is waiting', async t => {
  const running = baseJob({ id: 'job-run', name: 'Long read', running: true, step: 4 });
  const deferred = baseJob({ id: 'job-hb', name: 'Ambient check', kind: 'heartbeat', pendingHeartbeatAt: '2026-11-01T08:30:00.000Z', coalescedHeartbeats: 3 });
  const { page, errors } = await open(t, [running, deferred], []);
  assert.equal(await page.locator('.jobs-delivery').count(), 0, 'no waiting results, so no ready group');
  const rows = page.locator('.upcoming-job');
  const metas = await rows.allInnerTexts();
  assert.ok(metas.some(text => /Running · step 4/.test(text)), 'the live step is visible');
  assert.ok(metas.some(text => /Waiting for this chat · 3 checks held/.test(text)), 'a deferred heartbeat says it is pending');
  assert.deepEqual(errors, []);
});
