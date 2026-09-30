import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { chromeMcpCommand, CHROME_MCP_VERSION } from '../../src/integrations/browser-plugins.mjs';

test('Chrome bridge uses the packaged runtime and pinned dependency rather than npm or cache discovery', () => {
  const launch = chromeMcpCommand({ connection: 'port', port: 9333 });
  assert.equal(launch.command, process.execPath);
  assert.ok(fs.statSync(launch.args[0]).isFile());
  assert.match(launch.args[0].replaceAll('\\', '/'), /chrome-devtools-mcp\/build\/src\/bin\/chrome-devtools-mcp\.js$/);
  assert.equal(launch.args.includes('-y'), false);
  assert.equal(launch.args.at(-1), '--browserUrl=http://127.0.0.1:9333');
  assert.ok(CHROME_MCP_VERSION);
});
