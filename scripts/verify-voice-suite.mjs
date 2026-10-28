/** Serial Windows-safe regression scope for voice's shared core, channels, automation and desktop hosts. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TEST_ROOTS = ['test/core', 'test/channels', 'test/automation', 'test/desktop']; // Existing host contracts touched by voice; excludes ignored generated website fixtures.
const TEST_SUFFIX = '.test.mjs'; // Repository test-file contract.
const collect = directory => fs.readdirSync(path.join(ROOT, directory), { withFileTypes: true }).flatMap(entry => {
  const relative = path.join(directory, entry.name);
  return entry.isDirectory() ? collect(relative) : entry.name.endsWith(TEST_SUFFIX) ? [relative] : [];
});
const files = TEST_ROOTS.flatMap(collect).sort();
const result = spawnSync(process.execPath, ['--test', '--test-concurrency=1', ...files], { cwd: ROOT, stdio: 'inherit', windowsHide: true });
if (result.error) console.error(result.error.message);
process.exitCode = result.status ?? 1;
