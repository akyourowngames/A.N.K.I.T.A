import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';
import { DEFAULT_PERSONALITY } from '../../src/core/personality.mjs';
const ROOT = fileURLToPath(new URL('../../desktop/renderer/', import.meta.url));
const ROUTE = '/personality-ui'; // Local component preview; bridge fixtures never call an external model.
const TIMEOUT_MS = 8000; // Milliseconds: fail a missing editor promptly.
test('personality editor edits structured fields, saves, handles errors, resets drafts and fits small windows', async t => {
  assert.ok(fs.existsSync(path.join(ROOT, 'src/components/PersonalitySettings.tsx')), 'Personality editor is missing');
  const vite = await createServer({ configFile: false, root: ROOT, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  const server = http.createServer(async (req, res) => {
    if (req.url !== ROUTE) return vite.middlewares(req, res);
    res.setHeader('content-type', 'text/html');
    res.end(await vite.transformIndexHtml(ROUTE, `<!doctype html><html data-theme="graphite"><body class="desktop-workbench"><div class="settings-window"><aside class="settings-nav">Preferences</aside><main class="settings-main"><div class="settings-scroll"><div id="root"></div></div></main></div><script type="module">
      import React from 'react'; import { createRoot } from 'react-dom/client';
      import { PersonalitySettings } from '/src/components/PersonalitySettings.tsx';
      import '/src/styles.css'; import '/src/workbench.css';
      window.saved = null; window.failNext = false;
      window.ankita = { invoke: async (action, profile) => {
        if (action === 'personality:get') return {profile:${JSON.stringify(DEFAULT_PERSONALITY)}, notice:null};
        if (window.failNext) {window.failNext=false; throw new Error('Local save fixture failed');}
        window.saved=structuredClone(profile); return {profile, notice:null};
      }};
      createRoot(document.getElementById('root')).render(React.createElement(PersonalitySettings));
    </script></body></html>`));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true });
  t.after(async () => { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await vite.close(); });
  const page = await browser.newPage({ viewport: {width:1200,height:900} }); page.setDefaultTimeout(TIMEOUT_MS);
  const errors=[]; page.on('pageerror', error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}${ROUTE}`);
  await page.getByLabel('Character', {exact:true}).waitFor();
  const title = await page.getByRole('heading', {name:'Personality',exact:true}).boundingBox();
  const subtitle = await page.getByText('Give her a voice that feels familiar.',{exact:true}).boundingBox();
  assert.ok(subtitle.y >= title.y + title.height, 'Personality title and subtitle must not overlap');
  await page.getByLabel('Character', {exact:true}).fill('Caring and confident fixture character');
  await page.getByLabel('Attitude', {exact:true}).selectOption('gentle');
  await page.getByLabel('Teasing', {exact:true}).selectOption('off');
  await page.locator('summary').click();
  await page.getByLabel('Example reply 1', {exact:true}).fill('A changed example, not a fixed response.');
  await page.getByRole('button', {name:'Save personality',exact:true}).click();
  await page.getByRole('status').filter({hasText:'Personality saved'}).waitFor();
  const saved=await page.evaluate(()=>window.saved);
  assert.equal(saved.description,'Caring and confident fixture character');
  assert.equal(saved.attitude,'gentle'); assert.equal(saved.teasing,'off');
  assert.equal(saved.examples[0].assistant,'A changed example, not a fixed response.');
  await page.getByRole('button',{name:'Restore default',exact:true}).click();
  assert.equal(await page.getByLabel('Character',{exact:true}).inputValue(),DEFAULT_PERSONALITY.description);
  assert.equal(await page.evaluate(()=>window.saved.description),saved.description,'Restore only edits the draft until saved');
  await page.evaluate(()=>{window.failNext=true;});
  await page.getByRole('button',{name:'Save personality',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'Local save fixture failed'}).waitFor();
  assert.equal(await page.evaluate(()=>window.saved.description),saved.description);
  for(const width of [1200,620,390]) {
    await page.setViewportSize({width,height:900});
    assert.ok(await page.locator('.settings-scroll').evaluate(el=>el.scrollWidth<=el.clientWidth),'No horizontal overflow at '+width);
    await page.getByLabel('Character',{exact:true}).focus();
    assert.equal(await page.getByLabel('Character',{exact:true}).evaluate(el=>el===document.activeElement),true);
  }
  if(process.env.ANKITA_UI_CAPTURE_DIR) {
    fs.mkdirSync(process.env.ANKITA_UI_CAPTURE_DIR,{recursive:true});
    await page.setViewportSize({width:1200,height:900});
    await page.getByRole('button',{name:'Restore default',exact:true}).click();
    if(await page.locator('details').getAttribute('open') !== null) await page.locator('summary').click();
    await page.locator('.settings-scroll').evaluate(el=>el.scrollTop=0);
    await page.screenshot({path:path.join(process.env.ANKITA_UI_CAPTURE_DIR,'personality-settings.png')});
  }
  assert.deepEqual(errors,[]);
});
