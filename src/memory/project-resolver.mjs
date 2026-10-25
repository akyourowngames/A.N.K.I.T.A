import fs from "node:fs";
import os from "node:os";
import path from "node:path";

/**
 * Works out which project a directory belongs to.
 *
 * Matching is deliberately strict: a project path is a root, never a loose
 * substring, and `C:\foo` must not capture `C:\foobar`. The longest matching
 * root wins so nested projects behave predictably.
 */

// A repository root is usually a handful of levels up; this stops a pathological
// filesystem walk without spawning a child process.
export const MAX_REPO_ROOT_DEPTH = 12;

function pathApi(platform) {
  return platform === "win32" ? path.win32 : path.posix;
}

/** Absolute, no trailing separator, and case-folded only where the OS is. */
export function normalizeProjectPath(value, platform = process.platform) {
  const text = String(value ?? "").trim();
  if (!text) return "";
  const api = pathApi(platform);
  let resolved = api.resolve(text);
  const root = api.parse(resolved).root;
  while (resolved.length > root.length && (resolved.endsWith(api.sep) || resolved.endsWith("/"))) {
    resolved = resolved.slice(0, -1);
  }
  return platform === "win32" ? resolved.toLowerCase() : resolved;
}

/** True for the root itself and anything below it. Boundary-safe. */
export function isPathInside(root, candidate, platform = process.platform) {
  const parent = normalizeProjectPath(root, platform);
  const child = normalizeProjectPath(candidate, platform);
  if (!parent || !child) return false;
  const api = pathApi(platform);
  const relative = api.relative(parent, child);
  if (relative === "") return true;
  return relative !== ".." && !relative.startsWith(`..${api.sep}`) && !relative.startsWith("../") && !api.isAbsolute(relative);
}

/**
 * Returns `{ project, reason: 'matched' }`, `{ reason: 'ambiguous', candidates }`
 * when two roots tie, or `{ reason: 'none' }`.
 */
export function resolveProjectForPath(projects, cwd, { platform = process.platform } = {}) {
  const target = normalizeProjectPath(cwd, platform);
  if (!target) return { project: null, reason: "none", candidates: [] };

  const matches = [];
  for (const project of projects || []) {
    if (!project || project.archived || !project.path) continue;
    const root = normalizeProjectPath(project.path, platform);
    if (root && isPathInside(root, target, platform)) matches.push({ project, root });
  }
  if (!matches.length) return { project: null, reason: "none", candidates: [] };

  const longest = Math.max(...matches.map((match) => match.root.length));
  const best = matches.filter((match) => match.root.length === longest);
  if (best.length > 1) {
    return { project: null, reason: "ambiguous", candidates: best.map((match) => match.project) };
  }
  return { project: best[0].project, reason: "matched", candidates: [] };
}

/** Nearest ancestor holding a `.git` file or directory, or null. */
export function findRepoRoot(cwd, { maxDepth = MAX_REPO_ROOT_DEPTH } = {}) {
  let current = path.resolve(String(cwd || ""));
  for (let depth = 0; depth <= maxDepth; depth++) {
    try {
      if (fs.existsSync(path.join(current, ".git"))) return current;
    } catch {
      return null;
    }
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return null;
}

/**
 * A candidate project for an untracked repository folder. The user still has to
 * say yes; this is only a suggestion to offer.
 */
export function suggestProjectForPath(cwd, { home = os.homedir(), platform = process.platform } = {}) {
  const root = findRepoRoot(cwd);
  if (!root) return null;
  if (home && normalizeProjectPath(root, platform) === normalizeProjectPath(home, platform)) return null;
  return { name: path.basename(root), path: root };
}

/** The project a session should attach to from its working directory. */
export function detectProject(store, cwd, config = {}) {
  if (config.projectAutoDetect === false) return null;
  const result = resolveProjectForPath(store?.projects || [], cwd);
  return result.reason === "matched" ? result.project : null;
}
