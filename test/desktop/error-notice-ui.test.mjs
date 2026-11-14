import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { createServer } from 'vite';
import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('../../desktop/renderer/', import.meta.url));
const ROUTE = '/notice-ui'; // Local preview with a stubbed desktop bridge; no real process or provider.

test('engine failures render as human notices with technical detail tucked away', async t => {
  const vite = await createServer({ configFile: false, root: ROOT, define: { __ANKITA_VERSION__: JSON.stringify('0.0.0-test') }, server: { middlewareMode: true }, appType: 'custom' });
  const server = http.createServer(async (req, res) => {
    if (req.url !== ROUTE) return vite.middlewares(req, res);
    res.setHeader('content-type', 'text/html');
    res.end(await vite.transformIndexHtml(ROUTE, `<!doctype html><html data-theme="graphite"><body class="desktop-workbench"><div id="root"></div><script type="module">
      import React from 'react';import{createRoot}from'react-dom/client';import App from '/src/App.tsx';
      import '/src/styles.css';import '/src/workbench.css';
      const listeners=new Set();
      window.emitEvent=event=>listeners.forEach(fn=>fn(event));
      window.calls=[];
      window.ankita={
        onEvent:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},
        onMenuCommand:()=>()=>{},onUpdateEvent:()=>()=>{},
        invoke:async(action,payload)=>{window.calls.push({action,payload});
          if(action==='initialize')return{teammates:[{id:'chief',name:'Chief',persona:'Your teammate',color:'sage',projectId:null}],models:[],settings:{username:'',provider:'kilo',model:'',tools:[]},chrome:'custom',jobs:[],version:'0.0.0',contract:0};
          if(action==='loadThread'||action==='listProjects')return[];
          return[];}
      };
      createRoot(document.getElementById('root')).render(React.createElement(App));
    </script></body></html>`));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true });
  t.after(async () => { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await vite.close(); });
  const page = await browser.newPage({ viewport: { width: 1000, height: 768 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}${ROUTE}`);
  await page.getByRole('button', { name: 'Conversations', exact: true }).click();
  await page.locator('.chat-pane').waitFor();

  const portError = "Error invoking remote method 'engine:invoke': Error: listen EADDRINUSE: address already in use 127.0.0.1:50457";
  await page.evaluate(message => window.emitEvent({ type: 'error', threadId: null, message }), portError);
  const notice = page.locator('.notice-card');
  await notice.waitFor();
  assert.match(await notice.innerText(), /Ankita is already running/);
  assert.match(await notice.innerText(), /127\.0\.0\.1:50457/);
  assert.doesNotMatch(await notice.innerText(), /invoking remote method/);
  assert.equal(await page.locator('.error-toast').count(), 0);
  const compactHeight = (await notice.boundingBox()).height;
  assert.ok(compactHeight <= 80, `notice stays compact, measured ${compactHeight}px`);
  assert.equal(await page.locator('.notice-popover').count(), 0, 'details stay hidden until asked for');
  const details = page.getByRole('button', { name: 'Details', exact: true });
  assert.equal(await details.getAttribute('aria-expanded'), 'false');
  if (process.env.ANKITA_UI_CAPTURE_DIR) {
    fs.mkdirSync(process.env.ANKITA_UI_CAPTURE_DIR, { recursive: true });
    await page.screenshot({ path: path.join(process.env.ANKITA_UI_CAPTURE_DIR, 'chat-notice.png') });
  }
  await details.click();
  const popover = page.locator('.notice-popover');
  await popover.waitFor();
  assert.equal(await details.getAttribute('aria-expanded'), 'true');
  assert.equal(await popover.locator('code').textContent(), portError);
  assert.match(await popover.innerText(), /Close the other Ankita window/);
  assert.ok((await notice.boundingBox()).height <= 80, 'the anchored details popover does not enlarge the card');
  assert.ok((await popover.boundingBox()).width <= 340, 'details popover stays narrow');
  if (process.env.ANKITA_UI_CAPTURE_DIR) {
    await page.screenshot({ path: path.join(process.env.ANKITA_UI_CAPTURE_DIR, 'chat-notice-details.png') });
  }
  await page.keyboard.press('Escape');
  await popover.waitFor({ state: 'detached' });
  await page.getByRole('button', { name: 'Dismiss error' }).click();
  await notice.waitFor({ state: 'detached' });

  await page.evaluate(message => window.emitEvent({ type: 'error', threadId: null, message }), "Error invoking remote method 'engine:invoke': Error: kaboom while testing");
  await page.locator('.notice-card').filter({ hasText: 'Something went wrong' }).waitFor();
  assert.match(await page.locator('.notice-card').innerText(), /kaboom while testing/);

  await page.evaluate(() => window.emitEvent({ type: 'secret-notice', message: 'Saved securely on this device.' }));
  await page.locator('.notice-card').filter({ hasText: 'Secret protection' }).waitFor();
  assert.match(await page.locator('.notice-card.info').innerText(), /Saved securely on this device/);
  await page.getByRole('button', { name: 'Dismiss secret notice' }).click();
  await page.locator('.notice-card').filter({ hasText: 'Secret protection' }).waitFor({ state: 'detached' });
  assert.deepEqual(errors, []);
});
