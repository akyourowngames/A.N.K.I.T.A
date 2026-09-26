import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import { PassThrough, Writable } from 'node:stream';
import { Worker, isMainThread, parentPort, workerData } from 'node:worker_threads';
import { cleanupFailedLauncher, killTree, trackJobTree } from './_job-tree.mjs';

// Executable candidates preserve PowerShell 7 semantics, then the existing
// Windows PowerShell fallback. Resolve them off the owner's event loop too.
const WINDOWS_SHELL_CANDIDATES = ['pwsh', 'powershell.exe'];
const WINDOWS_EXECUTABLE_LOOKUP = 'where';
const WINDOWS_EXECUTABLE_EXTENSION = '.exe';
const SHELL_LOOKUP_OPTIONS = { windowsHide: true, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] };
const SHELL_LOOKUP_LINES = /[^\r\n]+/g;
const LAUNCHER_WORKER_KIND = 'windows-job-launcher'; // Brand only our own workerData; ordinary tool imports are inert.
const CLOSED_STDIN_ERROR = 'Job stdin is closed.';
// Shared protocol names keep stream acknowledgements and lifecycle replies in
// sync between the owner and worker. Each stream has only one chunk in flight.
const MESSAGE = {
  resolved: 'resolved', spawn: 'spawn', tracked: 'tracked', output: 'output', ack: 'ack', input: 'input',
  eof: 'eof', inputDone: 'input-done', stdinError: 'stdin-error', exit: 'exit', close: 'close', error: 'error',
  terminate: 'terminate', terminated: 'terminated', kill: 'kill',
};
let cachedShell;

function resolveShell() {
  for (const candidate of WINDOWS_SHELL_CANDIDATES) {
    const result = spawnSync(WINDOWS_EXECUTABLE_LOOKUP, [candidate], SHELL_LOOKUP_OPTIONS);
    if (result.status !== 0) continue;
    for (const executable of String(result.stdout ?? '').match(SHELL_LOOKUP_LINES) || []) {
      if (!path.isAbsolute(executable) || path.extname(executable).toLowerCase() !== WINDOWS_EXECUTABLE_EXTENSION) continue;
      try { if (fs.statSync(executable).isFile()) return executable; }
      catch { /* Ignore stale resolver entries. */ }
    }
  }
  return WINDOWS_SHELL_CANDIDATES.at(-1);
}

/** ChildProcess-compatible pipes/events with native Windows work off-loop. */
class JobProcess extends EventEmitter {
  constructor(args, options) {
    super();
    this.pid = undefined;
    this.exitCode = null;
    this.signalCode = null;
    this.stdout = new PassThrough();
    this.stderr = new PassThrough();
    this.pending = new Map();
    this.pendingInput = new Map();
    this.requestId = 0;
    this.closed = false;
    this.ready = new Promise(resolve => { this.started = resolve; });
    this.identityReady = new Promise(resolve => { this.identified = resolve; });
    this.worker = new Worker(new URL(import.meta.url), { execArgv: [], workerData: { kind: LAUNCHER_WORKER_KIND, args, options, executable: cachedShell } });
    this.stdin = new Writable({
      write: (data, encoding, done) => this.sendInput(MESSAGE.input, data, done),
      final: done => this.sendInput(MESSAGE.eof, undefined, done),
    });
    this.worker.on('message', message => this.receive(message));
    this.worker.once('error', error => this.fail(error));
    this.worker.once('exit', code => {
      if (!this.closed) this.fail(new Error(`Job launcher exited unexpectedly (${code}).`));
      for (const entry of this.pending.values()) entry.reject(new Error('Job launcher exited before termination completed.'));
      this.pending.clear();
    });
  }

  post(message) { if (!this.closed) this.worker.postMessage(message); }

  sendInput(type, data, done) {
    if (this.closed) { done(new Error(CLOSED_STDIN_ERROR)); return; }
    const id = ++this.requestId;
    this.pendingInput.set(id, done);
    this.post({ type, data, id });
  }

  closeInput(error) {
    const callbacks = [...this.pendingInput.values()];
    this.pendingInput.clear();
    for (const done of callbacks) done(error);
    this.stdin.destroy(error);
  }

  receive(message) {
    if (message.type === MESSAGE.resolved) { this.shellExecutable = cachedShell = message.executable; }
    else if (message.type === MESSAGE.spawn) { this.pid = message.pid; this.started(this.pid); this.emit('spawn'); }
    else if (message.type === MESSAGE.tracked) { this.treeSnapshot = message.snapshot; this.identified(this.treeSnapshot); }
    else if (message.type === MESSAGE.output) {
      const stream = this[message.stream];
      const acknowledge = () => this.post({ type: MESSAGE.ack, stream: message.stream });
      if (stream.write(Buffer.from(message.data))) acknowledge();
      else stream.once('drain', acknowledge);
    } else if (message.type === MESSAGE.inputDone) {
      const done = this.pendingInput.get(message.id);
      this.pendingInput.delete(message.id);
      done?.(message.error ? new Error(message.error) : undefined);
    } else if (message.type === MESSAGE.stdinError) this.closeInput(new Error(message.error));
    else if (message.type === MESSAGE.exit) {
      this.exitCode = message.code; this.signalCode = message.signal;
      if (message.snapshot) this.treeSnapshot = message.snapshot;
      this.emit('exit', message.code, message.signal);
    } else if (message.type === MESSAGE.close) {
      this.closed = true;
      this.started(this.pid);
      this.identified(this.treeSnapshot);
      this.stdout.end(); this.stderr.end();
      this.closeInput(this.pendingInput.size ? new Error(CLOSED_STDIN_ERROR) : undefined);
      this.emit('close', message.code, message.signal);
      this.worker.unref();
    } else if (message.type === MESSAGE.error) this.emit('error', new Error(message.error));
    else if (message.type === MESSAGE.terminated) {
      const entry = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) entry?.reject(new Error(message.error));
      else entry?.resolve();
    }
  }

  async fail(error) {
    if (this.failing) return;
    this.failing = true;
    this.started(this.pid);
    this.identified(this.treeSnapshot);
    if (this.pid && !this.closed) {
      // This exceptional path runs in the owner because its launch worker is
      // gone. Verify its cached creation identity before using tree cleanup.
      const child = { pid: this.pid, exitCode: null, signalCode: null, kill: signal => process.kill(this.pid, signal) };
      try { await cleanupFailedLauncher(child, this.treeSnapshot); }
      catch (cleanupError) { error = new Error(`${error.message} Cleanup failed: ${cleanupError.message}`); }
    }
    this.emit('error', error);
    if (!this.closed) this.receive({ type: MESSAGE.close, code: this.exitCode, signal: this.signalCode });
  }

  async terminateTree() {
    // Stop may arrive before native CreateProcess returns its PID. Keep the
    // worker alive until then, so an unfinished launch cannot orphan a child.
    await this.ready;
    if (this.closed || !this.pid) return;
    const id = ++this.requestId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.post({ type: MESSAGE.terminate, id });
    });
  }

  kill(signal) { this.post({ type: MESSAGE.kill, signal }); return !this.closed; }
}

export function spawnWindowsJob(args, options) { return new JobProcess(args, options); }

function launch() {
  const executable = workerData.executable || resolveShell();
  parentPort.postMessage({ type: MESSAGE.resolved, executable });
  const child = spawn(executable, workerData.args, { ...workerData.options, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
  let closed = false;
  let terminating = 0;
  const finish = () => { if (closed && !terminating) parentPort.close(); };
  child.once('spawn', () => parentPort.postMessage({ type: MESSAGE.spawn, pid: child.pid }));
  let treeSnapshot;
  void trackJobTree(child).then(snapshot => {
    treeSnapshot = snapshot;
    if (!closed) parentPort.postMessage({ type: MESSAGE.tracked, snapshot });
  });
  for (const stream of ['stdout', 'stderr']) child[stream].on('data', data => {
    child[stream].pause();
    parentPort.postMessage({ type: MESSAGE.output, stream, data });
  });
  child.stdin.on('error', error => parentPort.postMessage({ type: MESSAGE.stdinError, error: error.message }));
  child.once('error', error => parentPort.postMessage({ type: MESSAGE.error, error: error.message }));
  child.once('exit', (code, signal) => parentPort.postMessage({ type: MESSAGE.exit, code, signal, snapshot: treeSnapshot }));
  child.once('close', (code, signal) => {
    closed = true;
    parentPort.postMessage({ type: MESSAGE.close, code, signal });
    finish();
  });
  parentPort.on('message', async message => {
    try {
      const inputDone = error => parentPort.postMessage({ type: MESSAGE.inputDone, id: message.id, error: error?.message });
      if (message.type === MESSAGE.input) child.stdin.write(Buffer.from(message.data), inputDone);
      else if (message.type === MESSAGE.eof) child.stdin.end(inputDone);
      else if (message.type === MESSAGE.ack) child[message.stream].resume();
      else if (message.type === MESSAGE.kill) child.kill(message.signal);
      else if (message.type === MESSAGE.terminate) {
        terminating++;
        try { await killTree(child); parentPort.postMessage({ type: MESSAGE.terminated, id: message.id }); }
        catch (error) { parentPort.postMessage({ type: MESSAGE.terminated, id: message.id, error: error.message }); }
        finally { terminating--; finish(); }
      }
    } catch (error) {
      const input = message.type === MESSAGE.input || message.type === MESSAGE.eof;
      parentPort.postMessage({ type: input ? MESSAGE.inputDone : MESSAGE.error, id: message.id, error: error.message });
    }
  });
}

if (!isMainThread && workerData?.kind === LAUNCHER_WORKER_KIND) launch();
