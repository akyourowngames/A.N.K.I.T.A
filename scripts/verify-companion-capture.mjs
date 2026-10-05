// Actual renderer readers, a real MV3 helper, and the production loopback bridge.
// All IPC/configuration/URLs here are isolated fixtures; no user drafts or tabs are touched.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { createServer } from 'vite';
import { CompanionCapture } from '../desktop/electron/companion-capture.mjs';
import { CAPTURE_ACTIONS, CAPTURE_EVENT, DRAG_MIME, MAX_ATTACHMENTS } from '../desktop/browser-helper/protocol.mjs';

const repo = fileURLToPath(new URL('../', import.meta.url));
const artifacts = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-mascot-capture-'));
const timeoutMs = 20_000; // Milliseconds; fixture browser readiness only.
const frameBudgetMs = 50; // Milliseconds; regression gate for long-history streaming commits on the fixture machine.
const receiptPollMs = 50; // Milliseconds; observe a real bridge receipt rather than an asynchronous page predicate.
const pageText = 'Exact rendered capture proof, including this signed-in-style document.';
const fixturePath = '/capture-fixture';
async function checkSwallowTarget(page) {
  const position=await page.evaluate(async()=>{
    const file=document.querySelector('.mascot-swallow-file');
    const animation=file.getAnimations()[0];animation.pause();animation.currentTime=Number(animation.effect.getTiming().duration)*.9;
    await new Promise(requestAnimationFrame);
    const f=file.getBoundingClientRect(),c=document.querySelector('.island-mascot-canvas').getBoundingClientRect();
    const position={x:f.x+f.width/2,y:f.y+f.height/2,mouthX:c.x+c.width/2,mouthY:c.y+c.height*.6};
    animation.currentTime=Number(animation.effect.getTiming().duration)*.25;animation.play();return position;
  });
  assert.ok(Math.abs(position.x-position.mouthX)<8 && Math.abs(position.y-position.mouthY)<8,'the shrinking file must land at the actual mascot mouth: '+JSON.stringify(position));
}
let renderer, mainRenderer, context;
const deliveries = [];
const bridge = new CompanionCapture({ configFile: path.join(artifacts, 'bridge.json'), threadExists: id => ['chief', 'research'].includes(id),
  onCapture: item => { deliveries.push(item); void (item.surface==='main'?mainRenderer:renderer)?.evaluate(({ type, capture }) => window.__emit({ type, capture }), {type: CAPTURE_EVENT, capture: item}); },
});
const fixturePages = (request, response, next) => {
  if (request.url === fixturePath) {
    response.setHeader('Content-Type', 'text/html');
    response.end(`<title>Capture fixture title</title><main><h1>Capture fixture title</h1><p>${pageText}</p><p hidden>HIDDEN_CAPTURE_SECRET</p><p style="display:none">CSS_HIDDEN_CAPTURE_SECRET</p><form><input value="PASSWORD_SHOULD_NOT_CAPTURE"></form><script>window.secret='SCRIPT_SHOULD_NOT_CAPTURE'</script></main>`);
  } else if (request.url === '/composer-fixture') {
    response.setHeader('Content-Type', 'text/html');
    const html = `<!doctype html><html><div id="root"></div><script type="module">import React,{useState} from 'react';import{createRoot}from'react-dom/client';import{Composer}from'/src/components/Composer.tsx';import{CompanionStatus}from'/src/components/CompanionStatus.tsx';import'/src/styles.css';function Fixture(){const[id,setId]=useState('chief');window.__choose=setId;const teammate={id,name:id,color:id==='chief'?'#60a5fa':'#a78bfa'};return React.createElement('div',null,React.createElement('div',{className:'chat-header'},React.createElement(CompanionStatus,{teammate,messages:[],running:false})),React.createElement(Composer,{threadId:id,name:id,messages:[],running:false,models:[],model:'',onModel:()=>{},onStop:()=>{},onSend:(text,attachments)=>window.__sent={id,text,attachments}}))}createRoot(document.getElementById('root')).render(React.createElement(Fixture));</script></html>`;
    void server.transformIndexHtml(request.url,html).then(html=>response.end(html));
  } else if (request.url === '/performance-fixture') {
    response.setHeader('Content-Type','text/html');
    const html = `<!doctype html><html><div id="root"></div><script type="module">import React,{useState,Profiler}from'react';import{createRoot}from'react-dom/client';import{Message}from'/src/components/Message.tsx';import'/src/styles.css';const teammate={id:'chief',name:'Chief',color:'#60a5fa'};const old=Array.from({length:24},(_,i)=>({id:'old-'+i,role:'assistant',content:('## Saved answer\\n\\nA saved paragraph containing useful context and **formatted text**.\\n\\n| Name | State |\\n| --- | --- |\\n| Test | Passed |\\n\\n').repeat(8)}));window.__commits=[];function Fixture(){const[text,setText]=useState('');window.__startPerf=async()=>{window.__commits=[];for(let i=0;i<30;i++){await new Promise(requestAnimationFrame);setText('Streaming '+i)}await new Promise(requestAnimationFrame);return window.__commits};return React.createElement(Profiler,{id:'transcript',onRender:(id,phase,duration)=>window.__commits.push(duration)},React.createElement('div',null,...old.map(message=>React.createElement(Message,{key:message.id,message,teammate,threadId:'chief',streaming:false})),React.createElement(Message,{key:'live',message:{id:'live',role:'assistant',content:text},teammate,threadId:'chief',streaming:true})))}createRoot(document.getElementById('root')).render(React.createElement(Fixture));</script></html>`;
    void server.transformIndexHtml(request.url,html).then(html=>response.end(html));
  } else next();
};
const server = await createServer({ configFile: path.join(repo, 'desktop/vite.config.ts'), plugins:[{name:'isolated-capture-fixtures',configureServer(vite){vite.middlewares.use(fixturePages);}}], server: {port: 0, strictPort: false} });
try {
  await bridge.start(); await server.listen();
  bridge.server.on('request', (request,response) => {response.on('finish',()=>console.log('Bridge fixture request: ' + JSON.stringify({method:request.method,route:request.url,origin:request.headers.origin,status:response.statusCode})));});
  const helper = path.join(repo, 'desktop/browser-helper');
  const options = { headless: true, channel: process.env.ANKITA_CAPTURE_BROWSER_CHANNEL || 'chromium', args: ['--disable-extensions-except=' + helper, '--load-extension=' + helper], viewport: {width: 960, height: 640} };
  // An explicit channel can exercise an installed Edge/Chrome; default is Playwright Chromium.
  context = await chromium.launchPersistentContext(path.join(artifacts, 'browser-profile'), options);
  context.setDefaultTimeout(timeoutMs);
  const worker = context.serviceWorkers()[0] || await context.waitForEvent('serviceworker');
  const extensionId = new URL(worker.url()).host;
  const popup = await context.newPage();
  await popup.goto('chrome-extension://' + extensionId + '/popup.html');
  await popup.getByLabel('ANKITA pairing code').fill(JSON.stringify(bridge.setup()));
  await popup.getByRole('button', {name: 'Pair with ANKITA', exact: true}).click();
  await popup.waitForFunction(() => document.querySelector('#status').textContent !== 'Pairing…');
  console.log('Helper pairing status: ' + await popup.locator('#status').textContent());
  await popup.getByText('Paired. Drag a teammate onto a webpage.', {exact:true}).waitFor();
  console.log('PASS real MV3 popup → service worker → one-use HTTP pairing');
  const url = server.resolvedUrls.local[0];
  renderer = await context.newPage();
  const errors = [];
  renderer.on('pageerror', error => errors.push(error.message));
  await renderer.exposeFunction('__invoke', async (action, payload) => {
    if (action === CAPTURE_ACTIONS.setup) return bridge.setup();
    if (action === CAPTURE_ACTIONS.register) return bridge.register({...payload, surface: 'island', sourceId: 'renderer'});
    if (action === CAPTURE_ACTIONS.cancel) return bridge.cancel(payload.ticketId, 'renderer');
    if (action === CAPTURE_ACTIONS.inbox) return bridge.inbox('island');
    if (action === CAPTURE_ACTIONS.ack) return bridge.ack(payload.id, 'island');
    return null;
  });
  await renderer.addInitScript(() => {
    const listeners = new Set();
    const teammates = [{id:'chief', name:'Chief', color:'#60a5fa'}, {id:'research', name:'Research', color:'#a78bfa'}];
    window.__emit = event => listeners.forEach(listener => listener(event));
    window.__sent = null;
    window.ankita = { onEvent: fn => {listeners.add(fn);return()=>listeners.delete(fn);}, onCursor:()=>()=>{}, islandAction:async()=>true,
      invoke:async(action,payload)=>{
        if(action==='islandSnapshot')return{teammates,threads:teammates.map(t=>({id:t.id,running:false,messages:[]}))};
        if(action==='scheduleList'||action==='approvalList')return[];
        if(action==='send'){window.__sent=payload;return{};}
        return window.__invoke(action,payload);
      }
    };
  });
  await renderer.goto(url + 'island.html');
  await renderer.getByRole('button', {name:'Open Ankita island',exact:true}).click();
  await renderer.getByLabel('Ask', {exact:true}).click();
  await renderer.getByLabel('Chat teammate').selectOption('research');
  await renderer.getByLabel('Message', {exact:true}).fill('Keep my research draft');
  await renderer.getByLabel('Overview', {exact:true}).click();
  await renderer.getByRole('button', {name:'Focus Research', exact:true}).click();
  await renderer.waitForFunction(() => document.querySelector('.island-mascot-name').textContent === 'Research');
  const payload = await renderer.evaluate(mime => {
    const transfer = new DataTransfer();
    document.querySelector('.island-mascot').dispatchEvent(new DragEvent('dragstart',{bubbles:true,cancelable:true,dataTransfer:transfer}));
    return transfer.getData(mime);
  }, DRAG_MIME);
  assert.ok(JSON.parse(payload).ticketId);
  assert.equal(payload.includes('token'), false);
  const page = await context.newPage(); await page.goto(url.replace(/\/$/,'') + fixturePath);
  await page.waitForFunction(() => Boolean(document.querySelector('main')));
  // The browser supplies a real content-script sender and service-worker network context.
  // The cross-app drag transfer itself is dispatched, because native CUA is unavailable.
  await page.evaluate(({mime,payload}) => {
    const transfer = new DataTransfer(); transfer.setData(mime,payload);
    document.body.dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:transfer}));
    document.body.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}));
  }, {mime:DRAG_MIME,payload});
  await renderer.waitForFunction(()=>document.querySelector('[data-home-view="prompt"]'),{},{timeout:timeoutMs}).catch(async error=>{console.log('Delivery diagnostic: '+JSON.stringify({deliveries,inbox:bridge.inbox('island'),body:await renderer.locator('body').innerText()}));throw error;});
  await renderer.getByRole('button', {name:'Remove Capture fixture title.txt',exact:true}).waitFor();
  assert.equal(deliveries.length,1);
  assert.equal(deliveries[0].threadId,'research');
  const captured = Buffer.from(deliveries[0].attachment.data,'base64').toString();
  assert.ok(captured.includes(pageText)); assert.ok(captured.includes(new URL(fixturePath,url).href));
  assert.equal(captured.includes('HIDDEN_CAPTURE_SECRET'),false);
  assert.equal(captured.includes('CSS_HIDDEN_CAPTURE_SECRET'),false);
  assert.equal(captured.includes('SCRIPT_SHOULD_NOT_CAPTURE'),false);
  assert.equal(captured.includes('PASSWORD_SHOULD_NOT_CAPTURE'),false);
  assert.equal(await renderer.getByLabel('Message',{exact:true}).inputValue(),'Keep my research draft');
  assert.equal(await renderer.evaluate(()=>window.__sent),null);
  console.log('PASS actual page drop listener → extension worker → bridge → original teammate attachment; existing draft preserved, no automatic send');
  await renderer.screenshot({path:path.join(artifacts,'captured-page.png')});
  const normal = await page.evaluate(() => {const d=new DataTransfer();d.setData('text/plain','ordinary');const e=new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:d});document.body.dispatchEvent(e);return e.defaultPrevented;});
  assert.equal(normal,false);
  console.log('PASS ordinary webpage drags remain unaffected');
  await renderer.bringToFront(); // RAF deliberately pauses on a hidden companion tab.
  // Delay only the fixture File reader so anticipation/swallow/reading can be sampled.
  await renderer.evaluate(() => {
    const original=File.prototype.arrayBuffer;
    File.prototype.arrayBuffer=function(){if(this.name==='delayed.md')return new Promise(resolve=>{window.__finishRead=()=>original.call(this).then(resolve);});return original.call(this);};
    const d=new DataTransfer();d.items.add(new File(['Real extracted file bytes'],'delayed.md',{type:'text/markdown'}));window.__fileTransfer=d;
    document.querySelector('.island').dispatchEvent(new DragEvent('dragenter',{bubbles:true,cancelable:true,dataTransfer:d}));
  });
  await renderer.locator('canvas[data-interaction="anticipate"]').waitFor();
  await renderer.screenshot({path:path.join(artifacts,'hungry-mouth.png')});
  await renderer.evaluate(()=>document.querySelector('.island').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:window.__fileTransfer})));
  await renderer.locator('canvas[data-interaction="gulp"]').waitFor();
  await renderer.locator('.mascot-swallow-file').waitFor();
  await checkSwallowTarget(renderer);
  await renderer.screenshot({path:path.join(artifacts,'swallow.png')});
  await renderer.locator('canvas[data-interaction="reading"]').waitFor();
  await renderer.getByLabel('Chat teammate').selectOption('chief');
  await renderer.getByLabel('Message',{exact:true}).fill('Chief draft stays here');
  await renderer.evaluate(()=>window.__finishRead());
  assert.equal(await renderer.getByRole('button',{name:'Remove delayed.md',exact:true}).count(),0);
  await renderer.getByLabel('Chat teammate').selectOption('research');
  await renderer.getByRole('button',{name:'Remove delayed.md',exact:true}).waitFor();
  assert.equal(await renderer.getByLabel('Message',{exact:true}).inputValue(),'Keep my research draft');
  await renderer.getByRole('button',{name:'Send',exact:true}).click();
  const sent=await renderer.evaluate(()=>window.__sent);
  assert.equal(sent.id,'research');
  assert.equal(Buffer.from(sent.attachments.find(file=>file.name==='delayed.md').data,'base64').toString(),'Real extracted file bytes');
  console.log('PASS live anticipation → swallow → real reading; changing teammates preserves original file bytes and both drafts');
  await renderer.locator('input[type="file"]').setInputFiles({name:'unsupported.bin',mimeType:'application/octet-stream',buffer:Buffer.from('bad')});
  await renderer.getByText('unsupported.bin is not a supported file type',{exact:true}).waitFor();
  await renderer.locator('canvas[data-interaction="error"]').waitFor();
  await renderer.screenshot({path:path.join(artifacts,'rejected-file.png')});
  await renderer.emulateMedia({reducedMotion:'reduce'});
  await renderer.locator('input[type="file"]').setInputFiles({name:'quiet.md',mimeType:'text/markdown',buffer:Buffer.from('Reduced motion file')});
  await renderer.getByRole('button',{name:'Remove quiet.md',exact:true}).waitFor();
  assert.equal(await renderer.locator('.mascot-swallow-file:visible').count(),0);
  console.log('PASS rejected files show real errors; reduced motion attaches without swallow motion');
  await renderer.locator('input[type="file"]').setInputFiles(Array.from({length:MAX_ATTACHMENTS-1},(_,index)=>({name:'slot-'+index+'.md',mimeType:'text/markdown',buffer:Buffer.from('Bounded attachment slot')})));
  await renderer.getByRole('button',{name:'Remove slot-'+(MAX_ATTACHMENTS-2)+'.md',exact:true}).waitFor();
  const held=bridge.register({ticketId:crypto.randomUUID(),threadId:'research',surface:'island',sourceId:'held-fixture'});
  await page.evaluate(({mime,payload})=>{const transfer=new DataTransfer();transfer.setData(mime,payload);document.body.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}));},{mime:DRAG_MIME,payload:JSON.stringify(held)});
  await renderer.getByText(/Remove one to receive the captured page/).waitFor();
  assert.equal(bridge.inbox('island').length,1);
  await renderer.getByRole('button',{name:'Remove quiet.md',exact:true}).click();
  await renderer.getByRole('button',{name:'Remove Capture fixture title.txt',exact:true}).waitFor();
  await renderer.waitForFunction(()=>document.querySelectorAll('.island-file-chip').length===8);
  assert.equal(bridge.inbox('island').length,0);
  console.log('PASS a full draft holds capture once and automatically receives it after a slot is freed');
  assert.deepEqual(errors,[]);
  mainRenderer=await context.newPage();
  mainRenderer.on('pageerror',error=>errors.push(error.message));
  await mainRenderer.exposeFunction('__invoke',async(action,payload)=>{
    if(action===CAPTURE_ACTIONS.setup)return bridge.setup();
    if(action===CAPTURE_ACTIONS.inbox)return bridge.inbox('main');
    if(action===CAPTURE_ACTIONS.ack)return bridge.ack(payload.id,'main');
    return true;
  });
  await mainRenderer.addInitScript(()=>{
    const listeners=new Set();window.__emit=event=>listeners.forEach(fn=>fn(event));
    window.ankita={invoke:(...args)=>window.__invoke(...args),onEvent:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},onCursor:()=>()=>{},openExternal:async()=>{}};
    const original=File.prototype.arrayBuffer;
    File.prototype.arrayBuffer=function(){if(this.name==='main-delayed.md')return new Promise(resolve=>{window.__finishMainRead=()=>original.call(this).then(resolve);});return original.call(this);};
  });
  await mainRenderer.goto(url+'composer-fixture');
  await mainRenderer.bringToFront();
  await mainRenderer.getByLabel('Message chief',{exact:true}).fill('Preserve desktop Chief draft');
  await mainRenderer.evaluate(()=>{const d=new DataTransfer();d.items.add(new File(['Desktop extracted context'],'main-delayed.md',{type:'text/markdown'}));window.__mainTransfer=d;document.querySelector('.header-companion').dispatchEvent(new DragEvent('dragenter',{bubbles:true,cancelable:true,dataTransfer:d}));});
  await mainRenderer.locator('canvas[data-interaction="anticipate"]').waitFor();
  await mainRenderer.evaluate(()=>document.querySelector('.header-companion').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:window.__mainTransfer})));
  await mainRenderer.locator('canvas[data-interaction="gulp"]').waitFor();
  await checkSwallowTarget(mainRenderer);
  await mainRenderer.locator('canvas[data-interaction="reading"]').waitFor();
  await mainRenderer.evaluate(()=>window.__choose('research'));
  await mainRenderer.getByLabel('Message research',{exact:true}).fill('Preserve desktop Research draft');
  await mainRenderer.evaluate(()=>window.__finishMainRead());
  assert.equal(await mainRenderer.getByRole('button',{name:'Remove main-delayed.md',exact:true}).count(),0);
  await mainRenderer.evaluate(()=>window.__choose('chief'));
  await mainRenderer.getByRole('button',{name:'Remove main-delayed.md',exact:true}).waitFor();
  assert.equal(await mainRenderer.getByLabel('Message chief',{exact:true}).inputValue(),'Preserve desktop Chief draft');
  await mainRenderer.getByRole('button',{name:'Send message',exact:true}).click();
  const mainSent=await mainRenderer.evaluate(()=>window.__sent);
  assert.equal(mainSent.id,'chief');assert.equal(Buffer.from(mainSent.attachments[0].data,'base64').toString(),'Desktop extracted context');
  console.log('PASS desktop header mouth → actual Composer reader → pinned attachment bytes; both desktop teammate drafts survive switching');
  await mainRenderer.evaluate(()=>document.querySelector('.header-companion').dispatchEvent(new DragEvent('dragenter',{bubbles:true,cancelable:true,dataTransfer:window.__mainTransfer})));
  await mainRenderer.locator('canvas[data-interaction="anticipate"]').waitFor();
  await mainRenderer.evaluate(()=>document.querySelector('.header-companion').dispatchEvent(new DragEvent('dragleave',{bubbles:true,cancelable:true,dataTransfer:window.__mainTransfer})));
  await mainRenderer.locator('canvas[data-interaction="rest"]').waitFor();
  console.log('PASS leaving a file drop target cancels the hungry pose');
  await mainRenderer.screenshot({path:path.join(artifacts,'desktop-file.png')});
  assert.deepEqual(errors,[]);
  const performancePage=await context.newPage();
  await performancePage.goto(url+'performance-fixture');
  await performancePage.bringToFront();
  await performancePage.waitForFunction(()=>typeof window.__startPerf==='function');
    const commits=await performancePage.evaluate(()=>window.__startPerf());
  const sorted=commits.slice().sort((a,b)=>a-b);
  const metric={commits:commits.length,meanMs:commits.reduce((a,b)=>a+b,0)/commits.length,p95Ms:sorted[Math.floor(sorted.length*.95)]};
  await fs.writeFile(path.join(artifacts,'renderer-performance.json'),JSON.stringify(metric,null,2));
  console.log('Renderer transcript profile: '+JSON.stringify(metric));
  assert.ok(metric.p95Ms<Number(process.env.ANKITA_CAPTURE_PERF_GATE || frameBudgetMs),'saved transcript Markdown must not be re-parsed on every streaming token');
  // Close and reopen the actual browser profile: its worker and page scripts are
  // recreated, while only extension storage retains the per-helper credentials.
  await context.close(); renderer=null;mainRenderer=null;
  context=await chromium.launchPersistentContext(path.join(artifacts,'browser-profile'),options);
  context.setDefaultTimeout(timeoutMs);
  const restarted=await context.newPage();await restarted.goto(new URL(fixturePath,url).href);
  const restartTicket=bridge.register({ticketId:crypto.randomUUID(),threadId:'chief',surface:'island',sourceId:'restart-fixture'});
  await restarted.evaluate(({mime,payload})=>{const d=new DataTransfer();d.setData(mime,payload);window.__restartTransfer=d;},{mime:DRAG_MIME,payload:JSON.stringify(restartTicket)});
  await restarted.waitForFunction(()=>{document.body.dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:window.__restartTransfer}));return Boolean(document.querySelector('#ankita-mascot-capture-target'));});
  await restarted.evaluate(()=>document.body.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:window.__restartTransfer})));
  const receiptDeadline=performance.now()+timeoutMs;
  while (!bridge.inbox('island').length && performance.now()<receiptDeadline) await new Promise(resolve=>setTimeout(resolve,receiptPollMs));
  assert.equal(bridge.inbox('island').length,1,'the restarted helper must actually deliver a receipt');
  const restartedCapture=bridge.inbox('island')[0];assert.equal(restartedCapture.threadId,'chief');
  assert.match(Buffer.from(restartedCapture.attachment.data,'base64').toString(),/Exact rendered capture proof/);
  bridge.ack(restartedCapture.id,'island');
  console.log('PASS browser/service-worker restart restores pairing from extension storage without a new pairing code');
  console.log('Capture evidence: '+artifacts);
} catch (error) {
  console.log('Renderer diagnostic: '+ await renderer?.locator('body').innerText());
  if(renderer) await renderer.screenshot({path:path.join(artifacts,'failure.png')});
  console.log('Failure evidence: '+artifacts);
  throw error;
} finally {
  await context?.close(); await bridge.close(); await server.close();
}
