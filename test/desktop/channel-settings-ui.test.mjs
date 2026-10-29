import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';
import { defaultRegistry, ChannelRegistry } from '../../src/channels/core/registry.mjs';
import { commonFields } from '../../src/channels/manifests/common.mjs';

const ROOT = fileURLToPath(new URL('../../desktop/renderer/', import.meta.url));
const ROUTE = '/channel-settings-fixture';
test('manifest-generated channel setup preserves drafts, keeps keys private and fits desktop and narrow windows', async t => {
  const registry = new ChannelRegistry([...defaultRegistry.list(), { id: 'fixture', label: 'Fixture messenger', description: 'A newly registered private connection.', connect: 'socket', capabilities: ['upload'], docsUrl: 'https://example.test/setup', required: ['secret'], fields: { ...commonFields, secret: { kind: 'secret', label: 'Connection key', default: '', section: 'connection' } } }]);
  const view = { channels: Object.fromEntries(registry.list().map(manifest => [manifest.id, registry.publicView(manifest.id, { ...registry.defaults(manifest.id), teammateId: 'chief', ...(manifest.id === 'fixture' ? { secret: 'server-only-private-key' } : {}) })])) };
  const vite = await createServer({ configFile: false, root: ROOT, server: { middlewareMode: true }, appType: 'custom' });
  const server = http.createServer(async (request, response) => {
    if (request.url !== ROUTE) return vite.middlewares(request, response);
    response.setHeader('Content-Type', 'text/html');
    response.end(await vite.transformIndexHtml(ROUTE, `<!doctype html><html data-theme="graphite"><body><main class="desktop-workbench"><div id="root"></div></main><script type="module">
      import React from 'react';import{createRoot}from'react-dom/client';import{ChannelsSettings}from'/src/components/ChannelsSettings.tsx';import'/src/styles.css';import'/src/workbench.css';
      let view=${JSON.stringify(view)};window.calls=[];let listener=()=>{};
      window.updateChannelStatus=()=>listener({type:'channels-updated',channels:view});
      window.ankita={onEvent:fn=>{listener=fn;return()=>{};},openExternal:async()=>{},invoke:async(action,payload)=>{
        window.calls.push({action,payload});if(action==='getChannels')return view;
        if(action==='testChannel')return{account:'verified fixture'};
        if(action==='saveChannelSettings'){let current=view.channels[payload.channel];for(const[key,value]of Object.entries(payload.patch)){if(current.manifest.fields[key].kind==='secret')current.secrets[key]=!!value;else current[key]=value;}return structuredClone(view);}
        return view;
      }};
      createRoot(document.getElementById('root')).render(React.createElement(ChannelsSettings,{teammates:[{id:'chief',name:'Chief'}]}));
    </script></body></html>`));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true });
  t.after(async () => { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await vite.close(); });
  const page = await browser.newPage(), errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}${ROUTE}`);
  await page.getByRole('tab', { name: /Fixture messenger/ }).click({ timeout: 5000 });
  const key = page.getByLabel('Connection key', { exact: true });
  assert.equal(await key.inputValue(), '');
  assert.equal(await page.locator('body').innerText().then(text => text.includes('server-only-private-key')), false);
  await key.fill('new-fixture-key');
  await page.evaluate(() => window.updateChannelStatus());
  assert.equal(await key.inputValue(), 'new-fixture-key', 'status updates must not erase unsaved credentials');
  await page.getByRole('button', { name: 'Test connection', exact: true }).click();
  await page.getByText('Connected as verified fixture', { exact: true }).waitFor();
  const verify = await page.evaluate(() => window.calls.find(item => item.action === 'testChannel'));
  assert.equal(verify.payload.channel, 'fixture'); assert.equal(verify.payload.input.secret, 'new-fixture-key');
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await page.getByText('Changes saved.', { exact: true }).waitFor(); assert.equal(await key.inputValue(), '');
  const saved = await page.evaluate(() => window.calls.find(item => item.action === 'saveChannelSettings'));
  assert.deepEqual(saved.payload.patch, { secret: 'new-fixture-key' });
  for (const width of [1280, 620, 390]) {
    await page.setViewportSize({ width, height: 900 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `no overflow at ${width}`);
  }
  await page.getByRole('tab', { name: /Telegram/ }).focus(); await page.keyboard.press('End');
  assert.equal(await page.getByRole('tab', { name: /Fixture messenger/ }).getAttribute('aria-selected'), 'true');
  assert.deepEqual(errors, []);
  console.log('CHANNEL_SETTINGS_UI_OK: generated card; secret-safe edits; drafts survive status; save/test; keyboard; 1280/620/390; zero renderer errors.');
});
