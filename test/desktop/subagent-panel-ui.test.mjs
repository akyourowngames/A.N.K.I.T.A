import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { createServer } from 'vite';
import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('../../desktop/renderer/', import.meta.url));
const ROUTE = '/subagent-panel-ui'; // Local preview with a stubbed desktop bridge; no real process or provider.
const NOW = Date.now();
const DESCRIPTION = 'Research PHP5Shell vulnerability details';

const RECEIPT = {
  subagentId: 'child-earlier', parentCallId: 'call-delegate', subagentType: 'explore', description: DESCRIPTION,
  status: 'completed', summary: 'Earlier run summary.', toolsUsed: ['read_file'],
  usage: { prompt_tokens: 10, completion_tokens: 5 }, durationMs: 900, transcript: 'C:/sessions/subagent-child-earlier.json', depth: 1,
};

const MESSAGES = [
  { id: 'u1', role: 'user', content: 'Look into this exploit' },
  { id: 'call-delegate', role: 'tool', callId: 'call-delegate', name: 'delegate_task', args: { subagent_type: 'explore', description: DESCRIPTION }, result: JSON.stringify(RECEIPT), isError: false, startedAt: NOW - 10, endedAt: NOW - 5 },
  { id: 'a1', role: 'assistant', content: 'The researcher is on it.' },
];

const event = (type, extra) => ({ type, threadId: 'chief', ...extra });

test('a launched sub-agent opens the side panel, narrows chat and streams live work', async t => {
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
          if(action==='workspaceSnapshot')return{cwd:'C:/repo',files:[],artifacts:[],jobs:[]};
          return[];}
      };
      createRoot(document.getElementById('root')).render(React.createElement(App));
    </script></body></html>`));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true });
  t.after(async () => { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await vite.close(); });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const capture = async name => {
    if (!process.env.ANKITA_UI_CAPTURE_DIR) return;
    fs.mkdirSync(process.env.ANKITA_UI_CAPTURE_DIR, { recursive: true });
    await page.screenshot({ path: path.join(process.env.ANKITA_UI_CAPTURE_DIR, name) });
  };
  const chatWidth = async () => (await page.locator('.chat-pane').boundingBox()).width;

  await page.goto(`http://127.0.0.1:${server.address().port}${ROUTE}`);
  await page.locator('.teammate-row').filter({ hasText: 'Chief' }).click();
  await page.locator('.subagent-card').waitFor();

  // History stays inline: the panel opens for new work, not for old receipts.
  assert.equal(await page.locator('.subagent-panel.is-open').count(), 0);
  assert.equal(await page.locator('.app-shell.subagent-visible').count(), 0);
  assert.match(await page.locator('.subagent-open-panel').innerText(), /Open in side panel/);
  const wide = await chatWidth();

  await page.evaluate(start => window.emitEvent(start), event('subagent-start', {
    subagentId: 'child-live', parentCallId: 'call-delegate', subagentType: 'explore', description: DESCRIPTION,
    prompt: 'Read the exploit notes and report the injection point.', depth: 1,
  }));
  await page.locator('.subagent-panel.is-open').waitFor();
  assert.equal(await page.locator('.app-shell.subagent-visible').count(), 1);
  assert.match(await page.locator('.subagent-panel-heading').innerText(), /Research PHP5Shell vulnerability details/);
  assert.match(await page.locator('.subagent-panel-state').innerText(), /Working/);
  assert.equal(await page.locator('.subagent-panel-state .tool-spinner').count(), 1);
  assert.match(await page.locator('.subagent-panel-waiting').innerText(), /Waiting for the first output/);
  // The panel owns the live run, so the chat no longer duplicates the card.
  assert.equal(await page.locator('.subagent-card').count(), 0);

  // The chat gives the side panel its width while the child works.
  await page.waitForTimeout(400);
  const narrow = await chatWidth();
  assert.ok(narrow < wide - 200, `chat should narrow from ${wide}px, got ${narrow}px`);
  assert.match(await page.locator('.subagent-toggle').innerText(), /1 agent working/);

  await page.evaluate(delta => window.emitEvent(delta), event('subagent-delta', { subagentId: 'child-live', parentCallId: 'call-delegate', text: 'Reading the exploit notes…' }));
  await page.locator('.subagent-panel-output').filter({ hasText: 'Reading the exploit notes' }).waitFor();
  await page.evaluate(call => window.emitEvent(call), event('subagent-tool-call', {
    subagentId: 'child-live', parentCallId: 'call-delegate',
    call: { id: 'tool-live', function: { name: 'read_file', arguments: '{"path":"exploit.md"}' } },
  }));
  await page.evaluate(result => window.emitEvent(result), event('subagent-tool-result', {
    subagentId: 'child-live', parentCallId: 'call-delegate',
    call: { id: 'tool-live', function: { name: 'read_file' } }, result: 'injection notes',
  }));
  const tool = page.locator('.subagent-panel .subagent-tools li').filter({ hasText: 'Read file' });
  await tool.waitFor();
  assert.equal(await tool.locator('em').innerText(), 'Done');

  // Repeated reads fold into one row, and long prose keeps a readable measure.
  await page.evaluate(delta => window.emitEvent(delta), event('subagent-delta', {
    subagentId: 'child-live', parentCallId: 'call-delegate',
    text: ' I scanned the advisory, the vendor note and three independent write-ups. The injection point sits in the query parser, so the exploit only needs a crafted selector. Patching the parser is enough; the caller does not need to change.',
  }));
  for (let index = 0; index < 6; index++) {
    const id = `page-${index}`;
    await page.evaluate(call => window.emitEvent(call), event('subagent-tool-call', {
      subagentId: 'child-live', parentCallId: 'call-delegate',
      call: { id, function: { name: 'web_fetch', arguments: JSON.stringify({ url: `https://www.example.com/report-${index}` }) } },
    }));
    await page.evaluate(result => window.emitEvent(result), event('subagent-tool-result', {
      subagentId: 'child-live', parentCallId: 'call-delegate',
      call: { id, function: { name: 'web_fetch' } }, result: 'ok',
    }));
  }
  const group = page.locator('.subagent-panel .subagent-tool-group');
  await group.waitFor();
  assert.match(await page.locator('.subagent-tool-group-head').innerText(), /Read a page[\s\S]*6 calls[\s\S]*Done/);
  assert.equal(await page.locator('.subagent-tool-rows .subagent-tool-row').count(), 0, 'long runs start folded');
  const outputType = await page.locator('.subagent-panel-output').evaluate(element => {
    const style = getComputedStyle(element);
    return { size: parseFloat(style.fontSize), line: parseFloat(style.lineHeight) };
  });
  assert.ok(outputType.line / outputType.size >= 1.6, `output line-height should clear 1.6, got ${outputType.line}/${outputType.size}`);
  await group.locator('.subagent-tool-group-head').click();
  assert.equal(await page.locator('.subagent-tool-rows .subagent-tool-row').count(), 6);
  assert.match(await page.locator('.subagent-tool-rows .subagent-tool-row small').first().innerText(), /example\.com/);
  await page.locator('.subagent-tool-group-head').click();

  // A second child joins the run without stealing the child being watched.
  await page.evaluate(start => window.emitEvent(start), event('subagent-start', {
    subagentId: 'child-review', parentCallId: 'call-review', subagentType: 'reviewer', description: 'Review the patch', prompt: 'Review it.', depth: 1,
  }));
  await page.locator('.subagent-panel-switcher button').nth(1).waitFor();
  assert.equal(await page.locator('.subagent-panel-switcher button').count(), 2);
  assert.match(await page.locator('.subagent-panel-switcher button.active').innerText(), /Research PHP5Shell/);

  // Completion settles the panel in place and keeps the output readable.
  await page.evaluate(end => window.emitEvent(end), event('subagent-end', {
    subagentId: 'child-live', parentCallId: 'call-delegate', status: 'completed',
    summary: 'The injection point is in the query parser.', usage: { prompt_tokens: 40, completion_tokens: 20 },
    durationMs: 1400, transcript: 'C:/sessions/subagent-child-live.json', toolsUsed: ['read_file'],
  }));
  await page.locator('.subagent-panel-status.ok').waitFor();
  assert.equal(await page.locator('.subagent-panel-state .tool-spinner').count(), 0);
  assert.match(await page.locator('.subagent-panel-state').innerText(), /Done/);
  assert.match(await page.locator('.subagent-panel-output').innerText(), /Reading the exploit notes/);
  assert.match(await page.locator('.subagent-panel-summary').innerText(), /query parser/);
  assert.match(await page.locator('.subagent-toggle').innerText(), /1 agent working/);
  await page.locator('.subagent-panel-scroll').evaluate(element => { element.scrollTop = 0; });
  await capture('subagent-panel-live.png');

  // Closing gives the chat its width back; nothing re-opens on its own.
  await page.locator('.subagent-panel-top .icon-button').click();
  assert.equal(await page.locator('.subagent-panel.is-open').count(), 0);
  assert.equal(await page.locator('.app-shell.subagent-visible').count(), 0);
  await page.waitForTimeout(400);
  const restored = await chatWidth();
  assert.ok(restored > narrow, `chat should widen from ${narrow}px, got ${restored}px`);
  assert.equal(await page.locator('.subagent-card').count(), 1);
  assert.match(await page.locator('.subagent-open-panel').innerText(), /Open in side panel/);
  await capture('subagent-card-inline.png');

  // The context chip reopens on the still-working child; the rail switches runs.
  await page.locator('.subagent-toggle').click();
  await page.locator('.subagent-panel.is-open').waitFor();
  assert.match(await page.locator('.subagent-panel-heading').innerText(), /Review the patch/);
  await page.locator('.subagent-panel-switcher button').filter({ hasText: DESCRIPTION }).click();
  assert.match(await page.locator('.subagent-panel-heading').innerText(), /Research PHP5Shell vulnerability details/);

  // The inline card can also pull a run back into the panel.
  await page.locator('.subagent-panel-top .icon-button').click();
  await page.locator('.subagent-open-panel').click();
  await page.locator('.subagent-panel.is-open').waitFor();
  assert.match(await page.locator('.subagent-panel-heading').innerText(), /Research PHP5Shell vulnerability details/);
  assert.equal(await page.locator('.subagent-card').count(), 0);

  // Below 1200px the panel overlays the chat instead of squeezing it further.
  await page.setViewportSize({ width: 1100, height: 800 });
  assert.equal(await page.locator('.subagent-panel').evaluate(element => getComputedStyle(element).position), 'fixed');
  await page.setViewportSize({ width: 1400, height: 900 });

  await page.evaluate(end => window.emitEvent(end), event('subagent-end', {
    subagentId: 'child-review', parentCallId: 'call-review', status: 'cancelled', summary: 'Stopped.',
  }));
  await page.waitForFunction(() => document.querySelector('.subagent-toggle')?.textContent?.includes('2 sub-agents'));
  assert.equal(await page.locator('.subagent-panel-state .tool-spinner').count(), 0);
  await capture('subagent-panel-done.png');

  // Closing the panel restores the transcript anchors.
  await page.locator('.subagent-panel-top .icon-button').click();
  await page.locator('.subagent-card').waitFor();
  assert.match(await page.locator('.subagent-open-panel').innerText(), /Open in side panel/);

  assert.deepEqual(errors, []);
});
