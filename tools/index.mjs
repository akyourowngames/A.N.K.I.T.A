import * as runCommand from "./run-command.mjs";
import * as readFile from "./read-file.mjs";
import * as writeFile from "./write-file.mjs";
import * as editFile from "./edit-file.mjs";
import * as editLines from "./edit-lines.mjs";
import * as listDir from "./list-dir.mjs";
import * as searchFiles from "./search-files.mjs";
import * as glob from "./glob.mjs";
import * as moveFile from "./move-file.mjs";
import * as deleteFile from "./delete-file.mjs";
import * as fetchUrl from "./fetch-url.mjs";
import * as jobStatus from "./job-status.mjs";
import * as jobStop from "./job-stop.mjs";
import * as writeTodos from "./write-todos.mjs";
import * as findTools from "./find-tools.mjs";
import { killTree, waitForExit } from "./run-command.mjs";
import { CATEGORIES, deferredTools, deferredSpecByName, categoryOfTool, specOf } from "./catalog.mjs";

/**
 * The tools almost every task needs, sent on every request. Deliberately short:
 * every schema here is paid on every turn, forever.
 */
export const CORE = [
  readFile,
  writeFile,
  editFile,
  editLines,
  listDir,
  searchFiles,
  glob,
  moveFile,
  deleteFile,
  runCommand,
  jobStatus,
  jobStop,
  writeTodos,
  fetchUrl,
  findTools,
];

const byName = new Map([...CORE, ...deferredTools].map((m) => [m.name, m]));

/** Every tool, core and deferred alike. Used by the daemon and --config. */
export const tools = [...byName.values()];

export const specs = tools.map(specOf);

export const coreSpecs = CORE.map(specOf);

export { CATEGORIES, deferredSpecByName, categoryOfTool };

export function get(name) {
  return byName.get(name);
}

export function names() {
  return tools.map((m) => m.name);
}

export function coreNames() {
  return CORE.map((m) => m.name);
}

/** Full specs for a set of deferred tool names. */
export function specsFor(names) {
  return names.map((n) => deferredSpecByName.get(n)).filter(Boolean);
}

/** Tools that only ever read state can skip the confirmation prompt. */
export function needsApproval(name) {
  return byName.get(name)?.needsApproval !== false;
}

/**
 * Stop every unfinished background job in a session (exit / test cleanup).
 * Waits for the processes to actually exit so nothing holds locks afterwards.
 */
export async function cleanupJobs(state) {
  const jobs = state?.jobs;
  if (!jobs) return 0;
  let stopped = 0;
  const waits = [];
  for (const job of jobs.values()) {
    if (!job.done && !job.stopped) {
      job.stopped = true;
      try {
        killTree(job.child);
      } catch {}
      stopped++;
      waits.push(waitForExit(job, 5000));
    }
  }
  await Promise.all(waits);
  jobs.clear();
  return stopped;
}
