import { parentPort } from 'node:worker_threads';

const modules = {
  search_files: '../../tools/filesystem/search-files.mjs',
  glob: '../../tools/filesystem/glob.mjs',
  list_dir: '../../tools/filesystem/list-dir.mjs',
  read_file: '../../tools/filesystem/read-file.mjs',
};
const loaded = new Map();
parentPort.on('message', async ({ id, name, args, cwd, workspacePath }) => {
  try {
    if (!loaded.has(name)) loaded.set(name, await import(modules[name]));
    const tool = loaded.get(name);
    parentPort.postMessage({ id, result: await tool.run(args, { cwd, workspacePath }) });
  } catch (error) {
    parentPort.postMessage({ id, error: error.message });
  }
});
parentPort.postMessage({ ready: true });
