import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { AssistantTaskStore } from '../../src/assistant/tasks.mjs';

const WAIT_MS = 20000; // Milliseconds: bound process contention acceptance, without a network service.
const WORKERS = 4; // Separate processes contend over one task, not independent records.
const WRITES = 12; // Per process; total stays below the journal receipt limit.
const LEGACY_LOCK = '.write.lock'; // Older lock protocol must fail closed instead of deleting an unowned replacement.

test('legacy lock reclamation never unlinks a replacement owner lock', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'assistant-lock-'));
  try {
    const store = new AssistantTaskStore({ directory, isProcessAlive: () => false });
    const task = store.create({ ownerId: 'one', goal: 'Keep this receipt safe.' }), lock = path.join(directory, task.id, LEGACY_LOCK);
    const token = JSON.stringify({ pid: process.pid, nonce: 'another-writer' }); fs.writeFileSync(lock, token);
    assert.throws(() => store.start(task.id), /lock|busy|review/i);
    assert.equal(fs.readFileSync(lock, 'utf8'), token);
  } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});

test('independent processes keep every receipt when committing to the same record', { timeout: WAIT_MS }, async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'assistant-contention-')), children = [];
  t.after(async () => { for (const child of children) { if (child.exitCode === null) child.kill(); await child.done; } fs.rmSync(directory, { recursive: true, force: true }); });
  const store = new AssistantTaskStore({ directory }), task = store.create({ ownerId: 'one', goal: 'Keep concurrent receipts.' }); store.start(task.id);
  const moduleUrl = new URL('../../src/assistant/tasks.mjs', import.meta.url).href;
  const script = `import { AssistantTaskStore } from ${JSON.stringify(moduleUrl)};
    const [directory,id,worker,count] = process.argv.slice(1), store = new AssistantTaskStore({directory});
    const RETRY_MS=3, MAX_RETRIES=2000;
    for(let index=0;index<Number(count);index++) {
      let retries=0;
      for(;;) { try { store.requested(id,{id:worker+'-'+index,name:'read_file',arguments:{path:'note.txt'}},{mutation:false}); break; }
        catch(error) { if(!/busy|lock|owner changed/i.test(error.message)||++retries>MAX_RETRIES) throw error; await new Promise(resolve=>setTimeout(resolve,RETRY_MS)); } }
    }`;
  for (let worker = 0; worker < WORKERS; worker++) {
    const child = spawn(process.execPath, ['--input-type=module', '-e', script, directory, task.id, String(worker), String(WRITES)], { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let output = ''; child.stdout.on('data', chunk => { output += chunk; }); child.stderr.on('data', chunk => { output += chunk; });
    child.done = new Promise(resolve => child.once('close', code => resolve(code))); child.output = () => output; children.push(child);
  }
  for (const child of children) assert.equal(await child.done, 0, child.output());
  const saved = store.get(task.id);
  assert.equal(saved.steps.length, WORKERS * WRITES);
  assert.equal(new Set(saved.steps.map(step => step.callId)).size, WORKERS * WRITES);
  console.log(`ASSISTANT_CONTENTION_OK processes=${WORKERS} receipts=${saved.steps.length}`);
});
