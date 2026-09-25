import { PROJECTS_FILE, STATE_FILE } from "../../src/core/config.mjs";
import { ProjectStore, since, MAX_NOTES } from "../../src/memory/projects.mjs";
import { RoutineStore } from "../../src/automation/routines.mjs";
import { formatDuration } from "../../src/automation/cron.mjs";

export const name = "project_memory";
export const description =
  "Remember things about a project: notes, decisions, and open todos. Use it when the user " +
  "tells you something worth keeping ('remember we chose X because Y'), asks what is left to do, " +
  "or asks where a project stands. `log` shows the timeline; `brief` hands you everything needed " +
  "to catch the user up. Defaults to the active project. " +
  "Actions: note, decide, todo, done, log, brief.";

export const parameters = {
  type: "object",
  properties: {
    action: { type: "string", description: "note, decide, todo, done, log, or brief." },
    name: { type: "string", description: "Project name or id. Defaults to the active project." },
    text: { type: "string", description: "For note/decide/todo: what to remember." },
    ref: {
      type: "string",
      description: "For done: the todo's id (t1), its number among the open ones, or part of its text.",
    },
  },
  required: ["action"],
};

export const needsApproval = false;

function store(ctx = {}) {
  return new ProjectStore(ctx.projectsFile || PROJECTS_FILE).load();
}

function pickProject(s, args, ctx) {
  const wanted = args.name || ctx.projectId || null;
  if (!wanted) {
    const known = s.projects.map((p) => p.id);
    return {
      error: known.length
        ? `No project is active and none was named. Ask which one, or use one of: ${known.join(", ")}.`
        : "There are no projects yet. Ask the user whether to add one first.",
    };
  }
  const project = s.find(wanted);
  if (!project) {
    const known = s.projects.map((p) => p.id);
    return { error: `No project "${wanted}".${known.length ? ` Known: ${known.join(", ")}.` : ""}` };
  }
  return { project };
}

const counts = (project) => {
  const m = { notes: 0, decisions: 0, open: 0, done: 0 };
  m.notes = (project.notes || []).length;
  m.decisions = (project.decisions || []).length;
  for (const t of project.todos || []) (t.done ? m.done++ : m.open++);
  return m;
};

const summaryLine = (project) => {
  const c = counts(project);
  return `${project.name} — ${c.notes} note(s), ${c.decisions} decision(s), ${c.open} open (${c.done} done)`;
};

/** Compact one-liners for the things tagged with this project. */
function taggedItems(projectId) {
  const store_ = new RoutineStore(STATE_FILE).load();
  const watches = store_.watches.filter((w) => w.projectId === projectId).map((w) => {
    const value = w.lastValue ?? (w.lastChecked ? "(page tracked)" : "never checked");
    const when = w.lastChecked ? since(w.lastChecked) : "never";
    return `${w.name}   every ${formatDuration(w.intervalMs)}   last ${value} (${when})`;
  });
  const routines = store_.routines.filter((r) => r.projectId === projectId).map((r) => {
    const status = r.lastStatus ? `${r.lastStatus} ${since(r.lastRun)}` : "not run yet";
    return `${r.name}   ${r.cron}   last ${status}`;
  });
  return { watches, routines };
}

export function run(args = {}, ctx = {}) {
  const s = store(ctx);
  if (s.conflicts.length) return `Error: project state conflict: ${s.conflicts.join('; ')}`;
  const action = String(args.action || "log").toLowerCase();
  const found = pickProject(s, args, ctx);
  if (found.error) return `Error: ${found.error}`;
  const project = found.project;

  if (action === "note" || action === "decide" || action === "todo") {
    if (!args.text) return `Error: 'text' is required to add a ${action}.`;
    const written =
      action === "note"
        ? s.addNote(project.id, args.text, ctx.memorySource)
        : action === "decide"
          ? s.addDecision(project.id, args.text, ctx.memorySource)
          : s.addTodo(project.id, args.text, ctx.memorySource);
    if (!written) return `Error: no project "${project.id}".`;
    if (written.error) return `Error: ${written.error}.`;

    const c = counts(written);
    const kind = action === "decide" ? "Decision" : action === "todo" ? "Todo" : "Note";
    const extra = action === "todo" ? ` [${written.todos.at(-1).id}]` : "";
    return (
      `${kind} recorded on "${written.name}"${extra}: ${String(args.text).trim()}\n` +
      `(${c.notes} note(s), ${c.decisions} decision(s), ${c.open} open)` +
      (c.notes >= MAX_NOTES ? `\nNote: only the ${MAX_NOTES} most recent notes are kept.` : "")
    );
  }

  if (action === "done") {
    const result = s.completeTodo(project.id, args.ref);
    if (!result) return `Error: no project "${project.id}".`;
    if (result.error) {
      const open = (project.todos || []).filter((t) => !t.done);
      const list = open.map((t, i) => `  [${i + 1}] ${t.text}  (${t.id})`).join("\n");
      return `Error: ${result.error}.${list ? `\nOpen items:\n${list}` : ""}`;
    }
    const c = counts(result.project);
    return `Closed "${result.closed.text}" on "${result.project.name}". ${c.open} still open.`;
  }

  if (action === "log") {
    const c = counts(project);
    if (!c.notes && !c.decisions && !(c.open + c.done)) {
      return (
        `Nothing remembered about "${project.name}" yet.\n` +
        "As you work, use action=note for things worth keeping, decide for choices, todo for open items."
      );
    }
    const lines = [summaryLine(project), ""];

    const open = (project.todos || []).filter((t) => !t.done);
    if (open.length) {
      lines.push("open");
      open.forEach((t, i) => lines.push(`  [${i + 1}] ${t.text}   (${t.id}, ${since(t.at)})`));
      lines.push("");
    }
    if (c.decisions) {
      lines.push("decisions");
      for (const d of project.decisions.slice(-8)) lines.push(`  ${since(d.at).padEnd(9)} ${d.text}`);
      if (c.decisions > 8) lines.push(`  (+${c.decisions - 8} older)`);
      lines.push("");
    }
    if (c.notes) {
      lines.push("notes");
      for (const n of project.notes.slice(-10)) lines.push(`  ${since(n.at).padEnd(9)} ${n.text}`);
      if (c.notes > 10) lines.push(`  (+${c.notes - 10} older)`);
      lines.push("");
    }
    const done = (project.todos || []).filter((t) => t.done).slice(-5);
    if (done.length) {
      lines.push("done");
      for (const t of done) lines.push(`  ${since(t.doneAt).padEnd(9)} ${t.text}`);
    }
    return lines.join("\n").trimEnd();
  }

  if (action === "brief") {
    const c = counts(project);
    const { watches, routines } = taggedItems(project.id);
    const missing = s.missingFor(project);
    const open = (project.todos || []).filter((t) => !t.done);

    const blocks = [
      `Write ${ctx.config?.username || "the user"} a short brief on the project "${project.name}", catching them up as if you had been working on it together. Use only what is below; invent nothing.`,
      'Keep the evidence labels: stored project records are RECORDED, not CONFIRMED current facts. Only current file, git, test, or tool observations may be called CONFIRMED; otherwise say UNKNOWN. Do not infer deployment health from notes.',
      "",
      "RECORDED",
      "WHAT IT IS",
      `  summary  ${project.summary || "(not recorded yet)"}`,
      project.path ? `  path     ${project.path}` : null,
      `  status   ${project.status || "active"}${project.archived ? " (archived)" : ""}`,
      project.client ? `  client   ${project.client}` : null,
      project.conventions?.length ? `  conventions  ${project.conventions.join("; ")}` : null,
      missing.length ? `  still unknown: ${missing.join(", ")}` : null,
      "",
    ].filter((l) => l !== null);

    if (open.length) {
      blocks.push("OPEN ITEMS");
      open.forEach((t, i) => blocks.push(`  [${i + 1}] ${t.text}   (opened ${since(t.at)})`));
      blocks.push("");
    } else {
      blocks.push("OPEN ITEMS", "  none recorded", "");
    }

    if (c.decisions) {
      blocks.push("DECISIONS");
      for (const d of project.decisions.slice(-6)) blocks.push(`  (${since(d.at)}) ${d.text}`);
      blocks.push("");
    }
    if (c.notes) {
      blocks.push("RECENT NOTES");
      for (const n of project.notes.slice(-8)) blocks.push(`  (${since(n.at)}) ${n.text}`);
      blocks.push("");
    }
    if (watches.length) {
      blocks.push("ITS WATCHES", ...watches.map((w) => `  ${w}`), "");
    }
    if (routines.length) {
      blocks.push("ITS ROUTINES", ...routines.map((r) => `  ${r}`), "");
    }

    blocks.push(
      'UNKNOWN',
      '  current production health and whether recorded tasks remain unfinished without a fresh check',
      '',
      "Write 3-6 sentences, or a few short bullets. Cover where it stands, what is open, and one thing worth doing next.",
      "Name the project once. Address the user by name once, naturally. If there is little recorded yet, say so plainly instead of padding."
    );
    return blocks.join("\n");
  }

  return `Error: unknown action "${action}". Use note, decide, todo, done, log, or brief.`;
}
