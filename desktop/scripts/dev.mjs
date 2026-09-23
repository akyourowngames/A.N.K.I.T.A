import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const viteBin = path.join(root, 'node_modules/vite/bin/vite.js');
const electronBin = path.join(root, 'node_modules/electron/cli.js');
const url = 'http://127.0.0.1:5173';
const vite = spawn(process.execPath, [viteBin, '--config', 'desktop/vite.config.ts'], { cwd: root, stdio: 'inherit', windowsHide: true });
let electron = null;
const stop = () => { vite.kill(); electron?.kill(); };
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
vite.on('exit', () => electron?.kill());

for (let attempt = 0; attempt < 100; attempt++) {
  try { const response = await fetch(url); if (response.ok) break; } catch {}
  if (attempt === 99) throw new Error('Vite did not start');
  await new Promise(resolve => setTimeout(resolve, 150));
}
electron = spawn(process.execPath, [electronBin, '.'], {
  cwd: root, stdio: 'inherit', windowsHide: true,
  env: { ...process.env, ANKITA_DESKTOP_DEV_URL: url },
});
electron.on('exit', code => { vite.kill(); process.exitCode = code || 0; });
