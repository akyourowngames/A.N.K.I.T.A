import fs from "node:fs";
import path from "node:path";
import { writeTextFile } from "../../tools/shared/_shared.mjs";

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

export const STATUSES = ["active", "paused", "shipped", "on-hold"];

// Contacts and links are small, but "small" plus "forever" is unbounded growth.
export const MAX_CONTACTS = 20;
export const MAX_LINKS = 40;

// Remembered things. Newest kept; the tool says when older entries were dropped.
export const MAX_NOTES = 50;
export const MAX_DECISIONS = 50;
export const MAX_TODOS = 100;

/** "6d ago" reads like a memory; "2026-09-12T09:14:22Z" reads like a database. */
export function since(iso, now = Date.now()) {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const secs = Math.max(0, Math.floor((now - t) / 1000));
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  const weeks = Math.floor(days / 7);
  if (weeks < 5) return `${weeks}w ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

function nextTodoId(todos = []) {
  let max = 0;
  for (const todo of todos) {
    const m = /^t(\d+)$/.exec(String(todo.id || ""));
    if (m) max = Math.max(max, Number(m[1]));
  }
  return `t${max + 1}`;
}

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

function cleanList(value, cap) {
  if (value === undefined || value === null) return undefined;
  const list = Array.isArray(value) ? value : [value];
  return list
    .map((v) => String(v).trim())
    .filter(Boolean)
    .slice(0, cap);
}

/**
 * Caps how many conventions are kept, never their length.
 *
 * A length cap here would silently truncate what the user wrote - it happened:
 * "…edge-tts for voice, scrapling for scraping" was stored as "…edge-tts for
 * voice,". Storage keeps the real value; the prompt block is where the size
 * bound belongs.
 */
function normalizeConventions(value) {
  return cleanList(value, MAX_CONVENTIONS) || [];
}

export class ProjectStore {
  constructor(file) {
    this.file = file;
    this.loadError = null;
    this.conflicts = [];
    this.data = { version: PROJECTS_VERSION, active: null, projects: [] };
  }

  load() {
    this.loadError = null;
    this.conflicts = [];
    try {
      const parsed = JSON.parse(fs.readFileSync(this.file, "utf8"));
      if (!parsed || !Array.isArray(parsed.projects)) throw new Error('Invalid project structure');
      this.data = {
        version: PROJECTS_VERSION,
        active: typeof parsed.active === "string" ? parsed.active : null,
        projects: Array.isArray(parsed.projects) ? parsed.projects.filter((p) => p && p.id) : [],
      };
      for (const project of this.data.projects) {
        const ids = new Set();
        const active = new Set();
        for (const todo of project.todos || []) {
          if (ids.has(todo.id)) this.conflicts.push(`${project.id}: duplicate todo ID ${todo.id}`);
          ids.add(todo.id);
          if (!todo.done) {
            const text = String(todo.text || '').trim().replace(/\s+/g, ' ').toLocaleLowerCase();
            if (active.has(text)) this.conflicts.push(`${project.id}: duplicate active todo ${todo.text}`);
            active.add(text);
          }
        }
      }
    } catch (error) {
      // Missing or malformed: start empty rather than crashing the CLI on boot.
      if (error.code !== 'ENOENT') this.loadError = error;
      this.data = { version: PROJECTS_VERSION, active: null, projects: [] };
    }
    return this;
  }

  save() {
    if (this.loadError) throw new Error(`Existing project state is malformed or unreadable: ${this.loadError.message}`);
    if (this.conflicts.length) throw new Error(`Project state conflict: ${this.conflicts.join('; ')}`);
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    writeTextFile(this.file, JSON.stringify(this.data, null, 2), "\n");
    return this;
  }

  /** Re-read before every write: the tool, the CLI and the daemon each hold one. */
  _fresh() {
    this.load();
    if (this.loadError) throw new Error(`Existing project state is malformed or unreadable: ${this.loadError.message}`);
    if (this.conflicts.length) throw new Error(`Project state conflict: ${this.conflicts.join('; ')}`);
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
      status: "active",
      archived: false,
      contacts: [],
      links: [],
      notes: [],
      decisions: [],
      todos: [],
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

  /**
   * Renames the display name only. The id is a stable handle that routines and
   * watches are tagged with, so it must not move underneath them.
   */
  renameProject(idOrName, newName) {
    this._fresh();
    const project = this.find(idOrName);
    const label = String(newName ?? "").trim();
    if (!project || !label) return null;
    project.name = label;
    this.save();
    return project;
  }

  setStatus(idOrName, status) {
    this._fresh();
    const project = this.find(idOrName);
    const value = String(status ?? "").trim().toLowerCase();
    if (!project) return null;
    if (!STATUSES.includes(value)) return { error: `status must be one of ${STATUSES.join(", ")}` };
    project.status = value;
    this.save();
    return project;
  }

  setArchived(idOrName, archived = true) {
    this._fresh();
    const project = this.find(idOrName);
    if (!project) return null;
    project.archived = Boolean(archived);
    // An archived project should not also be the active one.
    if (project.archived && this.data.active === project.id) this.data.active = null;
    this.save();
    return project;
  }

  addContact(idOrName, { name, role, email } = {}) {
    this._fresh();
    const project = this.find(idOrName);
    const label = String(name ?? "").trim();
    if (!project) return null;
    if (!label) return { error: "a contact needs a name" };

    // Only the fields actually supplied are written: defaulting role/email to
    // "" and assigning anyway would wipe a value the caller never mentioned.
    const patch = { name: label };
    if (role !== undefined) patch.role = String(role).trim();
    if (email !== undefined) patch.email = String(email).trim();

    project.contacts = [...(project.contacts || [])];
    const existing = project.contacts.find((c) => c.name.toLowerCase() === label.toLowerCase());
    if (existing) Object.assign(existing, patch);
    else project.contacts.push({ name: label, role: patch.role ?? "", email: patch.email ?? "" });

    project.contacts = project.contacts.slice(-MAX_CONTACTS);
    this.save();
    return project;
  }

  addLink(idOrName, { label, url } = {}) {
    this._fresh();
    const project = this.find(idOrName);
    if (!project) return null;
    const target = String(url ?? "").trim();
    if (!target) return { error: "a link needs a url" };
    try {
      const parsed = new URL(target);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
        return { error: "link url must be http(s)" };
      }
    } catch {
      return { error: `not a valid url: ${target}` };
    }
    project.links = [...(project.links || []), { label: String(label || target).trim(), url: target }].slice(-MAX_LINKS);
    this.save();
    return project;
  }

  /* ------------------------------- memory -------------------------------- */

  addNote(idOrName, text, source = null) {
    this._fresh();
    const project = this.find(idOrName);
    const value = String(text ?? "").trim();
    if (!project) return null;
    if (!value) return { error: "a note needs some text" };
    project.notes = [...(project.notes || []), { at: new Date().toISOString(), text: value, ...(source ? { source } : {}) }].slice(-MAX_NOTES);
    this.save();
    return project;
  }

  addDecision(idOrName, text, source = null) {
    this._fresh();
    const project = this.find(idOrName);
    const value = String(text ?? "").trim();
    if (!project) return null;
    if (!value) return { error: "a decision needs some text" };
    project.decisions = [...(project.decisions || []), { at: new Date().toISOString(), text: value, ...(source ? { source } : {}) }].slice(
      -MAX_DECISIONS
    );
    this.save();
    return project;
  }

  addTodo(idOrName, text, source = null) {
    this._fresh();
    const project = this.find(idOrName);
    const value = String(text ?? "").trim();
    if (!project) return null;
    if (!value) return { error: "a todo needs some text" };
    const normalized = value.replace(/\s+/g, ' ').toLocaleLowerCase();
    if ((project.todos || []).some(todo => !todo.done && String(todo.text).trim().replace(/\s+/g, ' ').toLocaleLowerCase() === normalized)) {
      return { error: 'an open todo with the same text already exists' };
    }
    if ((project.todos || []).length >= MAX_TODOS) return { error: `todo limit (${MAX_TODOS}) reached; archive history before adding more` };
    project.todos = [
      ...(project.todos || []),
      { id: nextTodoId(project.todos), at: new Date().toISOString(), text: value, done: false, doneAt: null, ...(source ? { source } : {}) },
    ];
    this.save();
    return project;
  }

  /**
   * Closes one todo. `ref` is a t-id, a 1-based position among the *open*
   * items, or a substring of the text. Ambiguity is reported, never guessed.
   */
  completeTodo(idOrName, ref) {
    this._fresh();
    const project = this.find(idOrName);
    if (!project) return null;
    const todos = project.todos || [];
    const open = todos.filter((t) => !t.done);
    if (!open.length) return { error: "nothing is open" };

    const key = String(ref ?? "").trim();
    if (!key) return { error: "which one? pass an id, a number, or some of the text" };

    let target = todos.find((t) => t.id === key && !t.done);
    if (!target && /^\d+$/.test(key)) {
      const n = Number(key);
      if (n >= 1 && n <= open.length) target = open[n - 1];
      else return { error: `there is no open item ${n} (${open.length} open)` };
    }
    if (!target) {
      const matches = todos.filter((t) => !t.done && t.text.toLowerCase().includes(key.toLowerCase()));
      if (matches.length === 1) target = matches[0];
      else if (matches.length > 1) {
        return { error: `"${key}" matches ${matches.length}: ${matches.map((t) => `${t.id} ${t.text}`).join(" | ")}` };
      }
    }
    if (!target) return { error: `no open item matches "${key}"` };

    target.done = true;
    target.doneAt = new Date().toISOString();
    this.save();
    return { project, closed: target };
  }

  memoryCounts(project) {
    const todos = project?.todos || [];
    return {
      notes: (project?.notes || []).length,
      decisions: (project?.decisions || []).length,
      todos: todos.length,
      open: todos.filter((t) => !t.done).length,
    };
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
  const marks = [];
  if (project.status && project.status !== "active") marks.push(`<${project.status}>`);
  if (project.archived) marks.push("<archived>");
  return `${mark} ${project.id.padEnd(18)} ${String(where).padEnd(34)} ${(project.summary || "").slice(0, 40)}${
    counts.length ? "  (" + counts.join(", ") + ")" : ""
  }${marks.length ? "  " + marks.join(" ") : ""}`;
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
  for (const c of project.contacts || []) {
    lines.push(`  contact      ${[c.name, c.role, c.email].filter(Boolean).join(" · ")}`);
  }
  for (const l of project.links || []) {
    lines.push(`  link         ${l.label}  ${l.url}`);
  }
  lines.push(`  status       ${project.status || "active"}${project.archived ? "  (archived)" : ""}`);
  lines.push(`  created      ${project.createdAt}`);
  if (project.lastUsedAt) lines.push(`  last used    ${project.lastUsedAt}`);
  if (store && store.activeId === project.id) lines.push(`  (active)`);
  const missing = store ? store.missingFor(project) : [];
  if (missing.length) lines.push(`  still unknown: ${missing.join(", ")}`);
  return lines.join("\n");
}
