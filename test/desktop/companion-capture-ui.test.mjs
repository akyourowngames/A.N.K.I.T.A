import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { createServer } from 'vite';
import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('../../desktop/renderer/', import.meta.url));
const ROUTE = '/capture-ui'; // Local preview with a stubbed desktop bridge; no real process or provider.

test('a busy capture bridge never leaks raw IPC text into passive mascot surfaces', async t => {
  const vite = await createServer({ configFile: false, root: ROOT, define: { __ANKITA_VERSION__: JSON.stringify('0.0.0-test') }, server: { middlewareMode: true }, appType: 'custom' });
  const server = http.createServer(async (req, res) => {
    if (req.url !== ROUTE) return vite.middlewares(req, res);
    res.setHeader('content-type', 'text/html');
    res.end(await vite.transformIndexHtml(ROUTE, `<!doctype html><html data-theme="graphite"><body class="desktop-workbench"><div id="root"></div><script type="module">
      import React from 'react';import{createRoot}from'react-dom/client';import App from '/src/App.tsx';
      import '/src/styles.css';import '/src/workbench.css';
      const portError="Error invoking remote method 'engine:invoke': Error: listen EADDRINUSE: address already in use 127.0.0.1:50457";
      const human={unavailable:{title:'Ankita is already running',detail:'The helper bridge belongs to another Ankita process (127.0.0.1:50457).',hint:'Quit the other window, then try again.'}};
      const listeners=new Set();let mode='reject';
      window.setCaptureMode=value=>{mode=value;};
      window.calls=[];
      window.ankita={
        onEvent:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},
        onMenuCommand:()=>()=>{},onUpdateEvent:()=>()=>{},
        invoke:async(action,payload)=>{window.calls.push({action,payload});
          if(action==='initialize')return{teammates:[{id:'chief',name:'Chief',persona:'Your teammate',color:'sage',projectId:null}],models:[],settings:{username:'',provider:'kilo',model:'',tools:[]},chrome:'custom',jobs:[],version:'0.0.0-test',contract:7};
          if(action==='loadThread'||action==='listProjects')return[];
          if(action==='companionCaptureSetup'){if(mode==='reject')throw new Error(portError);if(mode==='unavailable')return human;return{address:'http://127.0.0.1:50457',code:'pair-code',instanceId:'instance',paired:0};}
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
  assert.equal(await page.locator('.conversation-state').count(), 0, 'no status tag in the conversation header');
  assert.equal(await page.locator('.companion-helper-toggle').count(), 0, 'no helper badge on the mascot');
  const composer = page.locator('.composer-shell textarea');
  await composer.focus();
  assert.equal(await composer.evaluate(element => getComputedStyle(element).outlineStyle), 'none', 'the shell border is the only focus frame');
  const mascot = page.locator('.header-companion');
  const setups = () => page.evaluate(() => window.calls.filter(call => call.action === 'companionCaptureSetup').length);
  const started = await setups();
  await mascot.hover();
  await page.waitForFunction(count => window.calls.filter(call => call.action === 'companionCaptureSetup').length > count, started);
  assert.equal(await page.locator('.companion-capture-toast').count(), 0, 'hover stays silent when the bridge is busy');
  assert.doesNotMatch(await mascot.getAttribute('title'), /EADDRINUSE|invoking remote method/i);

  await page.getByRole('button', { name: 'Conversation options' }).click();
  await page.getByRole('button', { name: 'Browser helper' }).click();
  await page.locator('.helper-dialog').waitFor();
  const setup = page.locator('.companion-helper-setup');
  await setup.waitFor();
  await setup.getByRole('button', { name: 'Copy pairing code' }).click();
  await setup.locator('[role="status"]').filter({ hasText: 'Another Ankita process' }).waitFor();
  const rejected = await setup.locator('[role="status"]').innerText();
  assert.match(rejected, /Ankita is already running/);
  assert.match(rejected, /Close the other Ankita window/);
  assert.doesNotMatch(rejected, /invoking remote method|EADDRINUSE/i);

  await page.evaluate(() => window.setCaptureMode('unavailable'));
  await setup.getByRole('button', { name: 'Copy pairing code' }).click();
  await setup.locator('[role="status"]').filter({ hasText: 'belongs to another Ankita process' }).waitFor();
  assert.match(await setup.locator('[role="status"]').innerText(), /Quit the other window/);
  assert.equal(await setup.getByLabel('Browser pairing code').count(), 0, 'no code is offered while the bridge is owned elsewhere');
  if (process.env.ANKITA_UI_CAPTURE_DIR) {
    fs.mkdirSync(process.env.ANKITA_UI_CAPTURE_DIR, { recursive: true });
    await page.screenshot({ path: path.join(process.env.ANKITA_UI_CAPTURE_DIR, 'companion-helper-unavailable.png') });
  }
  assert.deepEqual(errors, []);
});
