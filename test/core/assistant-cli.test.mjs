import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { AssistantTaskStore, ASSISTANT_TASK_DIRECTORY } from '../../src/assistant/tasks.mjs';
import { runLocalCommand } from '../../src/core/local-commands.mjs';

const WAIT_MS = 15000; // Milliseconds: bounded local process/server acceptance.
const CLI = fileURLToPath(new URL('../../chat.mjs', import.meta.url));
const call = (id, name, args) => ({ id, type: 'function', function: { name, arguments: JSON.stringify(args) } });

test('offline work listing and details do not bootstrap a provider', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'assistant-offline-')); t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const store = new AssistantTaskStore({ directory }), task = store.create({ ownerId: 'owner', goal: 'Saved request' }), output = [];
  assert.equal(await runLocalCommand(['work', 'list'], { assistantTasks: store, write: text => output.push(text) }), true);
  assert.equal(JSON.parse(output[0])[0].id, task.id);
  await runLocalCommand(['work', 'show', task.id], { assistantTasks: store, write: text => output.push(text) });
  assert.equal(JSON.parse(output[1]).goal, task.goal);
});

test('real CLI crash and restart continue one original goal with an exact completed-action guard', { timeout: WAIT_MS * 2 }, async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'assistant-cli-')), profile = path.join(directory, 'profile');
  const children = [], errors = []; let resumed = false, held, captured;
  const waiting = new Promise(resolve => { held = resolve; });
  const save = { path: 'note.txt', content: 'Saved exactly once.' };
  const server = http.createServer(async (req, res) => {
    res.setHeader('content-type', 'application/json');
    if (req.method === 'GET') return res.end(JSON.stringify({ data: [{ id: 'assistant-fixture', tools: true, context: 131072 }] }));
    try {
      let raw = ''; for await (const chunk of req) raw += chunk;
      const body = JSON.parse(raw), receipts = body.messages.filter(message => message.role === 'tool');
      const reply = (content, tool) => res.end(JSON.stringify({ choices: [{ message: { role: 'assistant', content, ...(tool ? { tool_calls: [tool] } : {}) }, finish_reason: tool ? 'tool_calls' : 'stop' }] }));
      if (!resumed) {
        if (!receipts.length) return reply('', call('save-once', 'write_file', save));
        captured = body; held(); return; // Crash while the next decision is pending, after the saved file receipt.
      }
      assert.ok(body.messages.some(message => String(message.content).includes('Save a note then a reminder.')));
      if (!receipts.some(message => /already completed/.test(String(message.content)))) return reply('', call('attempt-repeat', 'write_file', save));
      if (!receipts.some(message => String(message.content).includes('reminder.txt'))) return reply('', call('save-remaining', 'write_file', { path: 'reminder.txt', content: 'Continue from the saved note.' }));
      return reply('The saved note was kept and the reminder is ready.');
    } catch (error) { errors.push(error.message); res.statusCode = 500; res.end(JSON.stringify({ error: { message: error.message } })); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const launch = (args, cwd = directory) => {
    const child = spawn(process.execPath, [CLI, ...args, '--plain', '--no-banner', '--yes'], { cwd, windowsHide: true,
      env: { ...process.env, CONFIG_DIR: profile, PROVIDER: 'kilo', MODEL: 'assistant-fixture', API_BASE: `http://127.0.0.1:${server.address().port}/v1`, API_KEY: 'fixture-only',
        TOOL_PROVIDER: '', TOOL_MODEL: '', TOOL_API_BASE: '', TOOL_API_KEY: '', CONTEXT_WINDOW: '131072', MAX_TOKENS: '1000',
        MEMORY_CONSOLIDATION: 'off', MEMORY_RECALL_CHARS: '0', EMBEDDINGS: 'off', PROJECT_AUTO_DETECT: 'off', PROJECT_WORK_CAPTURE: 'off', PROJECT_AUTO_MAINTENANCE: 'off', SUBAGENTS_ENABLED: 'off', TOOLS: 'on', SPEAK: 'off' },
      stdio: ['ignore', 'pipe', 'pipe'] });
    let output = ''; child.stdout.on('data', chunk => { output += chunk; }); child.stderr.on('data', chunk => { output += chunk; });
    children.push(child); child.output = () => output;
    child.done = new Promise(resolve => child.once('close', code => resolve(code))); return child;
  };
  t.after(async () => { for (const child of children) { if (child.exitCode === null) child.kill(); await child.done; } server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); fs.rmSync(directory, { recursive: true, force: true }); });
  const initial = launch(['--prompt', 'Save a note then a reminder.']);
  let timer; await Promise.race([waiting, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(initial.output() || 'CLI never reached the second decision')), WAIT_MS); })]).finally(() => clearTimeout(timer));
  assert.ok(captured); initial.kill(); await initial.done;
  const store = new AssistantTaskStore({ directory: path.join(profile, ASSISTANT_TASK_DIRECTORY) });
  assert.equal(store.recoverInterrupted(), 1); const task = store.list()[0];
  assert.equal(task.steps[0].phase, 'settled'); resumed = true;
  assert.equal(task.workspacePath, fs.realpathSync(directory));
  const otherDirectory = path.join(directory, 'another-folder'); fs.mkdirSync(otherDirectory);
  const continuation = launch(['--resume-task', task.id], otherDirectory);
  assert.equal(await continuation.done, 0, continuation.output());
  assert.equal(store.get(task.id).attempt, 2); assert.equal(store.get(task.id).status, 'completed');
  assert.ok(store.get(task.id).steps.some(step => step.phase === 'not_run' && /already completed/.test(step.result)));
  assert.equal(fs.readFileSync(path.join(directory, 'reminder.txt'), 'utf8'), 'Continue from the saved note.');
  assert.equal(fs.existsSync(path.join(otherDirectory, 'reminder.txt')), false);
  assert.deepEqual(errors, []);
  console.log('ASSISTANT_CLI_RESTART_OK original_goal=kept completed_write=blocked remaining_file=saved attempts=2');
});
