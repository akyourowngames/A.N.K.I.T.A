import { CATEGORIES, CATEGORIES as ALL, findCategory } from "./catalog.mjs";

export const name = "find_tools";
export const description =
  "Load extra tools that are not in your default set: searching the internet and scraping pages, " +
  "scheduled routines and page watches, project management and memory, GitHub notifications, and " +
  "directory creation. Call this first whenever a task needs one of those; the tools become callable " +
  "immediately afterwards.";

export const parameters = {
  type: "object",
  properties: {
    query: {
      type: "string",
      description:
        "What you want to do, in a few words - e.g. 'search the web', 'remind me daily', " +
        "'where does this project stand', 'my github notifications'.",
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
  for (const category of ALL) {
    if (category.id.toLowerCase() === q) hits.add(category.id);
    else if (category.keywords.some((k) => q.includes(k))) hits.add(category.id);
    // Tool names too, so "web_search" or "project_memory" also works.
    else if (category.tools.some((t) => q.includes(t.name.toLowerCase()))) hits.add(category.id);
  }
  return [...hits];
}

function catalogue() {
  return CATEGORIES.map((c) => `  ${c.id.padEnd(12)} ${c.summary}`).join("\n");
}

/** The activated set, created lazily like state.jobs and state.todos. */
function activated(state) {
  if (!state) return null;
  state.activatedTools ??= new Set();
  return state.activatedTools;
}

export function run(args = {}, ctx = {}) {
  const set = activated(ctx.state);
  const query = String(args.query ?? "").trim();

  if (!query) {
    return `Tell me what you want to do and I will load the right tools.\nGroups you can load:\n${catalogue()}`;
  }

  const matched = matchCategories(query);
  if (!matched.length) {
    // Never guess which family was meant - show them all and ask again.
    return (
      `Nothing matched "${query}". Every group you can load:\n${catalogue()}\n\n` +
      "Call find_tools again with one of those words."
    );
  }

  const loaded = [];
  const already = [];
  for (const id of matched) {
    for (const tool of findCategory(id).tools) {
      if (set && !set.has(tool.name)) {
        set.add(tool.name);
        loaded.push(tool.name);
      } else {
        already.push(tool.name);
      }
    }
  }

  const summaries = matched.map((id) => {
    const c = findCategory(id);
    return `  ${c.id}: ${c.summary}`;
  });

  return (
    `Loaded ${matched.join(", ")}.\n${summaries.join("\n")}` +
    (loaded.length ? `\nNow callable: ${loaded.join(", ")}.` : "") +
    (already.length && !loaded.length ? `\nAlready loaded: ${already.join(", ")}.` : "")
  );
}
