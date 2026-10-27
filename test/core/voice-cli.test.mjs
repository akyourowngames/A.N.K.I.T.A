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
  const server = http.createServer(async (request, response) => {
    response.setHeader('Content-Type', 'application/json');
    if (request.url.endsWith('/models')) { response.end(JSON.stringify({ data: [{ id: 'typed-model', context_length: 131072, supported_parameters: ['tools'] }] })); return; }
    let raw = ''; for await (const chunk of request) raw += chunk;
    const body = JSON.parse(raw); models.push(body.model);
    if (mode === 'failure' && body.model === 'voice-model') { response.statusCode = 403; response.end('Planner access denied'); return; }
    const voice = body.model === 'voice-model';
    if (voice) {
      assert.equal(body.reasoning_effort, 'low'); assert.ok(body.max_tokens >= 400);
      assert.match(body.messages[0].content, /one or two short sentences/);
    } else assert.ok(!body.messages[0].content.includes('Voice conversation:'));
    const tool = voice && !body.messages.some(message => message.role === 'tool');
    if (voice && !tool && ['narration', 'tail-cancel'].includes(mode)) await new Promise(resolve => setTimeout(resolve, 100));
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
    `AUTO_APPROVE=${['narration', 'tail-cancel'].includes(mode) || BARGE_MODES.has(mode) ? 'on' : 'off'}`, `VOICE_BARGE_IN=${BARGE_MODES.has(mode) ? 'on' : 'off'}`, 'VOICE_HFP_ROUTING=off', 'MEMORY_CONSOLIDATION=off',
    'VOICE_SPEECH_GAP_MS=5',
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
      transcribeAudio: async () => ({ text: capture++ ? 'exit' : 'Workspace kholo', languageCode: 'hi-IN', confidence: 0.99 }),
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
      narrate: async () => "I'm writing your workspace note now.",
      playMp3: async (audio, {signal} = {}) => {
        console.log('PLAYED: ' + audio.toString());
        const tail = ${JSON.stringify(mode)} === 'tail-cancel' && audio.toString().includes('writing your workspace note');
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
  child.stdout.on('data', data => {
    stdout += data;
    const seen = stdout.split('CAPTURE_READY').length - 1;
    while (captures < seen) { captures++; child.stdin.write('\n'); }
    if (!approval && stdout.includes('allow?')) { approval = true; child.stdin.write('y\n'); }
    if (!typed && (stdout.includes('leaving voice mode') || stdout.includes('VOICE_IO_PROBE') || stdout.includes('voice needs SARVAM_API_KEY'))) {
      typed = true; child.stdin.end('Say hello\n/task\n/exit\n');
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
  return { stdout, models, records, written: fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : null };
}

test('CLI voice devices can be supplied without opening a physical microphone', async t => {
  const result = await runCli(t, 'probe');
  assert.match(result.stdout, /VOICE_IO_PROBE/);
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

for (const mode of ['success', 'narration', 'tts-failure', 'failure', 'cancel', 'approval-cancel', 'tail-cancel']) test(`real CLI voice loop: ${mode}, saved task, then unchanged typed chat`, async t => {
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
      const end = result.stdout.indexOf("ENDED: I'm writing your workspace note now.");
      assert.ok(end > 0, result.stdout);
      assert.ok(end < result.stdout.indexOf('PLAYED: Workspace tayyar hai.'), result.stdout);
      assert.ok(!result.stdout.includes('PLAYED: Write · write_file'));
    }
  } else if (mode === 'failure') {
    assert.match(task.error, /403/);
    assert.ok(!result.stdout.includes('token refreshed'));
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
