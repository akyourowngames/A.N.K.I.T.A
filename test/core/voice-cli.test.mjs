import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { spawn } from 'node:child_process';

const CLI_URL = new URL('../../src/core/cli.mjs', import.meta.url).href;
const CHILD_TIMEOUT_MS = 15000; // Test-only ceiling: no real microphone or cloud service is used.
const BARGE_MODES = new Set(['latency', 'latency-mic-failure', 'latency-cancel']);
async function runCli(t, mode) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-cli-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));
  const runtime = path.join(directory, 'config');
  const file = path.join(directory, 'note.txt');
  const models = [];
  let emittedEmpty = false;
  const server = http.createServer(async (request, response) => {
    response.setHeader('Content-Type', 'application/json');
    if (request.url.endsWith('/models')) { response.end(JSON.stringify({ data: [{ id: 'typed-model', context_length: 131072, supported_parameters: ['tools'] }] })); return; }
    let raw = ''; for await (const chunk of request) raw += chunk;
    const body = JSON.parse(raw); models.push(body.model);
    if (mode === 'failure' && body.model === 'voice-model') { response.statusCode = 403; response.end('Planner access denied'); return; }
    const voice = body.model === 'voice-model';
    if (voice) {
      assert.equal(body.reasoning_effort, 'low'); assert.equal(body.max_tokens, 4096);
      assert.match(body.messages[0].content, /one or two short sentences/);
    } else assert.ok(!body.messages[0].content.includes('Voice conversation:'));
    if (voice && mode === 'output-limit') {
      response.end(JSON.stringify({ choices: [{ message: { content: '' }, finish_reason: 'length' }] })); return;
    }
    if (voice && (mode === 'empty-twice' || (!emittedEmpty && (mode === 'empty-first' || (mode === 'empty-final' && body.messages.some(message => message.role === 'tool')))))) {
      emittedEmpty = true;
      response.end(JSON.stringify({ choices: [{ message: { role: 'assistant', content: '' }, finish_reason: 'stop' }] })); return;
    }
    if (mode === 'mixed-approval' && !voice) {
      const done = body.messages.some(message => message.role === 'tool' && message.tool_call_id === 'typed-write');
      response.end(JSON.stringify({ choices: [{ message: done ? { role: 'assistant', content: 'Hi from chat.' } : {
        role: 'assistant', content: '', tool_calls: [{ id: 'typed-write', type: 'function', function: { name: 'write_file', arguments: JSON.stringify({ path: path.join(directory, 'typed-note.txt'), content: 'Typed request approved' }) } }],
      } }] })); return;
    }
    if (mode === 'mixed-approval' && voice && !body.messages.some(message => message.role === 'tool')) await new Promise(resolve => setTimeout(resolve, 250));
    if (voice && mode === 'controls') {
      assert.ok(body.tools.some(tool => tool.function.name === 'voice_jobs'));
      const user = body.messages.findLast(message => message.role === 'user')?.content;
      const results = body.messages.filter(message => message.role === 'tool');
      const reply = (content, action, id) => response.end(JSON.stringify({ choices: [{ message: action ? {
        role: 'assistant', content: '', tool_calls: [{ id: `control-${results.length}`, type: 'function', function: { name: 'voice_jobs', arguments: JSON.stringify({ action, ...(id ? { id } : {}) }) } }],
      } : { role: 'assistant', content } }] }));
      if (user === 'Slow research') {
        await new Promise(resolve => { const timer = setTimeout(resolve, 7000); response.once('close', () => { clearTimeout(timer); resolve(); }); });
        if (!response.destroyed) reply('Research complete.');
      } else if (!results.length) reply('', 'list');
      else if (user === 'What is running?') reply('First task is running.');
      else if (results.length === 1) {
        const first = JSON.parse(results[0].content.split('\n')[0]).find(job => job.transcript === 'Slow research');
        reply('', 'cancel', first.id);
      } else reply('First task stopped.');
      return;
    }
    const tool = voice && !body.messages.some(message => message.role === 'tool');
    if (voice && !tool && ['narration', 'tail-cancel'].includes(mode)) await new Promise(resolve => setTimeout(resolve, 100));
    if (voice && mode === 'parallel' && body.messages.at(-1)?.content === 'First slow note') await new Promise(resolve => setTimeout(resolve, 400));
    if (voice && ['end-running', 'clear-running'].includes(mode) && tool) await new Promise(resolve => setTimeout(resolve, 250));
    if (!voice && ['end-running', 'clear-running'].includes(mode)) await new Promise(resolve => setTimeout(resolve, 600));
    response.end(JSON.stringify({ choices: [{ message: tool ? {
      role: 'assistant', content: 'Intermediate tool preamble.', reasoning_content: 'HIDDEN REASONING', tool_calls: [{ id: 'write-1', type: 'function', function: {
        name: 'write_file', arguments: JSON.stringify({ path: file, content: 'Workspace ready' }),
      } }],
    } : { role: 'assistant', content: voice ? `Workspace tayyar hai.${mode === 'verbose-reply' ? ' File is ready. Want anything else?' : ''}` : 'Hi from chat.' } }] }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  const endpoint = `http://127.0.0.1:${server.address().port}/v1`;
  fs.writeFileSync(path.join(directory, '.env'), [
    'PROVIDER=kilo', 'MODEL=typed-model', `API_BASE=${endpoint}`, 'VOICE_PROVIDER=baseten',
    'VOICE_MODEL=voice-model', 'VOICE_CONTEXT_WINDOW=131072', `VOICE_API_BASE=${endpoint}`, 'BASETEN_API_KEY=fixture-planner',
    'STT_PROVIDER=sarvam', `SARVAM_API_KEY=${mode === 'probe' ? '' : 'fixture-speech'}`, 'TTS_PROVIDER=sarvam',
    'TOOL_PROVIDER=kilo', 'TOOL_MODEL=unwanted-tool-model', `TOOL_API_BASE=${endpoint}`,
    `AUTO_APPROVE=${['narration', 'tail-cancel', 'parallel', 'end-running', 'clear-running', 'controls'].includes(mode) || BARGE_MODES.has(mode) ? 'on' : 'off'}`, `VOICE_BARGE_IN=${BARGE_MODES.has(mode) ? 'on' : 'off'}`, 'VOICE_HFP_ROUTING=off', 'MEMORY_CONSOLIDATION=off',
    'VOICE_SPEECH_GAP_MS=5',
    'VOICE_JOB_SPEAK_MIN_INTERVAL_MS=1', // Fixture rate: exercise the result update without a real multi-second task.
    'EMBEDDINGS=off', 'PROJECT_AUTO_DETECT=off', 'PROJECT_WORK_CAPTURE=off', 'PROJECT_AUTO_MAINTENANCE=off',
    'SUBAGENTS_ENABLED=off',
  ].join('\n'));
  const harness = path.join(directory, 'harness.mjs');
  fs.writeFileSync(harness, `
    import fs from 'node:fs';
    import { main } from ${JSON.stringify(CLI_URL)};
    let capture = 0;
    let inputCount = 0;
    let discoveryCount = 0;
    const fetchOriginal = globalThis.fetch;
    globalThis.fetch = async (url, options) => {
      if (${JSON.stringify(mode)} === 'cancel' && options?.body && JSON.parse(options.body).model === 'voice-model') {
        setImmediate(() => process.emit('SIGINT'));
      }
      return fetchOriginal(url, options);
    };
    process.argv = [process.execPath, ${JSON.stringify(harness)}, '--voice', '--plain', '--no-banner'];
    // Capture the CLI's requested exit and allow test sockets to close naturally.
    // Immediate process.exit with mocked, zero-duration audio hits Node's Windows
    // libuv shutdown assertion; this harness tests the loop, not forced teardown.
    const requestedExit = new Error('requested CLI exit');
    process.exit = code => { process.exitCode = code; throw requestedExit; };
    try { await main({ voiceIO: {
      voiceRuntimeCheck: () => ${mode === 'probe' ? JSON.stringify('VOICE_IO_PROBE') : 'null'},
      audioDeps: () => ({ ffmpeg: true, ffplay: true }),
      detectMic: async () => {
        console.log('MIC_DISCOVERY');
        if (++discoveryCount === 2 && ${JSON.stringify(mode)} === 'capture-refresh-failure') throw new Error('fixture discovery failed');
        return { name: 'fixture mic' };
      },
      openVoiceInput: ({outFile}) => {
        fs.writeFileSync(outFile, 'fixture');
        const barge = ++inputCount === 2 && ${BARGE_MODES.has(mode)};
        if (barge) console.log('BARGE_OPEN');
        const failed = (barge && ${JSON.stringify(mode)} === 'latency-mic-failure') || (inputCount === 1 && ${JSON.stringify(mode)} === 'capture-refresh-failure');
        return {
          ready: failed ? Promise.reject(new Error('fixture mic disconnected')) : Promise.resolve().then(() => console.log('CAPTURE_READY')),
          stop: async () => { if (barge) console.log('BARGE_STOPPED'); return true; },
        };
      },
      transcribeAudio: async () => ({ text: ${JSON.stringify(mode)} === 'controls' ? ['Slow research', 'What is running?', 'Stop first task', 'exit'][capture++] : ${JSON.stringify(mode)} === 'parallel' ? ['First slow note', 'Second fast note', 'exit'][capture++] : capture++ ? 'exit' : 'Workspace kholo', languageCode: 'hi-IN', confidence: 0.99 }),
      synthesizeSarvam: async ({text}) => {
        if (${BARGE_MODES.has(mode)} && text === 'Workspace tayyar hai.') {
          console.log('REPORT_SYNTH_START');
          if (${JSON.stringify(mode)} === 'latency-cancel') setImmediate(() => process.emit('SIGINT'));
          await new Promise(resolve => setTimeout(resolve, 75));
          console.log('REPORT_SYNTH_READY');
        }
        if (${JSON.stringify(mode)} === 'tts-failure') throw new Error('fixture Sarvam outage');
        if (${JSON.stringify(mode)} === 'approval-cancel' && text.startsWith('Permission chahiye')) {
          setImmediate(() => process.emit('SIGINT'));
          await new Promise(resolve => setTimeout(resolve, 500));
        }
        return Buffer.from(text);
      },
      synthesizeEdge: async ({text}) => Buffer.from(text),
      narrate: async event => event.phase === 'completed' ? 'Your workspace note is saved.' : "I'm writing your workspace note now.",
      playMp3: async (audio, {signal} = {}) => {
        console.log('PLAYED: ' + audio.toString());
        const tail = ${JSON.stringify(mode)} === 'tail-cancel' && audio.toString() === 'Your workspace note is saved.';
        if (tail) setTimeout(() => process.emit('SIGINT'), 150);
        await new Promise(resolve => {
          const timer = setTimeout(resolve, tail ? 250 : 20);
          signal?.addEventListener('abort', () => { clearTimeout(timer); resolve(); }, {once: true});
        });
        console.log('ENDED: ' + audio.toString());
      },
      stopPlayback: () => {},
    } }); } catch (error) { if (error !== requestedExit) throw error; }
  `);
  const child = spawn(process.execPath, [harness], { cwd: directory, env: { ...process.env, CONFIG_DIR: runtime, NO_COLOR: '1', SARVAM_API_KEY: '', BASETEN_API_KEY: '' }, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
  let stdout = ''; let stderr = ''; let captures = 0; let approval = false; let typed = false;
  let pendingCapture = false;
  let promptsBeforeAnswer = 0, firstDenied = false, secondAnswered = false;
  child.stdout.on('data', data => {
    stdout += data;
    const seen = stdout.split('CAPTURE_READY').length - 1;
    while (captures < seen) {
      captures++;
      if (captures === 1 || (['parallel', 'end-running', 'clear-running', 'controls', 'mixed-approval'].includes(mode) && captures === 2)) child.stdin.write('\n');
      else pendingCapture = true;
    }
    const readyReports = (stdout.match(/ENDED: (?:Workspace tayyar hai|Work did not finish|Cancelled|First task is running|First task stopped)/g) || []).length;
    const reportsNeeded = mode === 'controls' ? captures === 3 ? 1 : 3 : mode === 'parallel' ? 2 : 1;
    if (pendingCapture && readyReports >= reportsNeeded) { pendingCapture = false; child.stdin.write('\n'); }
    if (mode === 'mixed-approval') {
      const prompts = stdout.split('allow?').length - 1;
      if (!typed && prompts >= 1) {
        typed = true; child.stdin.write('Typed file request\n');
        setTimeout(() => { promptsBeforeAnswer = stdout.split('allow?').length - 1; firstDenied = true; child.stdin.write('n\n'); }, 200);
      }
      if (firstDenied && prompts >= 2 && !secondAnswered) { secondAnswered = true; child.stdin.end('y\n/task\n/exit\n'); }
    } else if (!approval && stdout.includes('allow?')) { approval = true; child.stdin.write('y\n'); }
    if (mode !== 'mixed-approval' && !typed && (stdout.includes('leaving voice mode') || stdout.includes('VOICE_IO_PROBE') || stdout.includes('voice needs SARVAM_API_KEY'))) {
      typed = true; child.stdin.end(`${mode === 'clear-running' ? '/clear\n' : ''}Say hello\n/task\n/exit\n`);
    }
  });
  child.stderr.on('data', data => { stderr += data; });
  const code = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { child.kill(); reject(new Error(`CLI timeout: ${stdout}\n${stderr}`)); }, CHILD_TIMEOUT_MS);
    child.on('exit', code => { clearTimeout(timer); resolve(code); });
    child.on('error', error => { clearTimeout(timer); reject(error); });
  });
  assert.equal(code, 0, stdout + stderr);
  const tasks = path.join(runtime, 'voice-tasks');
  const records = fs.existsSync(tasks) ? fs.readdirSync(tasks).filter(name => name.endsWith('.json')).map(name => JSON.parse(fs.readFileSync(path.join(tasks, name), 'utf8'))) : [];
  const sessions = path.join(runtime, 'sessions');
  const history = fs.existsSync(sessions) ? fs.readdirSync(sessions).filter(name => name.endsWith('.json')).map(name => ({ name, ...JSON.parse(fs.readFileSync(path.join(sessions, name), 'utf8')) })) : [];
  return { stdout, models, records, history, promptsBeforeAnswer, typedWritten: fs.existsSync(path.join(directory, 'typed-note.txt')), written: fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : null };
}

test('CLI voice devices can be supplied without opening a physical microphone', async t => {
  const result = await runCli(t, 'probe');
  assert.match(result.stdout, /VOICE_IO_PROBE/);
});

test('CLI accepts a second voice request before the slow first request completes', async t => {
  const result = await runCli(t, 'parallel');
  assert.equal(result.records.length, 2);
  const first = result.records.find(record => record.transcript === 'First slow note');
  const second = result.records.find(record => record.transcript === 'Second fast note');
  assert.ok(second.startedAt < first.endedAt, JSON.stringify(result.records));
  assert.ok(second.endedAt < first.endedAt, JSON.stringify(result.records));
  assert.equal(result.models.at(-1), 'typed-model');
});

test('real CLI status and stop use the private live job capability while the earlier planner waits', async t => {
  const result = await runCli(t, 'controls');
  assert.equal(result.records.length, 3, result.stdout);
  assert.equal(result.records.find(job => job.transcript === 'Slow research').status, 'cancelled');
  assert.equal(result.records.find(job => job.transcript === 'What is running?').status, 'done');
  assert.equal(result.records.find(job => job.transcript === 'Stop first task').status, 'done');
  assert.match(result.stdout, /PLAYED: First task is running/);
  assert.match(result.stdout, /PLAYED: First task stopped/);
  assert.equal(result.models.at(-1), 'typed-model');
});

test('ended voice and typed tool approvals share one prompt owner without stealing an answer', async t => {
  const result = await runCli(t, 'mixed-approval');
  assert.equal(result.promptsBeforeAnswer, 1, result.stdout);
  assert.equal(result.written, null, 'the first, voice permission was denied');
  assert.equal(result.typedWritten, true, 'the second, typed permission was approved');
});

for (const mode of ['empty-first', 'empty-final', 'empty-twice']) test(`CLI ${mode} retries an empty successful response once without repeating a file action`, async t => {
  const result = await runCli(t, mode);
  const task = result.records[0];
  assert.equal(task.status, mode === 'empty-twice' ? 'failed' : 'done', result.stdout);
  assert.equal(task.steps.filter(step => step.tool === 'write_file').length, mode === 'empty-twice' ? 0 : 1);
  assert.equal(result.models.filter(model => model === 'voice-model').length, mode === 'empty-twice' ? 2 : 3);
  assert.equal(result.models.at(-1), 'typed-model');
  if (mode === 'empty-twice') assert.match(task.error, /provider returned no answer or action after one recovery attempt/i);
});

for (const mode of ['end-running', 'clear-running']) test(`CLI ${mode} keeps work owned and its completed history separate from a typed turn`, async t => {
  const result = await runCli(t, mode);
  assert.equal(result.records[0].status, 'done', result.stdout);
  assert.equal(result.written, 'Workspace ready');
  assert.ok(!result.stdout.includes('PLAYED: Workspace tayyar hai.'), result.stdout);
  const autosave = result.history.find(item => item.name.includes('autosave'));
  assert.ok(autosave);
  const messages = autosave.messages.filter(message => message.role !== 'system');
  assert.deepEqual(messages.map(message => message.role), mode === 'clear-running' ? ['user', 'assistant'] : ['user', 'assistant', 'user', 'assistant']);
  if (mode === 'clear-running') assert.ok(result.history.some(item => item.name.includes('voice-') && item.messages.some(message => message.content === 'Workspace tayyar hai.')));
});

test('voice reply prepares interruption input during synthesis and discovers the microphone once per session', async t => {
  const result = await runCli(t, 'latency');
  assert.match(result.stdout, /PLAYED: Workspace tayyar hai\./);
  const opened = result.stdout.indexOf('BARGE_OPEN');
  const ready = result.stdout.indexOf('REPORT_SYNTH_READY');
  assert.ok(opened > 0 && opened < ready, result.stdout);
  assert.equal(result.stdout.split('MIC_DISCOVERY').length - 1, 1, result.stdout);
});

test('a disconnected interruption microphone is closed and does not suppress the spoken answer', async t => {
  const result = await runCli(t, 'latency-mic-failure');
  assert.match(result.stdout, /PLAYED: Workspace tayyar hai\./);
  assert.match(result.stdout, /BARGE_STOPPED/);
  assert.equal(result.stdout.split('MIC_DISCOVERY').length - 1, 2, 'failed input must force fresh discovery next turn');
});

test('cancelling during parallel reply preparation drops late audio and closes the microphone', async t => {
  const result = await runCli(t, 'latency-cancel');
  assert.ok(!result.stdout.includes('PLAYED: Workspace tayyar hai.'), result.stdout);
  assert.match(result.stdout, /BARGE_STOPPED/);
});

test('a failed microphone rediscovery stays inside voice mode and can recover on the next capture', async t => {
  const result = await runCli(t, 'capture-refresh-failure');
  assert.match(result.stdout, /mic: fixture discovery failed/);
  assert.match(result.stdout, /PLAYED: Workspace tayyar hai\./);
  assert.equal(result.records[0].status, 'done');
});

test('an overlong model reply is saved in full but spoken as only two sentences', async t => {
  const result = await runCli(t, 'verbose-reply');
  assert.equal(result.records[0].summary, 'Workspace tayyar hai. File is ready. Want anything else?');
  assert.match(result.stdout, /PLAYED: Workspace tayyar hai\. File is ready\.\n/);
  assert.ok(!result.stdout.includes('PLAYED: Workspace tayyar hai. File is ready. Want'), result.stdout);
});

for (const mode of ['success', 'narration', 'tts-failure', 'failure', 'output-limit', 'cancel', 'approval-cancel', 'tail-cancel']) test(`real CLI voice loop: ${mode}, saved task, then unchanged typed chat`, async t => {
  const result = await runCli(t, mode);
  assert.equal(result.records.length, 1);
  const task = result.records[0];
  assert.equal(task.status, ['success', 'narration', 'tts-failure'].includes(mode) ? 'done' : mode.includes('cancel') ? 'cancelled' : 'failed', JSON.stringify(task) + '\n' + result.stdout);
  assert.equal(task.transcript, 'Workspace kholo');
  assert.match(result.stdout, /PLAYED: Haan\./);
  assert.match(result.stdout, new RegExp(task.id));
  assert.match(result.stdout, /Hi from chat/);
  assert.equal(result.models.at(-1), 'typed-model');
  assert.ok(!result.models.includes('unwanted-tool-model'));
  assert.ok(!result.stdout.includes('HIDDEN REASONING'));
  assert.ok(!task.summary.includes('Intermediate tool preamble'));
  assert.ok(!result.stdout.includes('→ write_file'));
  if (['success', 'narration', 'tts-failure'].includes(mode)) {
    assert.equal(result.written, 'Workspace ready');
    if (mode !== 'narration') assert.match(result.stdout, /Permission chahiye/);
    assert.match(result.stdout, /PLAYED: Workspace tayyar hai/);
    if (mode === 'tts-failure') assert.match(result.stdout, /using Edge/);
    if (mode === 'narration') {
      const end = result.stdout.indexOf('ENDED: Your workspace note is saved.');
      assert.ok(end > 0, result.stdout);
      assert.ok(end < result.stdout.indexOf('PLAYED: Workspace tayyar hai.'), result.stdout);
      assert.ok(!result.stdout.includes('PLAYED: Write · write_file'));
      assert.ok(!result.stdout.includes("PLAYED: I'm writing your workspace note now."), 'the superseded writing update must be dropped');
    }
  } else if (mode === 'failure') {
    assert.match(task.error, /403/);
    assert.ok(!result.stdout.includes('token refreshed'));
  } else if (mode === 'output-limit') {
    assert.match(task.error, /output limit/);
    assert.ok(!task.error.includes('no final report'));
    assert.equal(result.written, null);
    assert.equal(result.models.filter(model => model === 'voice-model').length, 1);
    assert.match(result.stdout, /PLAYED: Work did not finish\. The model hit its output limit/);
  } else {
    assert.match(result.stdout, /PLAYED: Cancelled/);
    assert.ok(!result.stdout.includes('PLAYED: Workspace tayyar hai.'));
    if (mode === 'approval-cancel') {
      assert.ok(!result.stdout.includes('PLAYED: Permission'), result.stdout);
      assert.ok(!result.stdout.includes('allow?'), result.stdout);
      assert.equal(result.written, null);
    }
  }
});
