import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import * as client from '../../src/integrations/mcp-client.mjs';

test('only the Electron-owned MCP executable receives Node mode, even if overridden in extra env', () => {
  const runtime = { execPath: path.resolve('packaged-app.exe'), electron: true };
  const env = client.mcpLaunchEnv(runtime.execPath, { ELECTRON_RUN_AS_NODE: '0' }, runtime);
  assert.equal(env.ELECTRON_RUN_AS_NODE, '1');
  assert.equal(env.CI, '1');
  assert.equal(client.mcpLaunchEnv(path.resolve('other-server.exe'), {}, runtime).ELECTRON_RUN_AS_NODE, undefined);
  assert.equal(client.mcpLaunchEnv(runtime.execPath, {}, { ...runtime, electron: false }).ELECTRON_RUN_AS_NODE, undefined);
});
