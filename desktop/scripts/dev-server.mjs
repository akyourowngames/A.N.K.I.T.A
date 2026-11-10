import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { createServer } from 'vite';
import { terminateProcessTree } from './process-tree.mjs';

const ROOT = fileURLToPath(new URL('../../', import.meta.url)); // This checkout owns both the renderer and Electron host.
const VITE_CONFIG = 'desktop/vite.config.ts'; // Checkout-relative Vite configuration; never a user profile path.
const APP_ARGUMENTS = ['.']; // Electron loads the same checkout's package entry point.
const require = createRequire(import.meta.url);

/** Start one owned renderer and host. Closing either releases the other. */
export async function startDesktopDev({ root = ROOT, electronPath = require('electron'), electronArgs = APP_ARGUMENTS,
  env = process.env, stdio = 'inherit', logLevel } = {}) {
  const server = await createServer({ configFile: path.join(root, VITE_CONFIG),
    server: { strictPort: false }, ...(logLevel ? { logLevel } : {}) }); // Vite selects a free port; the host receives only this owned server's URL.
  let electron, childDone, closing;
  const close = () => closing ??= (async () => {
    if (electron) await terminateProcessTree(electron);
    await server.close();
    await childDone;
  })();
  try {
    await server.listen();
    const url = server.resolvedUrls?.local?.[0];
    if (!url) throw new Error('The desktop renderer did not publish a local address');
    // A terminal that itself runs under Electron (some editors set this for
    // their own helper processes) leaks ELECTRON_RUN_AS_NODE into children.
    // Inheriting it starts the host as plain Node, so `import { BrowserWindow }
    // from 'electron'` resolves to the npm stub and the app dies at boot.
    // This child is always the real desktop window, so the flag is never wanted.
    const { ELECTRON_RUN_AS_NODE: _runAsNode, ...hostEnv } = env;
    electron = spawn(electronPath, electronArgs, { cwd: root, stdio, windowsHide: true,
      detached: process.platform !== 'win32', // POSIX: own the whole group so shutdown stops Chromium children too.
      env: { ...hostEnv, ANKITA_DESKTOP_DEV_URL: url } });
    childDone = new Promise(resolve => electron.once('close', (code, signal) => resolve({ code, signal })));
    const closed = childDone.then(async result => { await close(); return result; });
    void closed.catch(() => {}); // Startup failures still clean up even before a caller receives these handles.
    await new Promise((resolve, reject) => { electron.once('spawn', resolve); electron.once('error', reject); });
    return { server, electron, url, close, closed };
  } catch (error) { await close(); throw error; }
}
