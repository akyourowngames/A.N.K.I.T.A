import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-config-source-'));
process.env.CONFIG_DIR = path.join(root, 'runtime');
test.after(() => fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));
const { loadConfig, CONFIG_DIR, GLOBAL_ENV_FILE, PROFILE_FILE } = await import('../../src/core/config.mjs');

test('a read-only global configuration source preserves provider layers without changing runtime storage', () => {
  const original = path.join(root, 'original');
  fs.mkdirSync(original, { recursive: true });
  const source = path.join(original, path.basename(GLOBAL_ENV_FILE));
  fs.writeFileSync(source, 'PROVIDER=custom\nAPI_BASE=https://fixture.test/v1\nAPI_KEY=fixture-global-key\n');
  const project = path.join(root, 'project.env');
  fs.writeFileSync(project, 'MODEL=fixture-model\n');
  const baseline = loadConfig(project);
  const loaded = loadConfig(project, { globalEnvFile: source });
  assert.equal(loaded.provider, 'custom');
  assert.equal(loaded.apiBase, 'https://fixture.test/v1');
  assert.equal(loaded.apiKey, 'fixture-global-key');
  assert.equal(CONFIG_DIR, process.env.CONFIG_DIR);
  assert.equal(path.dirname(PROFILE_FILE), CONFIG_DIR);
  assert.equal(loadConfig(project).provider, baseline.provider);
  fs.writeFileSync(project, 'PROVIDER=kilo\nAPI_KEY=fixture-project-key\n');
  const override = loadConfig(project, { globalEnvFile: source });
  assert.equal(override.provider, 'kilo');
  assert.equal(override.apiKey, 'fixture-project-key');
});
