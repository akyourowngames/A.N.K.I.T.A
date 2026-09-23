import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { PassThrough } from 'node:stream';
import { Terminal } from '../src/ui.mjs';
import { JOB_COMMANDS, isJobCommand, jobEventText } from '../src/job-ui.mjs';

test('terminal job controls can bypass an active chat wait without consuming its answer', async t => {
  const input = new PassThrough(), output = new PassThrough();
  let printed = '';
  output.on('data', d => { printed += d; });
  const term = new Terminal({ input, output });
  t.after(() => term.close());
  const intercepted = [];
  term.interceptLine = line => { if (!isJobCommand(line)) return false; intercepted.push(line); return true; };
  const answer = term.ask('allow? ');
  input.write('/jobs\n');
  term.notify('job 1 finished');
  input.write('yes\n');
  assert.equal(await answer, 'yes');
  assert.deepEqual(intercepted, ['/jobs']);
  assert.match(printed, /job 1 finished/);
  assert.ok(JOB_COMMANDS.includes('/input'));
  assert.match(jobEventText({ id: '1', event: 'started', command: 'serve' }), /running in background.*\/job 1/);
});

test('actual CLI starts a background job, lists it, sends stdin, reads output and stays responsive', { timeout: 25000 }, async t => {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-cli-jobs-'));
  const server = http.createServer((req, res) => {
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ data: [{ id: 'mock', context_length: 128000 }] }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const childFile = path.join(cwd, 'echo.cjs');
  fs.writeFileSync(childFile, "process.stdin.setEncoding('utf8'); process.stdin.on('data', s=>{ console.log('ACK:'+s.trim()); if(s.includes('quit')) process.exit(0); }); console.log('READY');");
  fs.writeFileSync(path.join(cwd, '.env'), `API_BASE=http://127.0.0.1:${server.address().port}/v1\nAPI_KEY=dummy\nMODEL=mock\nTOOLS=on\nAUTO_APPROVE=on\nMEMORY_CONSOLIDATION=off\nEMBEDDINGS=off\n`);
  const child = spawn(process.execPath, [path.resolve('chat.mjs'), '--plain', '--no-banner'], { cwd, env: { ...process.env, CONFIG_DIR: cwd, NO_COLOR: '1' }, windowsHide: true });
  let output = '', error = '';
  child.stdout.on('data', d => { output += d; });
  child.stderr.on('data', d => { error += d; });
  t.after(async () => {
    child.stdin.end('/exit\n');
    if (child.exitCode === null) child.kill();
    server.closeAllConnections(); server.close();
    fs.rmSync(cwd, { recursive: true, force: true });
  });
  const until = async pattern => {
    const deadline = Date.now() + 12000;
    while (!pattern.test(output)) {
      if (child.exitCode !== null || Date.now() > deadline) assert.fail(`CLI did not produce ${pattern}: ${output}\n${error}`);
      await new Promise(resolve => setTimeout(resolve, 25));
    }
  };
  await until(/›/);
  const quote = value => `'${value.replace(/'/g, process.platform === 'win32' ? "''" : "'\\''")}'`;
  child.stdin.write(`/bg ${process.platform === 'win32' ? '& ' : ''}${quote(process.execPath)} ${quote(childFile)}\n`);
  await until(/running in background/);
  child.stdin.write('/jobs\n/input 1 hello\n/input 1 quit\n/wait 1 10000\n/job 1 0\n');
  await until(/ACK:hello[\s\S]*quit/);
  assert.match(output, /1 running \| \/jobs/);
  assert.match(output, /next_offset=/);
  child.stdin.write('/exit\n');
  await new Promise(resolve => child.once('exit', resolve));
  assert.equal(child.exitCode, 0, error);
});
