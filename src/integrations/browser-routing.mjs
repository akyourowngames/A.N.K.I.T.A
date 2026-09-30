import { parseToolName } from './mcp-manager.mjs';

// Playwright's browser_* and Chrome DevTools' page/snapshot contract identify
// browser servers independently of user-assigned MCP server IDs.
const BROWSER_TOOL_PREFIX = 'browser_';
const CHROME_PAGE_TOOLS = ['list_pages', 'navigate_page'];
export const MANAGED_BROWSER_REQUIRED = 'Error: Use the built-in browser tool for this desktop session. External browser MCP tools cannot share its tabs, refs, secure sign-in or live preview. Continue with browser; never reuse external refs.';

function browserServer(server) {
  const names = (server?.tools || []).map(tool => typeof tool === 'string' ? tool : tool.name);
  return names.includes('take_snapshot') && CHROME_PAGE_TOOLS.some(name => names.includes(name));
}
export function isBrowserMcpTool(name, servers = []) {
  const parsed = parseToolName(name);
  if (!parsed) return false;
  return parsed.toolName.startsWith(BROWSER_TOOL_PREFIX) || browserServer(servers.find(server => server.id === parsed.serverId));
}
export function managedMcpSummaries(servers = []) {
  return servers.map(server => ({ ...server, tools: browserServer(server) ? [] : server.tools.filter(name => !name.startsWith(BROWSER_TOOL_PREFIX)) })).filter(server => server.tools.length);
}
