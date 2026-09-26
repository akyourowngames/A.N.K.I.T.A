import { Worker } from 'node:worker_threads';

const FILE_TOOLS = new Set(['search_files', 'glob', 'list_dir', 'read_file']);
const pending = new Map();
let worker = null, retiring = null, active = null, nextId = 0;

function settle(id, error, result) {
  const entry = pending.get(id);
  if (!entry) return;
  pending.delete(id);
  clearTimeout(entry.timer);
  entry.signal?.removeEventListener('abort', entry.onAbort);
  if (active === id) active = null;
  if (error) entry.reject(new Error(error));
  else entry.resolve(result);
}

// Terminate the thread, not merely its promise: a synchronous regex cannot
// observe AbortSignal, and would otherwise block every later inspection.
function retire() {
  const dead = worker;
  worker = null;
  if (!dead) return;
  dead.removeAllListeners();
  retiring = dead.terminate().catch(() => {}).finally(() => { retiring = null; pump(); });
}

function pump() {
  if (active !== null || retiring) return;
  const entry = pending.values().next().value;
  if (!entry) { worker?.unref(); return; }
  active = entry.id;
  try {
    if (!worker) {
      const created = new Worker(new URL('./tool-worker-pool-runner.mjs', import.meta.url), { execArgv: [] });
      worker = created;
      const fatal = reason => {
        if (worker !== created) return;
        settle(active, reason);
        retire();
      };
      created.on('error', error => fatal(`Filesystem worker failed: ${error.message}`));
      created.on('exit', code => fatal(`Filesystem worker exited (${code})`));
      created.on('message', message => {
        if (worker !== created || message?.ready || message?.id !== active) return;
        settle(message.id, message.error, message.result);
        pump();
      });
    }
    worker.ref();
    entry.timer = setTimeout(() => {
      if (active !== entry.id) return;
      settle(entry.id, `Filesystem inspection timed out after ${entry.timeoutMs}ms. Narrow the search or simplify the regex.`);
      retire();
    }, entry.timeoutMs);
    worker.postMessage({ id: entry.id, name: entry.name, args: entry.args, cwd: entry.cwd, workspacePath: entry.workspacePath });
  } catch (error) { settle(entry.id, error.message); retire(); pump(); }
}

/** Resident worker, serial bounded calls, and automatic recovery after Stop. */
export function runFileToolInWorker(name, args, { cwd, workspacePath, signal, timeoutMs = 5000 } = {}) {
  if (!FILE_TOOLS.has(name)) throw new Error(`Unsupported worker tool: ${name}`);
  if (signal?.aborted) return Promise.reject(new Error('Filesystem inspection cancelled'));
  if (pending.size >= 128) return Promise.reject(new Error('Filesystem inspection queue is full'));
  const deadline = Number.isFinite(timeoutMs) && timeoutMs > 0 ? Math.min(timeoutMs, 30000) : 5000;
  return new Promise((resolve, reject) => {
    const id = ++nextId;
    const onAbort = () => {
      const running = active === id;
      settle(id, 'Filesystem inspection cancelled');
      if (running) retire();
      pump();
    };
    pending.set(id, { id, name, args, cwd, workspacePath, signal, onAbort, resolve, reject, timeoutMs: deadline });
    signal?.addEventListener('abort', onAbort, { once: true });
    if (signal?.aborted) onAbort();
    else pump();
  });
}

export function shutdownFileToolWorkers() {
  for (const id of [...pending.keys()]) settle(id, 'Filesystem worker shut down');
  retire();
}
