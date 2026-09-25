import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { killTree } from '../../tools/process/run-command.mjs';
import * as kill from '../../tools/process/kill-process.mjs';
import { processIdentity } from '../../tools/shared/_process.mjs';

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const alive = pid => { try { process.kill(pid, 0); return true; } catch { return false; } };

async function tree(t) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-tree-'));
  const childFile = path.join(dir, 'leaf.cjs');
  const parentFile = path.join(dir, 'parent.cjs');
  const pidFile = path.join(dir, 'pid');
  const exitFile = path.join(dir, 'exit');
  await fs.writeFile(childFile, `require('fs').writeFileSync(${JSON.stringify(pidFile)},String(process.pid));setInterval(()=>{},1000);`);
  await fs.writeFile(parentFile, `require('child_process').spawn(process.execPath,[${JSON.stringify(childFile)}],{stdio:['ignore','inherit','inherit'],detached:process.platform==='win32',windowsHide:true});setInterval(()=>{if(require('fs').existsSync(${JSON.stringify(exitFile)}))process.exit(0)},50);`);
  const root = spawn(process.execPath, [parentFile], { detached: process.platform !== 'win32', windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  let leaf;
  t.after(async () => {
    if (leaf && alive(leaf)) { try { process.kill(leaf, 'SIGKILL'); } catch {} }
    if (root.exitCode === null) root.kill('SIGKILL');
    await delay(150);
    await fs.rm(dir, { recursive: true, force: true });
  });
  for (let i = 0; i < 100; i++) {
    try { leaf = Number(await fs.readFile(pidFile, 'utf8')); break; } catch {}
    await delay(50);
  }
  assert.ok(leaf, 'test descendant started');
  return { root, leaf, exitFile };
}

test('job tree cleanup survives the group leader exiting with inherited pipes', { timeout: 20000 }, async t => {
  const { root, leaf, exitFile } = await tree(t);
  const tracker = await import('../../tools/shared/_job-tree.mjs').catch(() => null);
  if (tracker) await tracker.trackJobTree(root);
  const exited = once(root, 'exit');
  await fs.writeFile(exitFile, 'exit');
  await exited;
  assert.equal(alive(leaf), true);
  await killTree(root);
  for (let i = 0; i < 60 && alive(leaf); i++) await delay(50);
  assert.equal(alive(leaf), false);
});

test('kill approval protects grandparents and previews the entire process tree', { timeout: 30000 }, async t => {
  const parent = await processIdentity(process.ppid);
  if (parent.parent > 1) await assert.rejects(kill.approval({ pid: parent.parent, force: true }, {}), /protected|ancestor|refus/i);
  const { root, leaf } = await tree(t);
  const ctx = {};
  const args = { pid: root.pid, force: true };
  const preview = await kill.approval(args, ctx);
  assert.match(preview, new RegExp(`PID ${leaf}`));
  await kill.run(args, ctx);
  for (let i = 0; i < 60 && alive(leaf); i++) await delay(50);
  assert.equal(alive(leaf), false);
});
