import { parentPort, workerData } from 'node:worker_threads';

const modules = {
  search_files: '../../tools/filesystem/search-files.mjs',
  glob: '../../tools/filesystem/glob.mjs',
  list_dir: '../../tools/filesystem/list-dir.mjs',
  read_file: '../../tools/filesystem/read-file.mjs',
};

try {
  const modulePath = modules[workerData.name];
  if (!modulePath) throw new Error('Unsupported filesystem tool');
  const tool = await import(modulePath);
  parentPort.postMessage({ result: await tool.run(workerData.args, { cwd: workerData.cwd }) });
} catch (error) {
  parentPort.postMessage({ error: error.message });
}
