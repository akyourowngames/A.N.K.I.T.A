import { Worker } from 'node:worker_threads';

const FILE_TOOLS = new Set(['search_files', 'glob', 'list_dir', 'read_file']);

/** Run synchronous filesystem tools away from Electron's main event loop. */
export function runFileToolInWorker(name, args, { cwd, signal } = {}) {
  if (!FILE_TOOLS.has(name)) throw new Error(`Unsupported worker tool: ${name}`);
  if (signal?.aborted) return Promise.reject(new Error('Filesystem inspection cancelled'));
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('./tool-worker-runner.mjs', import.meta.url), {
      workerData: { name, args, cwd }, execArgv: [],
    });
    let settled = false;
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener('abort', cancel);
      void worker.terminate();
      if (error) reject(error);
      else resolve(value);
    };
    const cancel = () => finish(new Error('Filesystem inspection cancelled'));
    signal?.addEventListener('abort', cancel, { once: true });
    worker.once('message', message => message.error ? finish(new Error(message.error)) : finish(null, message.result));
    worker.once('error', error => finish(error));
    worker.once('exit', code => { if (!settled) finish(new Error(`Filesystem worker exited (${code})`)); });
    if (signal?.aborted) cancel();
  });
}
