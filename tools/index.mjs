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
import * as httpRequest from './http-request.mjs';
import * as applyPatch from './apply-patch.mjs';
import * as jobStatus from "./job-status.mjs";
import * as jobStop from "./job-stop.mjs";
import * as jobInput from './job-input.mjs';
import * as jobWait from './job-wait.mjs';
import * as writeTodos from "./write-todos.mjs";
import * as findTools from "./find-tools.mjs";
import { killTree, waitForExit } from "./run-command.mjs";
import { CATEGORIES, alwaysOnTools, deferredTools, deferredSpecByName, categoryOfTool, specOf } from "./catalog.mjs";

/**
 * The tools almost every task needs, sent on every request. Deliberately short:
 * every schema here is paid on every turn, forever.
 */
export const CORE = [
  ...alwaysOnTools,
  readFile,
  writeFile,
  editFile,
  editLines,
  applyPatch,
  listDir,
  searchFiles,
  glob,
  moveFile,
  deleteFile,
  runCommand,
  jobStatus,
  jobStop,
  jobInput,
  jobWait,
  writeTodos,
  httpRequest,
  findTools,
];

const byName = new Map([...CORE, ...deferredTools].map((m) => [m.name, m]));
// Compatibility for existing tool-call transcripts; new turns use http_request.
byName.set(fetchUrl.name, fetchUrl);

/** Every tool, core and deferred alike. Used by the daemon and --config. */
export const tools = [...CORE, ...deferredTools];

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
export function needsApproval(name, args = {}, ctx = {}) {
  const value = byName.get(name)?.needsApproval;
  return typeof value === 'function' ? value(args, ctx) !== false : value !== false;
}

export function isReadOnly(name, args = {}, ctx = {}) {
  const value = byName.get(name)?.readOnly;
  return typeof value === 'function' ? value(args, ctx) === true : value === true;
}

export function displayArgs(name, args, ctx = {}) {
  const display = byName.get(name)?.display;
  if (display && (!args || typeof args !== 'object' || Array.isArray(args))) return '[invalid arguments omitted]';
  return display ? display(args, ctx) : args;
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
    if (!job.done) {
      job.stopped = true;
      try {
        waits.push(killTree(job.child).then(() => waitForExit(job, 5000)));
      } catch {}
      stopped++;
    }
  }
  await Promise.all(waits);
  jobs.clear();
  return stopped;
}
