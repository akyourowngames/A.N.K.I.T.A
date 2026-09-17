import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import * as registry from '../tools/index.mjs';
import * as edit from '../tools/edit-file.mjs';
import { renderDiff } from '../tools/_diff.mjs';

function workspace(t) {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'chat-tools-'));
  t.after(() => fs.rmSync(cwd, { recursive: true, force: true }));
  return { cwd, state: {} };
}
const ui = Object.fromEntries(['cyan','red','green','dim','bold'].map(k => [k, s => s]));

test('approval diff includes the last change and full long lines', () => {
  const after = Array.from({length: 90}, (_, i) => `${i} ${'x'.repeat(150)}`).join('\n');
  const diff = renderDiff('', after, { ui, width: 30 });
  assert.ok(diff.includes(`89 ${'x'.repeat(150)}`));
  assert.ok(!diff.includes('truncated'));
});

test('edit fallback reports line endings, trailing whitespace, indentation and refuses ambiguity atomically', t => {
  const ctx = workspace(t), p = path.join(ctx.cwd, 'a.txt');
  fs.writeFileSync(p, '  first  \r\n    second\r\n');
  let plan = edit.prepare({path:p, old_string:'  first  \n    second', new_string:'done'}, ctx);
  assert.equal(plan.applied[0].match, 'line-endings');
  plan = edit.prepare({path:p, old_string:'  first\n    second', new_string:'done'}, ctx);
  assert.equal(plan.applied[0].match, 'trailing-whitespace');
  plan = edit.prepare({path:p, old_string:'first\nsecond', new_string:'done'}, ctx);
  assert.equal(plan.applied[0].match, 'indentation');
  fs.writeFileSync(p, '  match\n    match\n');
  const result = edit.run({path:p, old_string:'match', new_string:'changed'}, ctx);
  assert.match(result, /matches 2 times/);
  assert.equal(fs.readFileSync(p,'utf8'), '  match\n    match\n');
});

test('search aliases support exclusions, recursive listing and readOnly metadata', t => {
  const ctx = workspace(t);
  fs.mkdirSync(path.join(ctx.cwd,'nested'));
  fs.writeFileSync(path.join(ctx.cwd,'nested','keep.txt'),'needle');
  fs.writeFileSync(path.join(ctx.cwd,'nested','skip.txt'),'needle');
  const result = registry.get('search_files').run({pattern:'needle',include:'**/*.txt',exclude:'**/skip*'},ctx);
  assert.match(result,/keep.txt/); assert.doesNotMatch(result,/skip.txt/);
  assert.match(registry.get('glob').run({pattern:'**/*.txt',exclude:'**/skip*'},ctx),/keep.txt/);
  assert.match(registry.get('list_dir').run({recursive:true},ctx),/nested\/keep.txt/);
  for (const name of ['read_file','search_files','glob','list_dir','fetch_url','job_status']) assert.equal(registry.get(name).readOnly,true);
});

test('file verbs protect workspace root, reject overwrites, and update todos atomically', t => {
  const ctx = workspace(t);
  registry.get('create_dir').run({path:'new/deep'},ctx);
  assert.ok(fs.existsSync(path.join(ctx.cwd,'new/deep')));
  fs.writeFileSync(path.join(ctx.cwd,'a'),'a'); fs.writeFileSync(path.join(ctx.cwd,'b'),'b');
  assert.throws(() => registry.get('move_file').run({source:'a',destination:'b'},ctx),/exist/);
  assert.throws(() => registry.get('delete_file').run({path:ctx.cwd,recursive:true},ctx),/root|working directory/i);
  registry.get('move_file').run({source:'a',destination:'new/a'},ctx);
  registry.get('delete_file').run({path:'new/a'},ctx);
  assert.ok(!fs.existsSync(path.join(ctx.cwd,'new/a')));
  registry.get('write_todos').run({todos:[{content:'Verify',status:'in_progress'}]},ctx);
  assert.equal(ctx.state.todos[0].content,'Verify');
  assert.throws(() => registry.get('write_todos').run({todos:[{content:'Bad',status:'invalid'}]},ctx));
  assert.equal(ctx.state.todos[0].content,'Verify');
});

test('fetch_url bounds streaming responses and enforces timeout', async t => {
  const server = http.createServer((req,res) => {
    if (req.url === '/slow') return;
    res.writeHead(200,{'Content-Type':'text/plain'}); res.end('x'.repeat(200000));
  });
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  const url = `http://127.0.0.1:${server.address().port}`;
  const out = await registry.get('fetch_url').run({url,max_bytes:2048},{});
  assert.ok(Buffer.byteLength(out)<3000); assert.match(out,/truncat/i);
  await assert.rejects(registry.get('fetch_url').run({url:url+'/slow',timeout_ms:100},{}),/timeout|abort/i);
});

test('command input/environment, bounded output and background jobs', async t => {
  const ctx = workspace(t);
  t.after(async () => { if(registry.cleanupJobs) await registry.cleanupJobs(ctx.state); });
  const command = process.platform === 'win32'
    ? "[Console]::In.ReadToEnd(); [Console]::Write($env:CHAT_TOOLS_TEST)"
    : "cat; printf '%s' \"$CHAT_TOOLS_TEST\"";
  const out = await registry.get('run_command').run({command,stdin:'hello',env:{CHAT_TOOLS_TEST:'world'}},ctx);
  assert.match(out,/hello/); assert.match(out,/world/);
  const burst = process.platform === 'win32' ? "[Console]::Write(('x' * 200000))" : "head -c 200000 /dev/zero | tr '\\0' x";
  assert.ok(Buffer.byteLength(await registry.get('run_command').run({command:burst},ctx))<66000);
  const sleep = process.platform === 'win32' ? 'Start-Sleep -Seconds 60' : 'sleep 60';
  const started = await registry.get('run_command').run({command:sleep,background:true},ctx);
  assert.match(started,/job/i); assert.equal(ctx.state.jobs.size,1);
  const jobId = [...ctx.state.jobs.keys()][0];
  assert.match(await registry.get('job_status').run({job_id:jobId},ctx),/running/);
  assert.match(await registry.get('job_stop').run({job_id:jobId},ctx),/stopped|cancelled/);
});
