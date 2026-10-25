import fs from "node:fs";
import { ProjectStore } from "./projects.mjs";
import { withFileLock } from "./file-lock.mjs";

/**
 * Writes what a finished turn did into its project.
 *
 * Deterministic by design: the work log and todo sync cost no model call. The
 * optional extraction pass is the only part that does, and it is off by default.
 * Every failure is swallowed into the return value - a turn must never break
 * because bookkeeping failed.
 */

export const WORKLOG_SUMMARY_FILES = 5;
export const TODO_TEXT_CAP = 500;

function normalize(text) {
  return String(text ?? "").trim().replace(/\s+/g, " ").toLocaleLowerCase();
}

function workSummary(audit) {
  const files = (audit.files || []).slice(0, WORKLOG_SUMMARY_FILES);
  const parts = [audit.termination || "done", `${(audit.files || []).length} file(s)`];
  if (files.length) parts.push(files.join(", "));
  return parts.join(" · ");
}

/**
 * Session checklist versus stored project todos. Only explicit status changes
 * count: pending/in_progress items become additions, completed/cancelled ones
 * close the matching open project todo.
 */
export function planTodoSync(project, todos, maxAdd = 5) {
  const open = new Map((project.todos || []).filter((todo) => !todo.done).map((todo) => [normalize(todo.text), todo]));
  const add = new Map();
  const close = new Set();
  for (const todo of todos || []) {
    if (!todo || typeof todo.content !== "string") continue;
    const text = todo.content.trim().slice(0, TODO_TEXT_CAP);
    if (!text) continue;
    const key = normalize(text);
    if (todo.status === "completed" || todo.status === "cancelled") {
      const match = open.get(key);
      if (match) close.add(match.id);
      continue;
    }
    if (todo.status === "pending" || todo.status === "in_progress") {
      if (!open.has(key) && !add.has(key)) add.set(key, text);
    }
  }
  return { add: [...add.values()].slice(0, Math.max(0, maxAdd)), close: [...close] };
}

function journalChars(file) {
  const raw = JSON.parse(fs.readFileSync(file, "utf8"));
  return (raw.messages || []).reduce((total, message) => total + String(message.content || "").length, 0);
}

export async function maintainTurn({
  projectId,
  audit = null,
  todos = [],
  sessionId = null,
  turnId = null,
  journalFile = null,
  config = {},
  projectsFile = null,
  consolidator = null,
  log = () => {},
} = {}) {
  if (config.projectAutoMaintenance === false) return { written: 0, skipped: "disabled" };
  if (!projectId || !projectsFile) return { written: 0, skipped: "no-project" };

  let written = 0;
  try {
    const stored = new ProjectStore(projectsFile).load();
    const project = stored.find(projectId);
    if (!project || project.archived) return { written: 0, skipped: "no-project" };

    const sync = planTodoSync(project, todos, config.projectTodoSyncMax ?? 5);
    const hasWork = Boolean(audit?.changed) || sync.add.length > 0 || sync.close.length > 0;
    if (!hasWork) return { written: 0, skipped: "no-work" };

    const held = withFileLock(`${projectsFile}.lock`, () => {
      const store = new ProjectStore(projectsFile).load();
      if (!store.find(projectId)) return 0;
      let count = 0;
      if (audit?.changed) {
        const result = store.appendWorkLog(projectId, {
          text: workSummary(audit),
          source: { kind: "auto-worklog", sessionId, turnId },
          cap: config.projectWorklogMax ?? undefined,
        });
        if (result && !result.error) count++;
      }
      for (const text of sync.add) {
        const result = store.addTodo(projectId, text, { kind: "auto-todo", sessionId });
        if (result && !result.error) count++;
      }
      for (const id of sync.close) {
        const result = store.completeTodo(projectId, id, { kind: "auto-todo", sessionId });
        if (result && !result.error) count++;
      }
      return count;
    });
    if (held === undefined) return { written: 0, skipped: "locked" };
    written = held;

    // The opt-in extraction pass runs in the background: the user already has
    // their reply and must not wait for another model call.
    if (config.projectInlineConsolidation === true && consolidator && journalFile && config.memoryConsolidation !== false) {
      try {
        const chars = journalChars(journalFile);
        if (chars >= (config.projectInlineMinChars ?? 400)) {
          void consolidator
            .runSession(journalFile, {
              projectId,
              sessionId,
              memorySource: { kind: "auto-consolidation", sessionId, turnId },
            })
            .catch((error) => log(`inline consolidation failed: ${error.message}`));
        }
      } catch (error) {
        log(`inline consolidation skipped: ${error.message}`);
      }
    }
    return { written };
  } catch (error) {
    log(`project maintenance failed: ${error.message}`);
    return { written, error: error.message };
  }
}
