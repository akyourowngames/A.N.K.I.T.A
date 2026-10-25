import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { createServer } from 'vite';
import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('../../desktop/renderer/', import.meta.url));
const ROUTE = '/transcript-ui'; // Local preview with a stubbed desktop bridge; no real process or provider.
const NOW = Date.now();

const MESSAGES = [
  { id: 'u1', role: 'user', content: 'Fix the capture bridge' },
  { id: 'think-1', role: 'assistant', content: '', reasoning: 'There is an existing test that asserts a remembered port conflict must reject.' },
  { id: 'call-read', role: 'tool', callId: 'call-read', name: 'read_file', args: { path: 'capture.test.mjs' }, result: 'test contents', isError: false, startedAt: NOW - 30, endedAt: NOW - 24 },
  { id: 'call-run', role: 'tool', callId: 'call-run', name: 'run_command', args: { command: 'grep -rhn "capture" test | head -n 20' }, result: 'grep output', isError: false, startedAt: NOW - 23, endedAt: NOW - 18 },
  { id: 'think-2', role: 'assistant', content: '', reasoning: 'Now patch the bridge and the dev runner.' },
  { id: 'call-edit', role: 'tool', callId: 'call-edit', name: 'edit_file', args: { path: 'desktop/electron/engine.mjs' }, result: 'Edited C:\\repo\\desktop\\electron\\engine.mjs\n+118 -2 · 5 lines changed at lines 27-31', isError: false, startedAt: NOW - 17, endedAt: NOW - 12 },
  { id: 'call-write', role: 'tool', callId: 'call-write', name: 'write_file', args: { path: 'desktop/renderer/src/App.tsx' }, result: 'Overwrote C:\\repo\\desktop\\renderer\\src\\App.tsx\n+3 -2 · now 120 lines', isError: false, startedAt: NOW - 11, endedAt: NOW - 7 },
  { id: 'call-fail', role: 'tool', callId: 'call-fail', name: 'run_command', args: { command: 'npm run desktop:build' }, result: 'Error: build failed', isError: true, startedAt: NOW - 6, endedAt: NOW - 2 },
  { id: 'answer', role: 'assistant', content: 'I found both root causes and fixed them.' },
];

test('agent work groups into compact thought and tool rows while the answer stays prominent', async t => {
  const vite = await createServer({ configFile: false, root: ROOT, define: { __ANKITA_VERSION__: JSON.stringify('0.0.0-test') }, server: { middlewareMode: true }, appType: 'custom' });
  const server = http.createServer(async (req, res) => {
    if (req.url !== ROUTE) return vite.middlewares(req, res);
    res.setHeader('content-type', 'text/html');
    res.end(await vite.transformIndexHtml(ROUTE, `<!doctype html><html data-theme="graphite"><body class="desktop-workbench"><div id="root"></div><script type="module">
      import React from 'react';import{createRoot}from'react-dom/client';import App from '/src/App.tsx';
      import '/src/styles.css';import '/src/workbench.css';
      const listeners=new Set();
      window.emitEvent=event=>listeners.forEach(fn=>fn(event));
      window.ankita={
        onEvent:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},
        onMenuCommand:()=>()=>{},onUpdateEvent:()=>()=>{},
        invoke:async(action,payload)=>{
          if(action==='initialize')return{teammates:[{id:'chief',name:'Chief',persona:'Your teammate',color:'sage',projectId:null}],models:[],settings:{username:'',provider:'kilo',model:'',tools:[]},chrome:'custom',jobs:[],version:'0.0.0-test',contract:7};
          if(action==='loadThread')return payload.id==='chief'?${JSON.stringify(MESSAGES)}:[];
          if(action==='listProjects')return[];
          return[];}
      };
      createRoot(document.getElementById('root')).render(React.createElement(App));
    </script></body></html>`));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true });
  t.after(async () => { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await vite.close(); });
  const page = await browser.newPage({ viewport: { width: 1100, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const capture = async name => {
    if (!process.env.ANKITA_UI_CAPTURE_DIR) return;
    fs.mkdirSync(process.env.ANKITA_UI_CAPTURE_DIR, { recursive: true });
    await page.screenshot({ path: path.join(process.env.ANKITA_UI_CAPTURE_DIR, name) });
  };
  await page.goto(`http://127.0.0.1:${server.address().port}${ROUTE}`);
  await page.locator('.teammate-row').filter({ hasText: 'Chief' }).click();
  await page.locator('.activity-group').waitFor();

  // Thoughts are rows, not empty assistant bubbles; the answer is the only assistant message.
  assert.equal(await page.locator('.activity-thought').count(), 2);
  assert.equal(await page.locator('.message.assistant-message').count(), 1);
  assert.match(await page.locator('.activity-group-header').innerText(), /Ran 5 tools/);
  assert.match(await page.locator('.activity-group-header').innerText(), /1 failed/);
  assert.equal(await page.locator('.activity-tool').count(), 5);
  assert.match(await page.locator('.activity-thought-text').first().innerText(), /remembered port conflict/);
  const labels = await page.locator('.activity-label').allTextContents();
  for (const label of ['Read file', 'Ran command', 'Edit file', 'Write file', 'Thought']) assert.ok(labels.includes(label), `missing ${label} row`);
  const args = await page.locator('.activity-arg').allTextContents();
  assert.ok(args.includes('capture.test.mjs'));
  assert.ok(args.includes('grep -rhn "capture" test | head -n 20'));
  assert.match(await page.locator('.markdown-body').innerText(), /both root causes and fixed them/);

  // Failed tools stay compact but marked, without coloring the rest of the group.
  const failed = page.locator('.activity-tool.failed');
  assert.equal(await failed.count(), 1);
  assert.equal(await failed.locator('.activity-error').innerText(), 'Failed');
  assert.equal(await failed.locator('.activity-detail').count(), 0);
  assert.equal(await page.locator('.activity-group.has-failure').count(), 1);
  await failed.locator('.activity-row').click();
  assert.match(await failed.locator('.activity-detail').innerText(), /Error: build failed/);

  // The turn closes with the files it touched and their line stats.
  const summary = page.locator('.edit-summary');
  await summary.waitFor();
  assert.match(await summary.innerText(), /Edited 2 files/);
  assert.match(await summary.innerText(), /\+121/);
  assert.match(await summary.innerText(), /-4/);
  assert.match(await summary.locator('.edit-summary-path').first().innerText(), /desktop\/electron\/engine\.mjs/);
  assert.match(await summary.locator('.edit-summary-review').innerText(), /Review/);
  await page.locator('.activity-group').first().scrollIntoViewIfNeeded();
  await capture('transcript-activity.png');
  await summary.scrollIntoViewIfNeeded();
  await capture('transcript-answer.png');

  // A row opens its own input/result without expanding the whole group.
  await page.locator('.activity-tool').filter({ hasText: 'Read file' }).locator('.activity-row').click();
  assert.match(await page.locator('.activity-tool').filter({ hasText: 'Read file' }).locator('.activity-detail').innerText(), /test contents/);
  await page.locator('.activity-thought').first().locator('.activity-row').click();
  assert.match(await page.locator('.activity-thought-body').first().innerText(), /remembered port conflict must reject/);

  // The header folds completed work away and reopens it.
  const header = page.locator('.activity-group-header').first();
  await header.click();
  assert.equal(await header.getAttribute('aria-expanded'), 'false');
  await page.locator('.activity-group').first().locator('.activity-list').waitFor({ state: 'detached' });
  await header.click();
  await page.locator('.activity-group').first().locator('.activity-list').waitFor();

  // While a later turn is running the newest group stays live with a spinner.
  await page.evaluate(() => {
    window.emitEvent({ type: 'turn-start', threadId: 'chief', turnId: 't2', text: 'Check the tests' });
    window.emitEvent({ type: 'message-start', threadId: 'chief', messageId: 'm2' });
    window.emitEvent({ type: 'reasoning-delta', threadId: 'chief', messageId: 'm2', text: 'Running the suite now.' });
    window.emitEvent({ type: 'tool-call', threadId: 'chief', callId: 'call-test', name: 'run_command', args: { command: 'npm test' } });
  });
  const live = page.locator('.activity-group').last();
  await live.locator('.activity-group-header .tool-spinner').waitFor();
  assert.match(await live.locator('.activity-group-header').innerText(), /Running 1 tool/);
  await live.scrollIntoViewIfNeeded();
  await capture('transcript-live.png');

  assert.deepEqual(errors, []);
});
