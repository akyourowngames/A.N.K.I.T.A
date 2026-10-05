import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';
import { islandSizeFor } from '../desktop/electron/island.mjs';

// Browser fixtures only: an ephemeral port and isolated IPC avoid touching user chats.
const repo = fileURLToPath(new URL('../', import.meta.url));
const artifactDir = process.env.ANKITA_ISLAND_ARTIFACT_DIR || await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-island-ui-'));
const timeoutMs = 15_000; // Milliseconds; local renderer readiness, never provider latency.
const server = await createServer({ configFile: path.join(repo, 'desktop/vite.config.ts'), server: { port: 0, strictPort: false } });
let browser;
try {
  await server.listen();
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 640, height: 480 } });
  await page.exposeFunction('__resizeIsland', async action => {
    if (['tuck', 'petit', 'home', 'home-expanded', 'home-chat'].includes(action)) {
      await page.setViewportSize(islandSizeFor(action === 'tuck' ? 'petit' : action));
    }
  });
  page.setDefaultTimeout(timeoutMs);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    const listeners = new Set();
    const teammates = [{ id: 'chief', name: 'Chief', color: '#60a5fa' }, { id: 'research', name: 'Research', color: '#a78bfa' }];
    window.__teammates = teammates;
    const history = [{ id: 'old-tool', role: 'tool', callId: 'old-tool', name: 'read_file', args: { path: 'README.md' }, result: 'Project notes', isError: false }];
    window.__calls = [];
    window.__emit = event => { for (const listener of listeners) listener(event); };
    window.ankita = {
      onEvent: callback => { listeners.add(callback); return () => listeners.delete(callback); },
      onCursor: () => () => {},
      islandAction: async (action, options) => { window.__calls.push({ action, options }); await window.__resizeIsland(action); return true; },
      openExternal: async () => {},
      redact: async text => text,
      invoke: async (action, payload) => {
        window.__calls.push({ action, payload });
        if (action === 'islandSnapshot') return { teammates, threads: teammates.map(t => ({ id: t.id, running: false, messages: t.id === 'chief' ? history : [] })) };
        if (action === 'listTeammates') return teammates;
        if (action === 'loadThread') return payload.id === 'chief' ? history : [];
        if (action === 'approvalList' && window.__deferApprovalList) return new Promise(resolve => { window.__completeApprovalList = resolve; });
        if (action === 'scheduleList' || action === 'approvalList') return [];
        if (action === 'respondApproval' && window.__rejectApproval) throw new Error('Connection unavailable');
        if (action === 'respondApproval') { window.__emit({ type: 'approval-resolved', requestId: payload.requestId }); return true; }
        if (action === 'send') {
          window.__emit({ type: 'turn-start', threadId: payload.id, turnId: 'sent-turn', text: payload.text, attachments: payload.attachments?.map(file => ({ name: file.name })) });
          return { turnId: 'sent-turn' };
        }
        return true;
      },
    };
  });
  await page.goto(`${server.resolvedUrls.local[0]}island.html`);
  await page.getByRole('button', { name: 'Open Ankita island', exact: true }).click();
  await page.evaluate(() => window.__emit({ type: 'turn-start', threadId: 'chief', turnId: 'live', text: 'Inspect app' }));
  await page.evaluate(() => window.__emit({ type: 'tool-call', threadId: 'chief', callId: 'live-read', name: 'read_file', args: { path: 'src/app.ts' } }));
  await page.getByLabel('Overview', { exact: true }).click();
  await page.getByText('app.ts', { exact: false }).first().waitFor();
  assert.equal(await page.locator('[data-mascot-state="working"]').count(), 1);
  console.log('PASS ordinary ANKITA tools appear in the overview and drive mascot state');
  await page.screenshot({ path: path.join(artifactDir, 'overview.png') });
  await page.getByLabel('Ask', { exact: true }).click();
  await page.evaluate(() => {
    window.__emit({ type: 'message-start', threadId: 'chief', messageId: 'live-answer' });
    window.__emit({ type: 'reasoning-delta', threadId: 'chief', messageId: 'live-answer', text: 'HIDDEN_REASONING' });
    window.__emit({ type: 'assistant-delta', threadId: 'chief', messageId: 'live-answer', text: '**Visible answer**' });
  });
  await page.getByText('Visible answer', { exact: true }).waitFor();
  assert.equal(await page.getByText('HIDDEN_REASONING', { exact: false }).count(), 0);
  await page.getByRole('button', { name: /read_file.*README/ }).click();
  await page.getByText('Project notes', { exact: true }).waitFor();
  console.log('PASS reasoning is separate, Markdown renders, persisted tool output expands');
  await page.screenshot({ path: path.join(artifactDir, 'chat.png') });
  await page.evaluate(() => {
    window.__emit({ type: 'tool-result', threadId: 'chief', callId: 'live-read', text: '1: App content', isError: false });
    window.__emit({ type: 'turn-end', threadId: 'chief', turnId: 'live' });
  });
  await page.getByLabel('Message', { exact: true }).fill('Chief draft');
  await page.getByLabel('Chat teammate').selectOption('research');
  await page.getByLabel('Message', { exact: true }).fill('Research draft');
  await page.getByLabel('Chat teammate').selectOption('chief');
  assert.equal(await page.getByLabel('Message', { exact: true }).inputValue(), 'Chief draft');
  await page.locator('input[type="file"]').setInputFiles({ name: 'notes.md', mimeType: 'text/markdown', buffer: Buffer.from('Attachment context') });
  await page.getByRole('button', { name: 'Remove notes.md' }).waitFor();
  await page.getByLabel('Message', { exact: true }).fill('Use this file');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await page.getByRole('button', { name: 'Stop reply' }).waitFor();
  const sent = await page.evaluate(() => window.__calls.findLast(call => call.action === 'send'));
  assert.equal(sent.payload.surface, 'island');
  assert.equal(sent.payload.id, 'chief');
  assert.equal(Buffer.from(sent.payload.attachments[0].data, 'base64').toString(), 'Attachment context');
  await page.getByRole('button', { name: 'Stop reply' }).click();
  assert.equal(await page.evaluate(() => window.__calls.some(call => call.action === 'cancel' && call.payload.id === 'chief')), true);
  console.log('PASS teammate drafts persist; attachment bytes and stop reach the engine IPC');
  await page.evaluate(() => window.__emit({ type: 'approval-request', requestId: 'permission', threadId: 'chief', toolName: 'run_command', detail: 'Review this change\n' + 'full diff line\n'.repeat(40) }));
  await page.getByRole('button', { name: 'Always allow', exact: true }).waitFor();
  const allowBounds = await page.getByRole('button', { name: 'Allow', exact: true }).boundingBox();
  assert.ok(allowBounds.y + allowBounds.height <= page.viewportSize().height, 'long approval details must scroll while the answer buttons stay visible');
  await page.evaluate(() => { window.__rejectApproval = true; });
  await page.getByRole('button', { name: 'Allow', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'Connection unavailable' }).waitFor();
  assert.equal(await page.locator('[data-home-view="approval"]').count(), 1);
  await page.evaluate(() => window.dispatchEvent(new Event('blur')));
  assert.equal(await page.locator('[data-shell-view="home"]').count(), 1);
  await page.screenshot({ path: path.join(artifactDir, 'approval.png') });
  await page.evaluate(() => { window.__rejectApproval = false; });
  await page.getByRole('button', { name: 'Always allow', exact: true }).click();
  await page.waitForFunction(() => window.__calls.some(call => call.action === 'respondApproval' && call.payload.answer === 'always'));
  console.log('PASS approvals stay pinned and retryable on IPC failure; Always allow reaches the engine');
  await page.getByRole('button', { name: 'Open Ankita island', exact: true }).click();
  await page.getByLabel('Settings', { exact: true }).click();
  await page.getByRole('switch', { name: 'Sound' }).click();
  assert.equal(await page.getByRole('button', { name: 'Unmute', exact: true }).count(), 1);
  await page.reload();
  await page.getByRole('button', { name: 'Open Ankita island', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: 'Unmute', exact: true }).count(), 1);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.getByLabel('Ask', { exact: true }).click();
  await page.waitForFunction(() => window.__calls.some(call => call.action === 'home-chat' && call.options?.animate === false));
  assert.equal(await page.locator('.island-view').evaluate(el => getComputedStyle(el).animationName), 'none');
  console.log('PASS sound preferences survive reload; reduced motion reaches native geometry and CSS');
  await page.setViewportSize({ width: 400, height: 300 });
  await page.screenshot({ path: path.join(artifactDir, 'small-display.png') });
  const overflow = await page.locator('.island').evaluate(el => el.scrollWidth > el.clientWidth);
  assert.equal(overflow, false);
  console.log('PASS companion fits a small display without horizontal overflow');
  await page.evaluate(() => {
    window.__teammates.push(...['Research desk with a very long name', 'Development and implementation team', 'Quality assurance and release agent', 'Additional teammate'].map((name, index) => ({ id: 'extra-' + index, name, color: '#60a5fa' })));
    window.__emit({ type: 'teammates-changed' });
    window.__emit({ type: 'schedule-changed', jobs: [{ id: 'scheduled-check', name: 'Instagram follower check (scheduled)', threadId: 'chief', running: false, needsApproval: false, lastStatus: 'completed' }] });
    for (const [index, name] of ['job_status', 'job_stop', 'run_command'].entries()) {
      window.__emit({ type: 'tool-call', threadId: 'chief', callId: 'layout-' + index, name, args: 'A long tool command and argument '.repeat(10) });
      window.__emit({ type: 'tool-result', threadId: 'chief', callId: 'layout-' + index, text: 'Completed output\n'.repeat(20), isError: false });
    }
    window.__emit({ type: 'turn-end', threadId: 'chief', turnId: 'sent-turn' });
  });
  await page.getByLabel('Overview', { exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll('.island-pill').length === 4);
  assert.equal(await page.locator('.island-ticker').count(), 1, 'overview tool history needs a rolling ticker instead of a scrollbar');
  assert.equal(await page.locator('.island-overview-right.island-card').count(), 0, 'teammates must use a plain list instead of a card');
  await page.waitForFunction(() => document.querySelector('.ticker-row-current .ticker-text')?.textContent.includes('run_command'));
  await page.screenshot({ path: path.join(artifactDir, 'crowded-overview.png') });
  const layoutProblems = await page.evaluate(() => {
    const problems = [];
    const pills = [...document.querySelectorAll('.island-pill')];
    if (pills.length !== 4) problems.push('expected 4 teammate pills, got ' + pills.length);
    if (pills.some(pill => pill.textContent.includes('Instagram'))) problems.push('scheduled job leaked into teammates');
    if (new Set(pills.map(pill => pill.querySelector('.island-mini-face').dataset.face)).size !== pills.length) problems.push('teammate avatars did not have distinct expressions');
    if (pills.some(pill => parseFloat(getComputedStyle(pill.querySelector('.lbl')).fontSize) > 10)) problems.push('teammate names are too large for the avatar layout');
    if (pills.length >= 4) {
      const boxes = pills.slice(0, 4).map(pill => pill.getBoundingClientRect());
      if (Math.abs(boxes[0].y - boxes[1].y) > 1 || Math.abs(boxes[2].y - boxes[3].y) > 1 || boxes[0].x === boxes[1].x) problems.push('long names did not stay in two columns');
    }
    const steps = document.querySelector('.island-activity-steps');
    const actions = document.querySelector('.island-activity-actions');
    const lastTool = steps.lastElementChild.getBoundingClientRect();
    if (getComputedStyle(steps).overflowY !== 'hidden') problems.push('overview tool history added a scrollbar');
    if (lastTool.bottom > actions.getBoundingClientRect().top) problems.push('tool rows overlap conversation actions');
    if (actions.getBoundingClientRect().bottom > innerHeight) problems.push('conversation actions are clipped');
    return problems;
  });
  assert.deepEqual(layoutProblems, [], 'crowded overview must fit real teammate names and tool history');
  console.log('PASS four teammates stay in two columns; jobs are excluded and tool history has no scrollbar or overlap');
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.waitForFunction(() => document.querySelector('.island-ticker')?.dataset.reducedMotion === 'false');
  await page.evaluate(() => window.__emit({ type: 'tool-call', threadId: 'chief', callId: 'rolling-proof', name: 'read_file', args: { path: 'roll-proof.md' } }));
  await page.waitForFunction(() => {
    const row = document.querySelector('.ticker-row-current');
    const y = row && new DOMMatrixReadOnly(getComputedStyle(row).transform).m42;
    return y > 0 && y < 21;
  });
  await page.waitForFunction(() => document.querySelector('.ticker-row-current .ticker-text')?.textContent.includes('roll-proof.md'));
  await page.evaluate(() => {
    window.__emit({ type: 'tool-result', threadId: 'chief', callId: 'rolling-proof', text: 'Rolling tool output proof', isError: false });
    window.__emit({ type: 'turn-end', threadId: 'chief', turnId: 'sent-turn' });
  });
  await page.waitForFunction(() => document.querySelector('.ticker-row-current')?.dataset.state === 'ok');
  await page.evaluate(() => {
    for (let index = 0; index < 6; index++) {
      window.__emit({ type: 'tool-call', threadId: 'chief', callId: 'burst-' + index, name: 'read_file', args: { path: 'burst-' + index + '.md' } });
      window.__emit({ type: 'tool-result', threadId: 'chief', callId: 'burst-' + index, text: 'Burst result', isError: index === 5 });
    }
  });
  await page.waitForFunction(() => document.querySelector('.ticker-row-current .ticker-text')?.textContent.includes('burst-5.md'));
  assert.equal(await page.locator('.ticker-row-current').getAttribute('data-state'), 'error', 'a rolling feed must retain the real failed-tool state');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.waitForFunction(() => document.querySelector('.island-ticker')?.dataset.reducedMotion === 'true');
  await page.evaluate(() => window.__emit({ type: 'tool-call', threadId: 'chief', callId: 'quiet-proof', name: 'read_file', args: { path: 'quiet-proof.md' } }));
  await page.waitForFunction(() => document.querySelector('.ticker-row-current .ticker-text')?.textContent.includes('quiet-proof.md'));
  assert.equal(await page.locator('.ticker-row-current').evaluate(el => new DOMMatrixReadOnly(getComputedStyle(el).transform).m42 === parseFloat(getComputedStyle(el.parentElement).getPropertyValue('--ticker-row-height'))), true, 'reduced motion must settle directly without a rolling transition');
  await page.setViewportSize({ width: 400, height: islandSizeFor('home-expanded').height });
  await page.screenshot({ path: path.join(artifactDir, 'small-overview.png') });
  assert.equal(await page.locator('.island-pill').evaluateAll(elements => elements.every(el => el.getBoundingClientRect().bottom <= innerHeight)), true, 'all four teammate avatars must remain visible on a narrow companion');
  assert.equal(await page.locator('.island-activity-actions').evaluate(el => el.getBoundingClientRect().bottom <= innerHeight), true, 'narrow companion actions must stay visible');
  console.log('PASS four teammate avatars and conversation actions stay visible on a narrow companion');
  await page.setViewportSize(islandSizeFor('home-expanded'));
  await page.getByRole('button', { name: 'Open conversation', exact: true }).click();
  await page.getByRole('button', { name: /read_file.*roll-proof.*Completed/ }).click();
  await page.getByText('Rolling tool output proof', { exact: true }).waitFor();
  console.log('PASS tools roll upward, bounded bursts retain errors, reduced motion settles directly, and full output remains in conversation');
  await page.addInitScript(() => { window.__deferApprovalList = true; });
  await page.reload();
  await page.getByRole('button', { name: 'Open Ankita island', exact: true }).waitFor();
  await page.evaluate(() => window.__emit({ type: 'approval-request', requestId: 'during-startup', threadId: 'chief', toolName: 'write_file', detail: 'Live permission' }));
  await page.getByText('Live permission', { exact: true }).waitFor();
  await page.evaluate(() => window.__completeApprovalList([]));
  assert.equal(await page.locator('[data-home-view="approval"]').count(), 1, 'a stale startup snapshot must not erase a newer approval');
  await page.getByRole('button', { name: 'Deny', exact: true }).click();
  await page.reload();
  await page.getByRole('button', { name: 'Open Ankita island', exact: true }).waitFor();
  await page.evaluate(() => {
    const request = { requestId: 'already-resolved', threadId: 'chief', toolName: 'write_file', detail: 'Resolved elsewhere' };
    window.__emit({ type: 'approval-request', ...request });
    window.__emit({ type: 'approval-resolved', requestId: request.requestId });
    window.__completeApprovalList([request]);
  });
  await page.waitForFunction(() => !document.querySelector('[data-home-view="approval"]'));
  console.log('PASS startup snapshots retain newer approvals and never resurrect resolved permissions');
  assert.deepEqual(errors, []);
  console.log(`Screenshots: ${artifactDir}`);
} finally {
  await browser?.close();
  await server.close();
}
