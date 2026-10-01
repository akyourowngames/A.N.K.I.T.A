import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';

const pkg = JSON.parse(readFileSync(fileURLToPath(new URL('../package.json', import.meta.url)), 'utf8'));

export default defineConfig({
  root: fileURLToPath(new URL('./renderer', import.meta.url)),
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // The island is a second window with its own entry page.
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL('./renderer/index.html', import.meta.url)),
        island: fileURLToPath(new URL('./renderer/island.html', import.meta.url)),
      },
    },
  },
  // The renderer imports the shared version module from ../shared, which is
  // outside its root, so the dev server has to be allowed to serve it.
  server: { host: '127.0.0.1', port: 5173, strictPort: true, fs: { allow: [fileURLToPath(new URL('..', import.meta.url))] } },
  // The window's own version, so it can tell whether the main process it is
  // talking to was built from the same commit.
  define: { __ANKITA_VERSION__: JSON.stringify(pkg.version || '0.0.0') },
});
