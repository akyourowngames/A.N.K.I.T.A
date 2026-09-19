import fs from "node:fs";
import path from "node:path";
import { writeTextFile } from "../tools/_shared.mjs";

/**
 * Projects: the things ankita is expected to know about.
 *
 * A project is deliberately loose - a folder, a server, a client, or all
 * three. Nothing is required beyond a name, so the guided intake can create a
 * stub and let the user fill the rest in over time.
 *
 * Lives in its own file so state.json stays about schedules.
 */

export const PROJECTS_VERSION = 1;

// These bound the prompt block, which is paid on every single turn. Real
// conventions are short ("pnpm not npm"); the caps only stop a runaway one.
export const SUMMARY_CAP = 200;
export const MAX_CONVENTIONS = 5;
export const CONVENTION_CAP = 60;

export const PROJECT_FIELDS = [
  "summary",
  "path",
  "repo",
  "client",
  "conventions",
  "environments",
  "databases",
];

/** Questions worth asking, in the order they usually matter. */
const INTAKE_QUESTIONS = [
  ["summary", "what it is"],
  ["path", "where it lives on disk"],
  ["databases", "which database it uses"],
  ["environments", "which servers/environments it runs on"],
  ["conventions", "how you like things done in it"],
  ["client", "which client it is for"],
];

function slug(text, fallback = "project") {
  const s = String(text ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  return s || fallback;
}

function uniqueId(base, taken) {
  let id = base;
  let n = 2;
  while (taken.has(id)) id = `${base}-${n++}`;
  return id;
}

function cleanList(value, cap, itemCap = 0) {
  if (value === undefined || value === null) return undefined;
  const list = Array.isArray(value) ? value : [value];
  return list
    .map((v) => String(v).trim())
    .filter(Boolean)
    .map((v) => (itemCap ? v.slice(0, itemCap) : v))
    .slice(0, cap);
}

/** Every entry point must respect the same limits, or the prompt block grows. */
function normalizeConventions(value) {
  return cleanList(value, MAX_CONVENTIONS, CONVENTION_CAP) || [];
}

export class ProjectStore {
  constructor(file) {
    this.file = file;
    this.data = { version: PROJECTS_VERSION, active: null, projects: [] };
  }

  load() {
    try {
      const parsed = JSON.parse(fs.readFileSync(this.file, "utf8"));
      this.data = {
        version: PROJECTS_VERSION,
        active: typeof parsed.active === "string" ? parsed.active : null,
        projects: Array.isArray(parsed.projects) ? parsed.projects.filter((p) => p && p.id) : [],
      };
    } catch {
      // Missing or malformed: start empty rather than crashing the CLI on boot.
      this.data = { version: PROJECTS_VERSION, active: null, projects: [] };
    }
    return this;
  }

  save() {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    writeTextFile(this.file, JSON.stringify(this.data, null, 2), "\n");
    return this;
  }

  /** Re-read before every write: the tool, the CLI and the daemon each hold one. */
  _fresh() {
    this.load();
    return this;
  }

  get projects() {
    return this.data.projects;
  }

  get activeId() {
    return this.data.active;
  }

  /** The active project object, or null. */
  get active() {
    return this.data.active ? this.find(this.data.active) : null;
  }

  find(idOrName) {
    const key = String(idOrName ?? "").trim().toLowerCase();
    if (!key) return null;
    return (
      this.projects.find((p) => p.id === key) ||
      this.projects.find((p) => String(p.name).toLowerCase() === key) ||
      null
    );
  }

  add({ name, summary, path: projectPath, repo, client, conventions, environments, databases } = {}) {
    this._fresh();
    const label = String(name ?? "").trim();
    if (!label) throw new Error("a project name is required");

    const taken = new Set(this.projects.map((p) => p.id));
    const project = {
      id: uniqueId(slug(label), taken),
      name: label,
      summary: summary ? String(summary).trim().slice(0, SUMMARY_CAP * 2) : null,
      path: projectPath ? path.resolve(String(projectPath).trim()) : null,
      repo: repo ? String(repo).trim() : null,
      client: client ? String(client).trim() : null,
      conventions: normalizeConventions(conventions),
      environments: Array.isArray(environments) ? environments.slice(0, 10) : [],
      databases: Array.isArray(databases) ? databases.slice(0, 10) : [],
      createdAt: new Date().toISOString(),
      lastUsedAt: null,
    };
    this.projects.push(project);
    this.save();
    return project;
  }

  update(idOrName, patch = {}) {
    this._fresh();
    const project = this.find(idOrName);
    if (!project) return null;

    if (patch.name !== undefined && String(patch.name).trim()) project.name = String(patch.name).trim();
    if (patch.summary !== undefined) {
      project.summary = patch.summary ? String(patch.summary).trim().slice(0, SUMMARY_CAP * 2) : null;
    }
    if (patch.path !== undefined) project.path = patch.path ? path.resolve(String(patch.path).trim()) : null;
    if (patch.repo !== undefined) project.repo = patch.repo ? String(patch.repo).trim() : null;
    if (patch.client !== undefined) project.client = patch.client ? String(patch.client).trim() : null;
    if (patch.conventions !== undefined) {
      project.conventions = normalizeConventions(patch.conventions);
    }
    if (patch.environments !== undefined) {
      project.environments = Array.isArray(patch.environments) ? patch.environments.slice(0, 10) : [];
    }
    if (patch.databases !== undefined) {
      project.databases = Array.isArray(patch.databases) ? patch.databases.slice(0, 10) : [];
    }
    this.save();
    return project;
  }

  /** Appends one convention without touching the rest. */
  addConvention(idOrName, text) {
    this._fresh();
    const project = this.find(idOrName);
    if (!project) return null;
    const value = String(text ?? "").trim().slice(0, CONVENTION_CAP);
    if (!value) return project;
    project.conventions = [...(project.conventions || [])];
    if (!project.conventions.some((c) => c.toLowerCase() === value.toLowerCase())) {
      project.conventions.push(value);
      project.conventions = project.conventions.slice(-MAX_CONVENTIONS);
    }
    this.save();
    return project;
  }

  use(idOrName) {
    this._fresh();
    const project = this.find(idOrName);
    if (!project) return null;
    project.lastUsedAt = new Date().toISOString();
    this.data.active = project.id;
    this.save();
    return project;
  }

  clearActive() {
    this._fresh();
    this.data.active = null;
    this.save();
    return this;
  }

  forget(idOrName) {
    this._fresh();
    const project = this.find(idOrName);
    if (!project) return null;
    this.data.projects = this.projects.filter((p) => p !== project);
    if (this.data.active === project.id) this.data.active = null;
    this.save();
    return project;
  }

  /** Fields still worth asking about, most useful first. */
  missingFor(project) {
    if (!project) return [];
    return INTAKE_QUESTIONS.filter(([field]) => {
      const value = project[field];
      if (Array.isArray(value)) return value.length === 0;
      return !value;
    }).map(([, label]) => label);
  }

  /**
   * The bounded block injected into the system prompt. Kept small on purpose:
   * tool specs already take a large share of the context budget.
   */
  promptBlock() {
    const project = this.active;
    if (!project) return "";
    const lines = [`Active project: ${project.name} (${project.id})`];
    if (project.summary) lines.push(`  what it is: ${String(project.summary).slice(0, SUMMARY_CAP)}`);
    if (project.path) lines.push(`  path: ${project.path}`);
    if (project.client) lines.push(`  client: ${project.client}`);
    const conventions = (project.conventions || []).slice(0, MAX_CONVENTIONS);
    if (conventions.length) {
      // Belt and braces: a hand-edited projects.json could still hold long ones.
      lines.push(`  how they like it: ${conventions.join("; ").slice(0, MAX_CONVENTIONS * CONVENTION_CAP)}`);
    }
    const dbs = (project.databases || []).map((d) => [d.kind, d.name].filter(Boolean).join(" "));
    if (dbs.length) lines.push(`  databases: ${dbs.join(", ")}`);
    return lines.join("\n");
  }
}

/**
 * Works out which project something new belongs to.
 *
 *   project: "zumba"  -> that project (by id or name)
 *   project: "none"   -> explicitly unattached
 *   omitted           -> whatever is active right now
 *
 * Returns { ok, projectId } or { ok: false, error } for an unknown name.
 */
export function resolveProjectRef(store, asked, activeId = null) {
  const name = String(asked ?? "").trim();
  if (!name) return { ok: true, projectId: activeId || null };
  if (name.toLowerCase() === "none") return { ok: true, projectId: null };

  const found = store.find(name);
  if (found) return { ok: true, projectId: found.id, projectName: found.name };

  const known = store.projects.map((p) => p.id);
  return {
    ok: false,
    error:
      `no project "${name}". ` +
      (known.length ? `Known: ${known.join(", ")}. ` : "No projects exist yet. ") +
      "Use 'none' to leave it unattached.",
  };
}

export function describeProject(project, activeId) {
  const mark = project.id === activeId ? "*" : " ";
  const where = project.path || project.client || "-";
  const counts = [
    project.databases?.length ? `${project.databases.length} db` : null,
    project.environments?.length ? `${project.environments.length} env` : null,
  ].filter(Boolean);
  return `${mark} ${project.id.padEnd(18)} ${String(where).padEnd(34)} ${(project.summary || "").slice(0, 40)}${
    counts.length ? "  (" + counts.join(", ") + ")" : ""
  }`;
}

export function describeProjectFull(project, store) {
  if (!project) return "No such project.";
  const lines = [`${project.name}  (id ${project.id})`];
  if (project.summary) lines.push(`  what it is   ${project.summary}`);
  if (project.path) lines.push(`  path         ${project.path}`);
  if (project.repo) lines.push(`  repo         ${project.repo}`);
  if (project.client) lines.push(`  client       ${project.client}`);
  if (project.conventions?.length) lines.push(`  conventions  ${project.conventions.join("; ")}`);
  for (const db of project.databases || []) {
    lines.push(
      `  database     ${db.name || "main"} (${db.kind || "unknown"})` +
        (db.environment ? ` env ${db.environment}` : "") +
        (db.credential ? ` credential ${db.credential}` : "")
    );
  }
  for (const env of project.environments || []) {
    lines.push(`  environment  ${env.name || "?"}${env.host ? ` at ${env.host}` : ""}`);
  }
  lines.push(`  created      ${project.createdAt}`);
  if (project.lastUsedAt) lines.push(`  last used    ${project.lastUsedAt}`);
  if (store && store.activeId === project.id) lines.push(`  (active)`);
  const missing = store ? store.missingFor(project) : [];
  if (missing.length) lines.push(`  still unknown: ${missing.join(", ")}`);
  return lines.join("\n");
}
