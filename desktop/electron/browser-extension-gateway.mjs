import http from 'node:http';
import { AsyncLocalStorage } from 'node:async_hooks';
import { randomBytes, timingSafeEqual } from 'node:crypto';
import { McpServer, createMcpHandler } from '@modelcontextprotocol/server';
import { toNodeHandler } from '@modelcontextprotocol/node';
import { LOOPBACK_HOST } from '../browser-helper/protocol.mjs';
import { BROWSER_EXTENSION_MCP_ID, BROWSER_EXTENSION_TOOL, CONTROL_MAX_RESULT_BYTES } from '../browser-helper/control-protocol.mjs';

const CAPABILITY_BYTES = 32; // Random bytes: ephemeral native MCP capability never shared with webpages.
const EPHEMERAL_PORT = 0; // OS chooses an unused local port; reconnect reads the new endpoint from the desktop owner.
const WIRE_VERSION = '1.0.0'; // This bridge's MCP implementation version, independent of app releases.
const RPC_LIST = 'tools/list', RPC_CALL = 'tools/call';
const requests = new AsyncLocalStorage(); // HTTP socket cancellation stays bound to its own command, not the receiver session.

export async function createBrowserExtensionGateway(browser) {
  const capability = '/' + randomBytes(CAPABILITY_BYTES).toString('base64url');
  const handler = createMcpHandler(() => {
    const mcp = new McpServer({ name: BROWSER_EXTENSION_MCP_ID, version: WIRE_VERSION }, { capabilities: { tools: {} } });
    mcp.server.setRequestHandler(RPC_LIST, async () => ({ tools: [{ name: BROWSER_EXTENSION_TOOL, description: 'Execute an owned browser operation through the paired Ankita extension.',
      inputSchema: { type: 'object', properties: { operation: { type: 'object' } }, required: ['operation'], additionalProperties: false } }] }));
    mcp.server.setRequestHandler(RPC_CALL, async (request, extra) => {
      try {
        if (request.params.name !== BROWSER_EXTENSION_TOOL) throw new Error('Unknown extension browser tool');
        const result = await browser.execute(request.params.arguments?.operation, { signal: requests.getStore()?.signal || extra?.signal });
        return { content: [{ type: 'text', text: JSON.stringify({ result }) }] };
      } catch (error) { return { isError: true, content: [{ type: 'text', text: JSON.stringify({ error: { message: error.message, dispatched: error.dispatched === true } }) }] }; }
    });
    return mcp;
  }, { maxRequestBodySize: CONTROL_MAX_RESULT_BYTES });
  const nodeHandler = toNodeHandler(handler, { maxRequestBodySize: CONTROL_MAX_RESULT_BYTES });
  const server = http.createServer((request, response) => {
    const supplied = Buffer.from(request.url || ''), expected = Buffer.from(capability);
    if (request.headers.host !== `${LOOPBACK_HOST}:${server.address().port}` || request.headers.origin || supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) {
      response.writeHead(403); response.end(); return;
    }
    response.setHeader('Cache-Control', 'no-store');
    const controller = new AbortController();
    response.once('close', () => { if (!response.writableFinished) controller.abort(); });
    void requests.run({ signal: controller.signal }, () => nodeHandler(request, response)).catch(() => { if (!response.headersSent) response.writeHead(500); response.end(); });
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(EPHEMERAL_PORT, LOOPBACK_HOST, resolve); });
  return { url: `http://${LOOPBACK_HOST}:${server.address().port}${capability}`, async close() {
    browser.close(); await handler.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  } };
}
