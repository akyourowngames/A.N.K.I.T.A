import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { McpClient } from '../src/mcp-client.mjs';
import { McpManager } from '../src/mcp-manager.mjs';
import { matchCategories } from '../tools/find-tools.mjs';
import * as composioTool from '../tools/composio.mjs';
import { mcpPromptLines } from '../src/agent.mjs';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ComposioStore } from '../src/composio-store.mjs';

async function server(handler) {
  const app = http.createServer(handler);
  await new Promise(resolve => app.listen(0, '127.0.0.1', resolve));
  return { url: `http://127.0.0.1:${app.address().port}/mcp`, close: () => new Promise(resolve => app.close(resolve)) };
}

test('HTTP MCP handles JSON, SSE, session header, and trusted manager tools', async () => {
  const seen = [];
  const app = await server(async (req, res) => {
    let body = '';
    for await (const chunk of req) body += chunk;
    const message = JSON.parse(body);
    seen.push({ message, headers: req.headers });
    if (!('id' in message)) { res.writeHead(202).end(); return; }
    if (message.method === 'initialize') res.setHeader('mcp-session-id', 'sid-1');
    const result = message.method === 'initialize' ? { protocolVersion: '2025-11-25', serverInfo: { name: 'test' } }
      : message.method === 'tools/list' ? { tools: [{ name: 'COMPOSIO_SEARCH_TOOLS', inputSchema: { type: 'object' } }] }
      : { content: [{ type: 'text', text: 'done' }] };
    const reply = { jsonrpc: '2.0', id: message.id, result };
    if (message.method === 'tools/call') {
      res.writeHead(200, { 'content-type': 'text/event-stream' });
      res.end(`event: message\ndata: ${JSON.stringify({ jsonrpc: '2.0', id: 999, result: {} })}\n\ndata: ${JSON.stringify(reply)}\n\n`);
    } else res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify(reply));
  });
  const manager = new McpManager();
  try {
    await manager.connect({ id: 'composio', transport: 'http', url: app.url, headers: { authorization: 'Bearer test' }, trusted: true, alwaysOn: true });
    assert.equal(manager.specs()[0].function.name, 'mcp__composio__COMPOSIO_SEARCH_TOOLS');
    assert.equal(manager.needsApproval('mcp__composio__COMPOSIO_SEARCH_TOOLS'), false);
    assert.deepEqual(manager.alwaysOnIds(), ['composio']);
    assert.equal(await manager.callTool('mcp__composio__COMPOSIO_SEARCH_TOOLS', {}), 'done');
    assert.equal(seen[1].message.method, 'notifications/initialized');
    assert.equal(seen[2].headers['mcp-session-id'], 'sid-1');
    assert.equal(seen[3].headers.authorization, 'Bearer test');
  } finally { await manager.closeAll(); await app.close(); }
});

test('Composio stays mounted through ordinary MCP reconcile and is discoverable', async () => {
  const app = await server(async (req, res) => {
    let body = '';
    for await (const chunk of req) body += chunk;
    const msg = JSON.parse(body);
    if (msg.id === undefined) { res.writeHead(202).end(); return; }
    const result = msg.method === 'tools/list' ? { tools: [{ name: 'COMPOSIO_SEARCH_TOOLS', inputSchema: { type: 'object' } }] } : { protocolVersion: '2025-11-25' };
    res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify({ jsonrpc: '2.0', id: msg.id, result }));
  });
  const manager = new McpManager();
  try {
    await manager.connect({ id: 'composio', transport: 'http', url: app.url, trusted: true, alwaysOn: true, synthetic: true });
    await manager.reconcile({ enabled: [], isApproved: () => false });
    assert.equal(manager.has('composio'), true);
    assert.ok(matchCategories('send an email').includes('connectors'));
    assert.equal(composioTool.needsApproval, false);
  } finally { await manager.closeAll(); await app.close(); }
});

test('connected Composio adds the meta-tool workflow to the prompt', () => {
  assert.equal(mcpPromptLines([]).some(line => line.includes('COMPOSIO_SEARCH_TOOLS')), false);
  const lines = mcpPromptLines([{ id: 'composio', deferred: false, tools: ['COMPOSIO_SEARCH_TOOLS'] }]);
  assert.ok(lines.some(line => line.includes('COMPOSIO_SEARCH_TOOLS') && line.includes('COMPOSIO_MULTI_EXECUTE_TOOL')));
});

test('ensureComposio replaces an endpoint when its direct session disappears', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'composio-mcp-'));
  const store = new ComposioStore(path.join(dir, 'state.json')).load();
  const manager = new McpManager();
  let missing = false;
  const fetchImpl = async (url, init = {}) => {
    const address = String(url);
    if (address.includes('/auth_configs?')) return Response.json({ items: [] });
    if (address.includes('backend.composio.dev')) {
      if (address.endsWith('/session/s1') && missing) return Response.json({}, { status: 404 });
      const id = missing ? 's2' : 's1';
      return Response.json({ session_id: id, mcp: { type: 'http', url: `https://app.composio.dev/${id}/mcp` }, config: { user_id: 'ankita_test', multi_account: { enable: true }, auth_configs: {} } });
    }
    const msg = JSON.parse(init.body);
    if (msg.id === undefined) return new Response(null, { status: 202 });
    const result = msg.method === 'tools/list' ? { tools: [] } : { protocolVersion: '2025-11-25' };
    return Response.json({ jsonrpc: '2.0', id: msg.id, result });
  };
  try {
    const cfg = { composioApiKey: 'ak_test' };
    assert.match((await manager.ensureComposio(cfg, store, fetchImpl)).url, /s1\/mcp$/);
    missing = true;
    assert.match((await manager.ensureComposio(cfg, store, fetchImpl)).url, /s2\/mcp$/);
  } finally { await manager.closeAll(); fs.rmSync(dir, { recursive: true, force: true }); }
});
