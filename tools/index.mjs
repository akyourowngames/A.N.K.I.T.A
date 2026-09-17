import * as runCommand from "./run-command.mjs";
import * as readFile from "./read-file.mjs";
import * as writeFile from "./write-file.mjs";
import * as editFile from "./edit-file.mjs";
import * as editLines from "./edit-lines.mjs";
import * as listDir from "./list-dir.mjs";
import * as searchFiles from "./search-files.mjs";
import * as glob from "./glob.mjs";
import * as createDir from "./create-dir.mjs";
import * as moveFile from "./move-file.mjs";
import * as deleteFile from "./delete-file.mjs";
import * as fetchUrl from "./fetch-url.mjs";
import * as writeTodos from "./write-todos.mjs";
import * as jobStatus from "./job-status.mjs";
import * as jobStop from "./job-stop.mjs";
import { killTree, waitForExit } from "./run-command.mjs";

const modules = [
  runCommand,
  readFile,
  writeFile,
  editFile,
  editLines,
  listDir,
  searchFiles,
  glob,
  createDir,
  moveFile,
  deleteFile,
  fetchUrl,
  writeTodos,
  jobStatus,
  jobStop,
];

const byName = new Map(modules.map((m) => [m.name, m]));

export const tools = modules;

export const specs = modules.map((m) => ({
  type: "function",
  function: { name: m.name, description: m.description, parameters: m.parameters },
}));

export function get(name) {
  return byName.get(name);
}

export function names() {
  return modules.map((m) => m.name);
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
