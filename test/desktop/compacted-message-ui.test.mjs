import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';

const ROOT = fileURLToPath(new URL('../../desktop/renderer/', import.meta.url));
const ROUTE = '/compacted-message-ui'; // Local preview with static props; no process or provider.

test('a compaction recap renders as a quiet labelled note, never as a user bubble', async t => {
  const vitess = await createServer({ configFile: false, root: ROOT, define: { __ANKITA_VERSION__: JSON.stringify('0.0.0-test') }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  const messages = [
    { id: 'm1', role: 'user', content: 'build the settings panel' },
    { id: 'm2', role: 'assistant', content: 'Settings panel is built and tested.', compacted: true },
    { id: 'm3', role: 'user', content: 'now add the desktop toggle' },
  ];
  const server = http.createServer(async (req, res) => {
    if (req.url !== ROUTE) return vitess.middlewares(req, res);
    res.setHeader('content-type', 'text/html');
    res.end(await vitess.transformIndexHtml(ROUTE, `<!doctype html><html data-theme="graphite"><body class="desktop-workbench"><div id="root"></div><script type="module">
      import React from 'react'; import {createRoot} from 'react-dom/client';
      import {Transcript} from '/src/components/Transcript.tsx';
      import '/src/styles.css'; import '/src/workbench.css';
      window.ankita = { invoke: async () => [], openExternal: () => {} };
      const messages = ${JSON.stringify(messages)};
      createRoot(document.getElementById('root')).render(React.createElement(Transcript, {
        messages, teammate: {id:'fixture', name:'Fixture', color:'sage'}, threadId:'fixture', running:false,
        jobs:[], onEditJob:()=>{}, onReview:()=>{}, subagentOpen:false,
      }));
    </script></body></html>`));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true });
  t.after(async () => { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await vitess.close(); });
  const page = await browser.newPage({ viewport: { width: 900, height: 700 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}${ROUTE}`);
  await page.locator('.compacted-card').waitFor();

  const card = page.locator('.compacted-card');
  assert.equal(await card.count(), 1, 'exactly one recap card');
  assert.match(await card.innerText(), /Earlier conversation, summarized/i, 'the label is styled in caps but keeps its case in the DOM');
  assert.match(await card.innerText(), /Settings panel is built and tested\./);
  assert.equal(await page.locator('.user-message').count(), 2, 'only the two real user turns get bubbles');
  assert.deepEqual(await page.locator('.user-bubble').allInnerTexts(), ['build the settings panel', 'now add the desktop toggle']);
  assert.equal(await page.locator('.assistant-message').count(), 0, 'the recap is not rendered as a teammate reply');

  const order = await page.locator('.message').evaluateAll(nodes => nodes.map(node => node.className));
  assert.match(order[0], /user-message/);
  assert.match(order[1], /compacted-message/);
  assert.match(order[2], /user-message/);
  assert.deepEqual(errors, []);
  if (process.env.ANKITA_UI_CAPTURE_DIR) {
    const { mkdirSync } = await import('node:fs');
    const { join } = await import('node:path');
    mkdirSync(process.env.ANKITA_UI_CAPTURE_DIR, { recursive: true });
    await page.screenshot({ path: join(process.env.ANKITA_UI_CAPTURE_DIR, 'compacted-message.png') });
  }
});
