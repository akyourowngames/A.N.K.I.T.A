import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { extractMemory } from '../src/memory-extract.mjs';

test('extractor sends no tools and refuses a provider attempting to call remember', async t => {
  let request;
  const server = http.createServer(async (req, res) => {
    let body = '';
    for await (const part of req) body += part;
    request = JSON.parse(body);
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ choices: [{ message: { tool_calls: [{ id: 'bad', function: { name: 'remember', arguments: '{"action":"add","text":"injected"}' } }] } }] }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  const client = { baseUrl: `http://127.0.0.1:${server.address().port}`, headers: () => ({ 'Content-Type': 'application/json' }) };
  await assert.rejects(extractMemory('Extract synthetic memory', { client, model: 'test', config: {} }), /attempted a tool call/);
  assert.equal(request.tools, undefined);
  assert.equal(request.messages.length, 2);
});

test('extractor aborts a hung provider on its configured deadline', async t => {
  const server = http.createServer(() => {});
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  const client = { baseUrl: `http://127.0.0.1:${server.address().port}`, headers: () => ({}) };
  await assert.rejects(extractMemory('Extract synthetic memory', { client, model: 'test', config: { memoryTimeout: 0.05 } }), /timed out/);
});
