import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';

const ROOT=fileURLToPath(new URL('../../desktop/renderer/',import.meta.url));
const ROUTE='/first-use-ui'; // Local full-chat preview; never a real account or profile.
test('chat keeps browser controls in Settings while preserving drafts and Stop across blocked replies',async t=>{
  const vite=await createServer({configFile:false,root:ROOT,server:{middlewareMode:true},appType:'custom'});
  const server=http.createServer(async(req,res)=>{
    if(req.url!==ROUTE)return vite.middlewares(req,res);
    res.setHeader('content-type','text/html');
    res.end(await vite.transformIndexHtml(ROUTE,`<!doctype html><html data-theme="graphite"><body class="desktop-workbench"><div id="root"></div><script type="module">
      import React,{useState} from 'react';import{createRoot}from'react-dom/client';
      import{ChatPane}from'/src/components/ChatPane.tsx';import'/src/styles.css';import'/src/workbench.css';
      let state={status:'ready',mode:'builtin',selectedModel:null,threadId:'fixture',recoverable:[],replying:false};
      const listeners=new Set();window.calls=[];
      const emit=()=>listeners.forEach(fn=>fn({type:'chatgpt-connection-changed',state:{...state}}));
      window.ankita={onEvent:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},invoke:async(action,payload)=>{
        window.calls.push({action,payload});
        if(action==='chatgptConnectionStart'){state={...state,mode:payload.mode,threadId:payload.threadId};emit();return{state};}
        if(action==='chatgptResumeReply'){state={...state,status:'ready',blockedReason:null,recoverable:[]};emit();return{imported:true};}
        if(action==='chatgptConnectionOverview')return state;
        return [];
      }};
      function Harness(){const[running,setRunning]=useState(false);window.showConnection=(next,working=false)=>{state=next;setRunning(working);emit();};return React.createElement(ChatPane,{
        teammate:{id:'fixture',name:'Research desk',persona:'Your teammate',color:'sage',projectId:null},messages:[],running,models:[],projects:[],defaultModel:'',provider:'chatgpt-browser',chrome:'custom',sidebarOpen:true,reviewOpen:false,jobs:[],commandsRevision:0,
        onToggleSidebar:()=>{},onToggleReview:()=>{},onOpenBrowser:()=>{},onProject:()=>{},onOpenProjects:()=>{},onSend:text=>window.calls.push({action:'send',text}),onStop:()=>window.calls.push({action:'stop'}),onModel:()=>{},onEdit:()=>{},onCreate:()=>{},onClear:()=>{},onDelete:()=>{},onEditJob:()=>{},onCommand:()=>{}
      });}
      createRoot(document.getElementById('root')).render(React.createElement(Harness));
    </script></body></html>`));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({headless:true});
  t.after(async()=>{await browser.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));await vite.close();});
  const page=await browser.newPage({viewport:{width:950,height:768}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}${ROUTE}`);
  const draft=page.getByRole('textbox',{name:'Message Research desk'});
  await draft.fill('Keep this draft while I check Settings');
  assert.equal(await page.getByRole('button',{name:'Use my Chrome',exact:true}).count(),0);
  assert.equal(await page.getByRole('button',{name:'Show ChatGPT',exact:true}).count(),0);
  assert.equal(await page.getByRole('button',{name:'Browser settings',exact:true}).count(),0);
  await page.evaluate(()=>window.showConnection({status:'ready',mode:'chrome',selectedModel:null,threadId:'fixture',recoverable:[{id:'lost-first-reply',outcome:'completed'}]}));
  await page.waitForFunction(()=>document.querySelector('button[aria-label="Send message"]')?.disabled===true);
  assert.equal(await page.getByRole('button',{name:'Send message',exact:true}).isDisabled(),true);
  await draft.press('Enter');
  assert.equal(await draft.inputValue(),'Keep this draft while I check Settings');
  assert.equal(await page.evaluate(()=>window.calls.filter(c=>c.action==='send').length),0);
  assert.match(await page.getByRole('button',{name:'Send message',exact:true}).getAttribute('title'),/Settings.*Providers/i);
  assert.equal(await page.getByRole('button',{name:'Read reply',exact:true}).count(),0);
  await page.evaluate(()=>window.showConnection({status:'blocked',mode:'chrome',selectedModel:null,threadId:'fixture',blockedReason:'transport',replying:true,recoverable:[]},true));
  await page.getByRole('button',{name:'Stop response',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Stop response',exact:true}).isEnabled(),true);
  await page.getByRole('button',{name:'Stop response',exact:true}).click();
  assert.equal(await page.evaluate(()=>window.calls.filter(c=>c.action==='stop').length),1);
  await page.evaluate(()=>window.showConnection({status:'ready',mode:'chrome',selectedModel:null,threadId:'other-owner',recoverable:[{id:'foreign-reply',outcome:'uncertain'}]}));
  await page.getByRole('button',{name:'Send message',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Send message',exact:true}).isDisabled(),true);
  assert.equal(await page.getByRole('region',{name:'ChatGPT connection'}).count(),0);
  await page.evaluate(()=>window.showConnection({status:'ready',mode:'chrome',selectedModel:null,threadId:'fixture',recoverable:[],replying:false}));
  await page.waitForFunction(()=>document.querySelector('button[aria-label="Send message"]')?.disabled===false);
  assert.equal(await draft.inputValue(),'Keep this draft while I check Settings');
  if(process.env.ANKITA_UI_CAPTURE_DIR){fs.mkdirSync(process.env.ANKITA_UI_CAPTURE_DIR,{recursive:true});await page.screenshot({path:path.join(process.env.ANKITA_UI_CAPTURE_DIR,'chat-settings-only.png')});}
  await page.getByRole('button',{name:'Send message',exact:true}).click();
  assert.equal(await page.evaluate(()=>window.calls.filter(c=>c.action==='send').length),1);
  await page.setViewportSize({width:650,height:650});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'connection controls fit the compact chat');
  assert.deepEqual(errors,[]);
});
