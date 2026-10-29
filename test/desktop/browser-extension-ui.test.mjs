import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';

const ROOT = fileURLToPath(new URL('../../desktop/renderer/', import.meta.url));
const ROUTE = '/browser-extension-ui';
test('browser setup exposes one-time pairing and pause/revoke controls without overflowing narrow windows', async t => {
  const vite = await createServer({ configFile: false, root: ROOT, server: { middlewareMode: true }, appType: 'custom' });
  const server = http.createServer(async (req, res) => {
    if (req.url !== ROUTE) return vite.middlewares(req, res);
    res.setHeader('Content-Type', 'text/html');
    res.end(await vite.transformIndexHtml(ROUTE, `<!doctype html><html data-theme="graphite"><body><main style="max-width:480px;padding:16px;box-sizing:border-box"><div id="root"></div></main><script type="module">
      import React from 'react';import{createRoot}from'react-dom/client';import{ExtensionBrowserSetup}from'/src/components/ExtensionBrowserSetup.tsx';import'/src/styles.css';
      let state={paired:false,connected:false,paused:false};window.calls=[];
      window.setConnection=next=>{state=next;};
      window.ankita={invoke:async action=>{window.calls.push(action);if(action==='browserExtensionStatus')return state;if(action==='browserExtensionSetup')return{address:'http://127.0.0.1:49152',code:'fixture-one-use-code',control:true};if(action==='browserExtensionDisconnect')state={paired:true,connected:false,paused:true};if(action==='browserExtensionResume')state={paired:true,connected:true,paused:false};if(action==='browserExtensionRevoke')state={paired:false,connected:false,paused:false};return state;}};
      createRoot(document.getElementById('root')).render(React.createElement(ExtensionBrowserSetup));
    </script></body></html>`));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true });
  t.after(async () => { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await vite.close(); });
  const page = await browser.newPage(), errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}${ROUTE}`);
  await page.getByText('Pair your browser once', { exact: true }).waitFor();
  assert.equal(await page.evaluate(() => window.calls.includes('browserExtensionSetup')), false, 'passive status never generates a pairing code');
  await page.getByRole('button', { name: 'Create setup code' }).click();
  const code = page.getByRole('textbox', { name: 'One-time setup code' }); await code.waitFor();
  assert.match(await code.inputValue(), /fixture-one-use-code/);
  for (const width of [1280, 620, 390]) {
    await page.setViewportSize({ width, height: 800 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `no horizontal overflow at ${width}`);
    const box = await code.boundingBox(); assert.ok(box.x >= 0 && box.x + box.width <= width);
  }
  await page.evaluate(() => window.setConnection({ paired: true, connected: true, paused: false }));
  await page.getByText('Connected to your browser', { exact: true }).waitFor();
  assert.equal(await code.count(), 0, 'the setup code disappears after pairing');
  await page.getByRole('button', { name: 'Disconnect', exact: true }).click();
  await page.getByText('Connection paused', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Reconnect', exact: true }).click();
  await page.getByText('Connected to your browser', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Unpair browser', exact: true }).click();
  await page.getByText('Pair your browser once', { exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log('BROWSER_SETUP_UI_OK: 1280/620/390; explicit setup only; private code cleared; pause/resume/revoke; zero renderer errors.');
});
