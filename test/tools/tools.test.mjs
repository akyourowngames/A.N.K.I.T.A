import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import * as registry from '../../tools/index.mjs';
import * as edit from '../../tools/filesystem/edit-file.mjs';
import * as shared from '../../tools/shared/_shared.mjs';
import { renderDiff } from '../../tools/shared/_diff.mjs';

function workspace(t) {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'chat-tools-'));
  t.after(() => fs.rmSync(cwd, { recursive: true, force: true }));
  return { cwd, state: {} };
}
const ui = Object.fromEntries(['cyan','red','green','dim','bold'].map(k => [k, s => s]));

test('paths handed to the model are usable: cwd-relative inside, absolute outside', () => {
  const cwd = path.join('C:', 'work', 'proj');
  assert.equal(shared.displayPath(cwd, path.join(cwd, 'src', 'a.mjs')), 'src/a.mjs');
  assert.equal(shared.displayPath(cwd, cwd), path.resolve(cwd).split(path.sep).join('/'));
  assert.equal(
    shared.displayPath(cwd, path.join('C:', 'other', 'pic.jpg')),
    'C:/other/pic.jpg'
  );
  assert.equal(shared.displayPath(cwd, path.join(cwd, '..', 'sibling', 'b.txt')), 'C:/work/sibling/b.txt');
});

test('read_file redirects image files instead of calling them binary', t => {
  const ctx = workspace(t);
  const png = path.join(ctx.cwd, 'shot.png');
  fs.writeFileSync(png, Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x00, 0x01]));
  const out = registry.get('read_file').run({ path: 'shot.png' }, ctx);
  assert.match(out, /is an image file, not text/);
  assert.match(out, /work-review artifacts/);
  assert.doesNotMatch(out, /looks like a binary file/);
  // Non-image binaries keep the original guard.
  const bin = path.join(ctx.cwd, 'blob.dat');
  fs.writeFileSync(bin, Buffer.from([0x00, 0x01, 0x02]));
  assert.match(registry.get('read_file').run({ path: 'blob.dat' }, ctx), /looks like a binary file/);
});

test('search tools refuse paths outside the working directory', (t) => {
  const ctx = workspace(t);
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'chat-outside-'));
  t.after(() => fs.rmSync(outside, { recursive: true, force: true }));
  fs.writeFileSync(path.join(outside, 'needle.txt'), 'haystack needle here');

  assert.throws(() => registry.get('glob').run({ pattern: 'needle.txt', path: outside }, ctx), /workspace boundary/);
  assert.throws(() => registry.get('search_files').run({ pattern: 'needle', path: outside }, ctx), /workspace boundary/);
});

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
  const originalId = ctx.state.todos[0].id;
  registry.get('write_todos').run({ updates: [{ id: originalId, status: 'completed' }] }, ctx);
  assert.equal(ctx.state.todos[0].id, originalId);
  assert.equal(ctx.state.todos[0].status, 'completed');
  assert.throws(() => registry.get('write_todos').run({ todos: [{ content: 'Different task', status: 'pending' }] }, ctx), /replace|remove/i);
  assert.equal(ctx.state.todos[0].content, 'Verify');
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

test('shell failures surface a non-zero exit instead of a silent success', async t => {
  const ctx = workspace(t);
  const cmd = process.platform === 'win32'
    ? 'Get-ChildItem C:/definitely/not/here'
    : 'cat /definitely/not/here';
  const out = await registry.get('run_command').run({ command: cmd, yield_ms: 10000 }, ctx);
  assert.match(out, /exit code: [1-9]/);
  if (process.platform === 'win32') {
    const lenient = await registry.get('run_command').run(
      { command: 'Get-ChildItem C:/nope -ErrorAction SilentlyContinue; Write-Output continued', yield_ms: 10000 }, ctx);
    assert.match(lenient, /exit code: 0/);
    assert.match(lenient, /continued/);
  }
});

test('command input/environment, bounded output and background jobs', async t => {
  const ctx = workspace(t);
  t.after(async () => { if(registry.cleanupJobs) await registry.cleanupJobs(ctx.state); });
  const command = process.platform === 'win32'
    ? "[Console]::In.ReadToEnd(); [Console]::Write($env:CHAT_TOOLS_TEST)"
    : "cat; printf '%s' \"$CHAT_TOOLS_TEST\"";
  const out = await registry.get('run_command').run({command,stdin:'hello',env:{CHAT_TOOLS_TEST:'world'},yield_ms:10000},ctx);
  assert.match(out,/hello/); assert.match(out,/world/);
  const burst = process.platform === 'win32' ? "[Console]::Write(('x' * 200000))" : "head -c 200000 /dev/zero | tr '\\0' x";
  assert.ok(Buffer.byteLength(await registry.get('run_command').run({command:burst,yield_ms:10000},ctx))<66000);
  const sleep = process.platform === 'win32' ? 'Start-Sleep -Seconds 60' : 'sleep 60';
  const started = await registry.get('run_command').run({command:sleep,background:true},ctx);
  assert.match(started,/job/i); assert.equal([...ctx.state.jobs.values()].filter(j=>!j.done).length,1);
  const jobId = [...ctx.state.jobs.keys()].at(-1);
  assert.match(await registry.get('job_status').run({job_id:jobId},ctx),/running/);
  assert.match(await registry.get('job_stop').run({job_id:jobId},ctx),/stopped|cancelled/);
});
