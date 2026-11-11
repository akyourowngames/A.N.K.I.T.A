import { CATEGORIES, CATEGORIES as ALL, findCategory } from "./catalog.mjs";
import { managedMcpSummaries } from '../src/integrations/browser-routing.mjs';
import { focusAllows, setToolFocus, BROWSER_DISCOVERY_GUIDANCE } from '../src/core/tool-focus.mjs';
import { loadSkills } from '../src/core/skills.mjs';
import { SUBAGENT_TOOL, SUBAGENT_CONTROL_TOOL } from '../src/core/subagents/registry.mjs';
import { SKILL_MANAGER_CATEGORY } from '../src/skills/manager.mjs';

const SKILL_LIST_LIMIT = 50; // Count/skills: bounds discovery output for large custom roots.
const SKILL_DESCRIPTION_CHARS = 160; // Characters/description; full instructions stay behind the skill tool.
const SKILL_OUTPUT_CHARS = 4000; // Characters/skill block: keeps discovery within one bounded tool result.

export const name = "find_tools";
export const description =
  "Discover tools for browser, web, files, Git, processes, schedules, apps and memory; accepted tools become available immediately. " + BROWSER_DISCOVERY_GUIDANCE;

export const parameters = {
  type: "object",
  properties: {
    scope: { type: 'string', enum: ['focus', 'general'], description: 'For browser focus use exactly query="browser", scope="focus". Focus accepts only the browser group and retains memory/checklist/skills/discovery. General restores other tools in this same conversation.' },
    query: {
      type: "string",
      description:
        "What you want to do, in a few words - e.g. 'search the web', 'remind me daily', " +
        "'where does this project stand', 'my github notifications'. For browser use exactly 'browser'; broad phrases can match unrelated groups.",
    },
  },
  required: ["query"],
};

export const readOnly = true;
export const needsApproval = false;

/** Which categories a query matches. Pure, so it is testable. */
export function matchCategories(query) {
  const q = String(query ?? "").toLowerCase().trim();
  if (!q) return [];
  const hits = new Set();
  const contains = key => new RegExp(`(^|[^a-z0-9])${key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}($|[^a-z0-9])`).test(q);
  for (const category of ALL) {
    // The built-in GitHub inbox owns notification queries; loading the connected
    // app manager as well would add an unrelated schema to that request.
    if (category.id === "connectors" && /\bnotifications?\b/.test(q) && /\bgithub\b/.test(q)) continue;
    if (category.id.toLowerCase() === q) hits.add(category.id);
    else if (category.keywords.some(contains)) hits.add(category.id);
    // Tool names too, so "web_search" or "project_memory" also works.
    else if (category.tools.some((t) => contains(t.name.toLowerCase()))) hits.add(category.id);
  }
  return [...hits];
}

const WORDS = (text) =>
  String(text ?? "")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((w) => w.length > 2);

/**
 * Which connected MCP servers a query matches - by server id, by a word in it
 * ("playwright" finds "playwright-mcp"), or by a word in a tool name, so
 * "open a browser page" finds a server offering browser_navigate.
 *
 * Only ever given the held-back servers, so a loose match costs one load of
 * something the model asked about, not a wrong action. Pure, so it is
 * testable without a manager.
 */
export function matchMcpServers(query, servers = []) {
  const q = String(query ?? "").toLowerCase().trim();
  if (!q) return [];
  const asked = new Set(WORDS(q));
  if (!asked.size) return [];

  return servers
    .filter((s) => {
      const id = String(s.id || "").toLowerCase();
      if (!id) return false;
      if (q.includes(id)) return true;
      if (WORDS(id).some((w) => asked.has(w))) return true;
      const toolWords = (s.tools || []).flatMap((t) => WORDS(t));
      return toolWords.some((w) => asked.has(w));
    })
    .map((s) => s.id);
}

/** Installed skill names/descriptions make name-based selection possible without guessing. */
function skillCatalogue(ctx) {
  if (ctx.skillsEnabled === false) return '';
  const disabled = ctx.disabledSkills;
  const skills = loadSkills().filter(skill => !disabled?.has?.(skill.name) && !disabled?.includes?.(skill.name));
  const lines = [];
  let used = 0;
  for (const skill of skills.slice(0, SKILL_LIST_LIMIT)) {
    const line = `  ${skill.name}: ${skill.description.slice(0, SKILL_DESCRIPTION_CHARS)}`;
    if (used + line.length + 1 > SKILL_OUTPUT_CHARS) break;
    used += line.length + 1;
    lines.push(line);
  }
  return lines.length ? `\nInstalled skills (call skill with a name):\n${lines.join('\n')}` : '';
}

function catalogue(mcpServers = [], skillsEnabled = true, categories = CATEGORIES) {
  const builtIn = categories.filter(c => skillsEnabled || !['skills', SKILL_MANAGER_CATEGORY].includes(c.id))
    .map((c) => `  ${c.id.padEnd(12)} ${c.summary}`);
  const external = mcpServers.map(
    (s) => `  ${String(s.id).padEnd(12)} MCP server - ${s.tools.length} tool(s): ${s.tools.slice(0, 6).join(", ")}`
  );
  return [...builtIn, ...external].join("\n");
}

/** The activated set, created lazily like state.jobs and state.todos. */
function activated(state) {
  if (!state) return null;
  state.activatedTools ??= new Set();
  return state.activatedTools;
}

export function run(args = {}, ctx = {}) {
  if (args.scope !== undefined && !['focus', 'general'].includes(args.scope)) return 'Error: tool scope must be focus or general. Tool access was not changed.';
  // An explicit exit must work even when the desired tool is core or the query misses.
  const restored = args.scope === 'general' ? setToolFocus(ctx.state, 'general', []) : '';
  const set = activated(ctx.state);
  const query = String(args.query ?? "").trim();
  const skillsEnabled = ctx.skillsEnabled !== false;
  // Discovery must agree with execution: background and child agents have no
  // runSubagent host, so they must not be told delegation is now callable.
  const allowed = tool => (!ctx.toolAvailability || ctx.toolAvailability.has(tool)) &&
    (tool !== SUBAGENT_TOOL || typeof ctx.runSubagent === 'function') &&
    (tool !== SUBAGENT_CONTROL_TOOL || typeof ctx.subagentControl === 'function');
  const categories = CATEGORIES.filter(category => (skillsEnabled || !['skills', SKILL_MANAGER_CATEGORY].includes(category.id)) && category.tools.some(tool => allowed(tool.name)));
  // Only held-back servers need loading; a small one is already in the request.
  const connected = ctx.mcp?.summaries() || [];
  const available = (ctx.browserManager ? managedMcpSummaries(connected) : connected)
    .map(server => ({ ...server, tools: server.tools.filter(tool => allowed(`mcp__${server.id}__${tool}`)) })).filter(server => server.tools.length);
  const held = ctx.toolAvailability ? available : available.filter((s) => s.deferred);

  if (!query) {
    return `${restored ? restored + '\n' : ''}Tell me what you want to do and I will load the right tools.\nGroups you can load:\n${catalogue(held, skillsEnabled, categories)}`;
  }

  const matched = matchCategories(query).filter(id => categories.some(category => category.id === id));
  const servers = matchMcpServers(query, held);
  const requestedTools = [...matched.flatMap(id => findCategory(id).tools.filter(tool => allowed(tool.name)).map(tool => tool.name)),
    ...available.filter(server => servers.includes(server.id)).flatMap(server => server.tools.map(tool => `mcp__${server.id}__${tool}`))];
  const browserTools = new Set(findCategory('browser').tools.map(tool => tool.name));
  if (args.scope === 'focus' && ctx.config?.browserToolFocus === true && (!requestedTools.length || requestedTools.some(name => !browserTools.has(name)))) {
    return 'Error: Browser focus requires only the browser group. Call find_tools(query="browser", scope="focus") to enter it, or use scope="general" for another group. No tools were loaded.';
  }
  if (args.scope !== 'general' && requestedTools.some(name => !focusAllows(ctx.state, name))) {
    return 'Error: This group is outside the current tool focus. Call find_tools(scope="general", query=the needed group) first. No tools were loaded and focus was not changed.';
  }
  if (!matched.length && !servers.length) {
    if (ctx.toolAvailability) return `${restored ? restored + '\n' : ''}Nothing matched "${query}" on this native app. Callable groups here:\n${catalogue(held, skillsEnabled, categories)}\nOther tool groups require their separately connected ChatGPT MCP app. Discovery here cannot add their interfaces to this app.`;
    // Never guess which family was meant - show them all and ask again. But a
    // miss usually means the capability is not here at all, so point at the one
    // place it might be bought in from, rather than dead-ending.
    return (
      `${restored ? restored + '\n' : ''}Nothing matched "${query}". Everything you can load right now:\n${catalogue(held, skillsEnabled, categories)}\n\n` +
      "Tip: booking, shopping, and media playback can usually be done directly in " +
      "a website - load the `browser` group with find_tools and drive the site. " +
      "If instead you need a whole capability that is not in that list - " +
      "a specific database or design tool - load the `mcp` group and search the MCP registry " +
      'with mcp_manage action="search". For Gmail, Slack, Notion and other connected apps, ' +
      "load `connectors` and use `/composio connect <app>`. Ask the user before installing " +
      "an MCP server."
    );
  }

  const loaded = [];
  const already = [];
  for (const id of matched) {
    for (const tool of findCategory(id).tools.filter(tool => allowed(tool.name))) {
      if (findCategory(id).alwaysOn) { already.push(tool.name); continue; }
      if (set && !set.has(tool.name)) {
        set.add(tool.name);
        loaded.push(tool.name);
      } else {
        already.push(tool.name);
      }
    }
  }

  // A whole MCP server is loaded by remembering its id; the agent turns that
  // into specs on the next request.
  const serversLoaded = [];
  for (const id of servers) {
    if (set && !set.has(`mcp:${id}`)) {
      set.add(`mcp:${id}`);
      serversLoaded.push(id);
    } else {
      already.push(id);
    }
  }

  const summaries = matched.map((id) => {
    const c = findCategory(id);
    return `  ${c.id}: ${c.summary}`;
  });
  for (const id of servers) {
    const s = held.find((x) => x.id === id);
    summaries.push(`  ${id}: MCP server - ${s ? s.tools.length : "?"} tool(s)`);
  }

  const fromMcp = available.filter((s) => servers.includes(s.id));
  const mcpTools = fromMcp.flatMap((s) => s.tools.map((t) => `mcp__${s.id}__${t}`));
  const focus = restored || (ctx.config?.browserToolFocus === true ? setToolFocus(ctx.state, args.scope, requestedTools) : '');
  // Notify the chat's skill loader only after discovery passed the focus boundary.
  ctx.onToolsActivated?.(requestedTools);

  return (
    `Loaded ${[...matched, ...servers].join(", ")}.\n${summaries.join("\n")}` + (focus ? `\n${focus}` : '') +
    (loaded.length ? `\nNow callable: ${loaded.join(", ")}.` : "") +
    (mcpTools.length ? `\nNow callable: ${mcpTools.join(", ")}.` : "") +
    (already.length && !loaded.length && !serversLoaded.length
      ? `\nAlready loaded: ${already.join(", ")}.`
      : "") +
    (matched.includes('skills') ? skillCatalogue(ctx) : '')
  );
}
