import test from 'node:test';
import assert from 'node:assert/strict';
import { McpClient } from '../../src/integrations/mcp-client.mjs';
import { McpManager } from '../../src/integrations/mcp-manager.mjs';
import { configuredSecrets, redactText } from '../../src/core/redact.mjs';

function connected(options = {}) {
  const client = new McpClient({ requestTimeoutMs: 100, ...options });
  client.child = { stdin: { write() {}, end() {} } };
  return client;
}

test('an oversized MCP response without a newline closes the transport and rejects requests', async () => {
  const client = connected({ maxMessageBytes: 64 });
  const pending = client.callTool('read');
  client._onStdout(Buffer.alloc(65, 120));
  await assert.rejects(pending, /message.*64.*bytes/i);
  assert.equal(client.closed, true);
  assert.equal(client.buffer, '');
  assert.equal(client.pending.size, 0);
});

test('a complete oversized MCP message is rejected before dispatch', async () => {
  const client = connected({ maxMessageBytes: 64 });
  const pending = client.callTool('read');
  client._onStdout(Buffer.from(JSON.stringify({ id: 1, result: 'x'.repeat(80) }) + '\n'));
  await assert.rejects(pending, /message.*64.*bytes/i);
  assert.equal(client.closed, true);
});

test('stdout bounds apply per message and decode UTF8 split across chunks', async () => {
  const client = connected({ maxMessageBytes: 64 });
  const pending = client.request('read');
  const bytes = Buffer.from(JSON.stringify({ id: 1, result: '雪 😀' }) + '\n');
  const split = bytes.indexOf(Buffer.from('雪')) + 1;
  client._onStdout(bytes.subarray(0, split));
  client._onStdout(Buffer.concat([bytes.subarray(split), Buffer.from('{}\n'.repeat(100))]));
  assert.equal(await pending, '雪 😀');
  assert.equal(client.closed, false);
  await client.close();
});

test('MCP stderr redacts configured and generic credentials across chunk boundaries', () => {
  const lines = [];
  const client = connected({ env: { SERVICE_TOKEN: 'configured-secret' }, headers: { 'x-api-key': 'header-secret' }, onStderr: line => lines.push(line) });
  client._onStderr(Buffer.from('connected token=configured-'));
  assert.deepEqual(lines, []);
  client._onStderr(Buffer.from('secret header-secret Authorization: Bearer credential-value\n'));
  const logged = lines.join('\n');
  assert.ok(!logged.includes('configured-secret'));
  assert.ok(!logged.includes('header-secret'));
  assert.ok(!logged.includes('credential-value'));
  assert.ok(logged.includes('[REDACTED]'));
});

test('an oversized stderr line is discarded through its newline without leaking its tail', () => {
  const lines = [];
  const client = connected({ maxStderrLineBytes: 32, onStderr: line => lines.push(line) });
  client._onStderr(Buffer.from('token=' + 'x'.repeat(40)));
  client._onStderr(Buffer.from('secret-tail\nnormal line\n'));
  assert.ok(!lines.join('\n').includes('secret-tail'));
  assert.ok(!lines.join('\n').includes('xxxx'));
  assert.ok(lines.some(line => line.includes('normal line')));
  assert.ok(client.stderrBuffer.length <= 32);
});

test('MCP approval details redact credentials in arguments and server launch details', () => {
  const manager = new McpManager();
  manager.servers.set('test', {
    id: 'test', command: 'server', args: ['--token', 'configured-secret'],
    env: { SERVICE_TOKEN: 'configured-secret' }, headers: { 'x-api-key': 'header-secret' },
    tools: [{ name: 'write', annotations: {} }],
  });
  const detail = manager.approvalDetail('mcp__test__write', { password: 'user-password', nested: { apiKey: 'nested-key' }, content: 'header-secret' });
  for (const secret of ['configured-secret', 'header-secret', 'user-password', 'nested-key']) assert.ok(!detail.includes(secret), `detail exposed ${secret}`);
  assert.ok(detail.includes('"content"'));
  assert.ok(detail.includes('[REDACTED]'));
});

test('redaction handles generic credentials and JSON-escaped configured values', () => {
  const configured = 'opaque"value\\ending';
  const input = JSON.stringify({ content: configured, password: 'space secret', api_key: 'api-value' })
    + ' https://user:pass@example.com/?token=query-value --secret cli-value Basic YWJjZA==';
  const result = redactText(input, { secrets: [configured] });
  for (const value of ['opaque', 'space secret', 'api-value', 'user:pass', 'query-value', 'cli-value', 'YWJjZA==']) assert.ok(!result.includes(value));
});
test('redaction preserves ordinary command descriptions containing credential words', () => {
  const text = '$ echo sample-token  (yields after 5 seconds; returns a job ID if still running)';
  assert.equal(redactText(text), text);
});

test('stderr flush preserves split UTF8 and redacts multiline configured secrets', () => {
  const lines = [];
  const client = connected({ env: { PRIVATE_KEY: 'first-private-line\nsecond-private-line' }, onStderr: line => lines.push(line) });
  const bytes = Buffer.from('雪 first-private-line\nsecond-private-line');
  client._onStderr(bytes.subarray(0, 1));
  client._onStderr(bytes.subarray(1));
  client._flushStderr();
  assert.equal(lines.length, 2);
  assert.ok(lines[0].startsWith('雪 '));
  assert.ok(!lines.join('\n').includes('private-line'));
  assert.ok(configuredSecrets({ PRIVATE_KEY: 'a\nb' }).includes('b'));
});

test('oversized stdout closes a spawned MCP server during initialization', async t => {
  const client = new McpClient({
    command: process.execPath,
    args: ['-e', 'process.stdin.on("data", () => process.stdout.write("x".repeat(65)))'],
    maxMessageBytes: 64, initTimeoutMs: 2000,
  });
  t.after(() => client.close());
  await assert.rejects(client.connect(), /message.*64.*bytes/i);
  assert.equal(client.closed, true);
  assert.equal(client.pending.size, 0);
});
