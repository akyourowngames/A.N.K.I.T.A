import * as createDir from "./create-dir.mjs";
import * as webSearch from "./web-search.mjs";
import * as webFetch from "./web-fetch.mjs";
import * as scrape from "./scrape.mjs";
import * as project from "./project.mjs";
import * as projectMemory from "./project-memory.mjs";
import * as schedule from "./schedule.mjs";
import * as watch from "./watch.mjs";
import * as githubNotifications from "./github-notifications.mjs";
import * as mcpManage from "./mcp-manage.mjs";

/**
 * The tools that are NOT sent on every request, grouped so one discovery call
 * loads a whole family and the obvious follow-up is already available.
 *
 * This lives apart from index.mjs on purpose: find_tools.mjs needs the
 * categories, and index.mjs needs find_tools, so putting both in one file
 * creates a cycle where a half-initialised namespace gets read.
 *
 * Keywords are matched with plain substring checks - no embeddings, no index.
 */
export const CATEGORIES = [
  {
    id: "web",
    summary: "search the internet, read pages, scrape blocked or JS-heavy sites",
    keywords: [
      "web", "search", "google", "internet", "online", "browse", "website", "url",
      "link", "docs", "documentation", "news", "latest", "current", "recent", "scrape",
      "crawl", "page", "lookup", "research",
    ],
    tools: [webSearch, webFetch, scrape],
  },
  {
    id: "automation",
    summary: "recurring routines and page watches that run while you are away",
    keywords: [
      "remind", "reminder", "recurring", "schedule", "cron", "daily", "weekly",
      "every morning", "every day", "routine", "watch", "monitor", "alert", "notify",
      "check every", "keep an eye",
    ],
    tools: [schedule, watch],
  },
  {
    id: "project",
    summary: "the projects you work on, and what you decided or still have to do",
    keywords: [
      "project", "client", "remember", "note", "decision", "decided", "todo",
      "backlog", "standup", "brief", "where does", "status of", "open items",
    ],
    tools: [project, projectMemory],
  },
  {
    id: "github",
    summary: "your GitHub inbox: notifications, mentions, review requests, invitations",
    keywords: [
      "github", "notification", "notifications", "mention", "mentions",
      "review request", "invitation", "inbox",
    ],
    tools: [githubNotifications],
  },
  {
    id: "mcp",
    summary: "add, list, remove or reload MCP servers (external tool providers)",
    keywords: [
      "mcp", "model context protocol", "server", "integrate", "plugin", "external tools",
      "connect a service", "tool server",
    ],
    tools: [mcpManage],
  },
  {
    id: "filesystem",
    summary: "create directories",
    keywords: ["mkdir", "directory", "folder", "create dir", "new dir"],
    tools: [createDir],
  },
];

export const deferredTools = CATEGORIES.flatMap((c) => c.tools);

export const specOf = (m) => ({
  type: "function",
  function: { name: m.name, description: m.description, parameters: m.parameters },
});

/** name -> full spec, for deferred tools only. */
export const deferredSpecByName = new Map(deferredTools.map((m) => [m.name, specOf(m)]));

/** name -> category id, so a match can activate a whole family. */
export const categoryOfTool = new Map(
  CATEGORIES.flatMap((c) => c.tools.map((m) => [m.name, c.id]))
);

export function findCategory(id) {
  return CATEGORIES.find((c) => c.id === id) || null;
}
