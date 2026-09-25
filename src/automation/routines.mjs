import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { parseCron, matchCron, normalizeSchedule, describeCron, parseDuration, formatDuration } from "./cron.mjs";
import { writeTextFile } from "../../tools/shared/_shared.mjs";

/**
 * Durable store for the things ankita does on its own: scheduled routines
 * ("every morning at 08:00, brief me") and URL watches ("tell me when the
 * signup count moves"). One JSON file, written atomically.
 */

export const STATE_VERSION = 1;

function slug(text, fallback = "item") {
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

export class RoutineStore {
  constructor(file) {
    this.file = file;
    this.data = { version: STATE_VERSION, routines: [], watches: [] };
  }

  load() {
    try {
      const parsed = JSON.parse(fs.readFileSync(this.file, "utf8"));
      this.data = {
        version: STATE_VERSION,
        routines: Array.isArray(parsed.routines) ? parsed.routines : [],
        watches: Array.isArray(parsed.watches) ? parsed.watches : [],
        telegramOffset: Number(parsed.telegramOffset) || 0,
      };
    } catch {
      this.data = { version: STATE_VERSION, routines: [], watches: [], telegramOffset: 0 };
    }
    return this;
  }

  save() {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    writeTextFile(this.file, JSON.stringify(this.data, null, 2), "\n");
    return this;
  }

  /**
   * Re-read from disk before every mutation.
   *
   * The daemon, the REPL and the schedule/watch tools each hold their own
   * RoutineStore. Without this, whichever instance writes last wins with a
   * stale snapshot, so a watch the agent created mid-routine is silently
   * erased by the daemon's next bookkeeping write.
   */
  _fresh() {
    this.load();
    return this;
  }

  get routines() {
    return this.data.routines;
  }
  get watches() {
    return this.data.watches;
  }

  /**
   * Telegram's getUpdates cursor. Telegram keeps returning every update whose
   * id is >= offset, so an in-memory-only cursor replays the last batch after
   * every restart (duplicate replies to you). Persist it.
   */
  get telegramOffset() {
    return Number(this.data.telegramOffset) || 0;
  }

  setTelegramOffset(value) {
    const next = Number(value);
    if (!Number.isFinite(next)) return this.telegramOffset;
    this.data.telegramOffset = next;
    this.save();
    return next;
  }

  /* ----------------------------- routines ----------------------------- */

  addRoutine({ name, cron, prompt, channel = "telegram", enabled = true, runAt = null, projectId = null }) {
    this._fresh();
    const expr = normalizeSchedule(cron);
    if (!expr || !parseCron(expr)) throw new Error(`invalid schedule: ${cron}`);
    if (!String(prompt ?? "").trim()) throw new Error("prompt is required");
    const taken = new Set(this.routines.map((r) => r.id));
    const id = uniqueId(slug(name || expr, "routine"), taken);
    const routine = {
      id,
      name: String(name || id),
      cron: expr,
      prompt: String(prompt).trim(),
      channel,
      // Metadata only: which project this belongs to. Never changes execution.
      projectId: projectId ? String(projectId) : null,
      enabled: Boolean(enabled),
      createdAt: new Date().toISOString(),
      lastRun: null,
      lastStatus: null,
      lastSummary: null,
      runs: 0,
      runAt: runAt || null,
    };
    this.routines.push(routine);
    this.save();
    return routine;
  }

  findRoutine(id) {
    const key = String(id ?? "").trim().toLowerCase();
    return (
      this.routines.find((r) => r.id === key) ||
      this.routines.find((r) => r.name.toLowerCase() === key) ||
      null
    );
  }

  removeRoutine(id) {
    this._fresh();
    const routine = this.findRoutine(id);
    if (!routine) return null;
    this.data.routines = this.routines.filter((r) => r !== routine);
    this.save();
    return routine;
  }

  setRoutineEnabled(id, enabled) {
    this._fresh();
    const routine = this.findRoutine(id);
    if (!routine) return null;
    routine.enabled = Boolean(enabled);
    this.save();
    return routine;
  }

  /**
   * Claims a routine for this minute without counting it as a completed run.
   * Stops the next tick re-dispatching work that is still in flight.
   */
  claimRoutine(id, at) {
    this._fresh();
    const routine = this.findRoutine(id);
    if (!routine) return null;
    routine.lastRun = at || new Date().toISOString();
    if (routine.runAt) routine.runAt = null;
    this.save();
    return routine;
  }

  markRoutineRun(id, { status, summary, at }) {
    this._fresh();
    const routine = this.findRoutine(id);
    if (!routine) return null;
    // `at` lets the daemon stamp runs with the same clock it used to decide the
    // routine was due; otherwise a skewed or injected clock double-fires.
    routine.lastRun = at || new Date().toISOString();
    routine.lastStatus = status;
    routine.lastSummary = summary ? String(summary).slice(0, 400) : null;
    routine.runs = (routine.runs || 0) + 1;
    this.save();
    return routine;
  }

  /** Ask for a routine to fire on the next daemon tick, cron notwithstanding. */
  scheduleRoutineNow(id) {
    this._fresh();
    const routine = this.findRoutine(id);
    if (!routine) return null;
    routine.runAt = new Date().toISOString();
    this.save();
    return routine;
  }

  /**
   * Routines that should fire at `now`. A cron routine runs at most once per
   * matching minute, so a daemon restart mid-minute cannot double-fire; a
   * one-shot (runAt) fires the moment its time passes, enabled or not.
   */
  dueRoutines(now = new Date()) {
    const minute = Math.floor(now.getTime() / 60000);
    return this.routines.filter((routine) => {
      if (routine.runAt) {
        const at = Date.parse(routine.runAt);
        return Number.isFinite(at) ? at <= now.getTime() : false;
      }
      if (!routine.enabled) return false;
      if (!matchCron(routine.cron, now)) return false;
      if (routine.lastRun) {
        const last = Math.floor(Date.parse(routine.lastRun) / 60000);
        if (Number.isFinite(last) && last >= minute) return false;
      }
      return true;
    });
  }

  /** One-shot routines clear their one-shot marker once fired. */
  clearRunAt(id) {
    this._fresh();
    const routine = this.findRoutine(id);
    if (routine && routine.runAt) {
      routine.runAt = null;
      this.save();
    }
    return routine;
  }

  /* ------------------------------ watches ----------------------------- */

  addWatch({
    name,
    url,
    selector = "",
    regex = "",
    interval = "1h",
    alertEvery = "10m",
    enabled = true,
    notify = true,
    projectId = null,
  }) {
    this._fresh();
    let parsed;
    try {
      parsed = new URL(String(url ?? "").trim());
    } catch {
      throw new Error(`invalid url: ${url}`);
    }
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      throw new Error("url must be http(s)");
    }
    const everyMs = parseDuration(interval, 3600000);
    // 15s floor: fine for a local dashboard, still far above a busy loop.
    if (everyMs < 15000) throw new Error("interval must be at least 15s");

    const taken = new Set(this.watches.map((w) => w.id));
    const watch = {
      id: uniqueId(slug(name || parsed.hostname, "watch"), taken),
      name: String(name || parsed.hostname),
      url: parsed.toString(),
      selector: String(selector || ""),
      regex: String(regex || ""),
      intervalMs: everyMs,
      // Metadata only, same as routines.
      projectId: projectId ? String(projectId) : null,
      // Checking often is cheap; alerting often is not. A busy number would
      // otherwise send a message every check.
      alertCooldownMs: Math.max(0, parseDuration(alertEvery, 600000)),
      enabled: Boolean(enabled),
      notify: Boolean(notify),
      lastAlerted: null,
      createdAt: new Date().toISOString(),
      lastChecked: null,
      lastValue: null,
      lastText: null,
      lastError: null,
      checks: 0,
      changes: 0,
      history: [],
    };
    this.watches.push(watch);
    this.save();
    return watch;
  }

  findWatch(id) {
    const key = String(id ?? "").trim().toLowerCase();
    return (
      this.watches.find((w) => w.id === key) ||
      this.watches.find((w) => w.name.toLowerCase() === key) ||
      null
    );
  }

  removeWatch(id) {
    this._fresh();
    const watch = this.findWatch(id);
    if (!watch) return null;
    this.data.watches = this.watches.filter((w) => w !== watch);
    this.save();
    return watch;
  }

  setWatchEnabled(id, enabled) {
    this._fresh();
    const watch = this.findWatch(id);
    if (!watch) return null;
    watch.enabled = Boolean(enabled);
    this.save();
    return watch;
  }

  /**
   * Records a check. Change detection hashes the observed content, so a
   * whole-page watch (value === null) still notices edits, while a numeric
   * extraction also yields a delta: "1,204" -> "1,227" is +23.
   */
  recordWatchCheck(id, { value = null, text = null, error = null }) {
    this._fresh();
    const watch = this.findWatch(id);
    if (!watch) return null;
    const previous = watch.lastValue;
    const previousHash = watch.lastHash ?? null;
    watch.lastChecked = new Date().toISOString();
    watch.checks = (watch.checks || 0) + 1;
    watch.lastError = error;

    if (error) {
      this.save();
      return { watched: watch, changed: false, delta: null, value: null, error };
    }

    const digest = hashContent(value ?? text ?? "");
    const changed = previousHash !== null && previousHash !== digest;
    const delta = numericDelta(previous, value);
    if (changed) watch.changes = (watch.changes || 0) + 1;

    watch.lastValue = value;
    watch.lastHash = digest;
    watch.lastText = text ? String(text).slice(0, 2000) : watch.lastText;
    watch.history = [...(watch.history || []), { at: watch.lastChecked, value, delta }].slice(-50);
    this.save();
    return { watched: watch, changed, delta, value, previous };
  }

  /** True when a change is worth telling the user about right now. */
  shouldAlert(watch, now = new Date()) {
    if (!watch.notify) return false;
    const cooldown = watch.alertCooldownMs ?? 600000;
    if (!cooldown) return true;
    if (!watch.lastAlerted) return true;
    const last = Date.parse(watch.lastAlerted);
    return !Number.isFinite(last) || now.getTime() - last >= cooldown;
  }

  markAlerted(id, at) {
    this._fresh();
    const watch = this.findWatch(id);
    if (!watch) return null;
    watch.lastAlerted = at || new Date().toISOString();
    this.save();
    return watch;
  }

  /**
   * Tags routines and watches with a project.
   *
   * Pass explicit id arrays to tag those; omit them to adopt everything that
   * is currently untagged. Returns the ids that actually changed.
   */
  attachToProject(projectId, { routines = null, watches = null } = {}) {
    this._fresh();
    const target = String(projectId);
    const pick = (list, ids) => {
      if (Array.isArray(ids) && ids.length) {
        const wanted = ids.map((i) => String(i).toLowerCase());
        return list.filter(
          (item) => wanted.includes(item.id) || wanted.includes(String(item.name).toLowerCase())
        );
      }
      return list.filter((item) => !item.projectId);
    };

    const tagged = [...pick(this.routines, routines), ...pick(this.watches, watches)];
    for (const item of tagged) item.projectId = target;
    if (tagged.length) this.save();
    return {
      routines: tagged.filter((i) => this.routines.includes(i)).map((i) => i.id),
      watches: tagged.filter((i) => this.watches.includes(i)).map((i) => i.id),
    };
  }

  dueWatches(now = new Date()) {
    return this.watches.filter((watch) => {
      if (!watch.enabled) return false;
      if (!watch.lastChecked) return true;
      const last = Date.parse(watch.lastChecked);
      if (!Number.isFinite(last)) return true;
      return now.getTime() - last >= (watch.intervalMs || 3600000);
    });
  }

  summary() {
    return {
      routines: this.routines.length,
      routinesEnabled: this.routines.filter((r) => r.enabled).length,
      watches: this.watches.length,
      watchesEnabled: this.watches.filter((w) => w.enabled).length,
    };
  }
}

export function hashContent(text) {
  return crypto.createHash("sha256").update(String(text ?? ""), "utf8").digest("hex").slice(0, 16);
}

/** "1,204" vs "1,227" -> +23. Returns null when either side is not numeric. */
export function numericDelta(previous, current) {
  const a = toNumber(previous);
  const b = toNumber(current);
  if (a === null || b === null) return null;
  return b - a;
}

export function toNumber(value) {
  if (value === null || value === undefined) return null;
  const cleaned = String(value).replace(/[,\s_]/g, "").replace(/^\+/, "");
  if (!/^-?\d+(\.\d+)?$/.test(cleaned)) return null;
  const n = Number(cleaned);
  return Number.isFinite(n) ? n : null;
}

/** " [zumba]" when tagged, "" otherwise. Keeps existing lines byte-identical. */
function tag(entry) {
  return entry.projectId ? `  [${entry.projectId}]` : "";
}

export function describeRoutine(routine) {
  return `${routine.enabled ? "on " : "off"} ${routine.id.padEnd(18)} ${describeCron(routine.cron).padEnd(22)} ${routine.name}${tag(routine)}`;
}

export function describeWatch(watch) {
  const every = formatDuration(watch.intervalMs || 3600000) + (watch.alertCooldownMs ? "/alert " + formatDuration(watch.alertCooldownMs) : "");
  const value = watch.lastValue === null || watch.lastValue === undefined ? "-" : String(watch.lastValue).slice(0, 30);
  return `${watch.enabled ? "on " : "off"} ${watch.id.padEnd(18)} every ${every.padEnd(6)} ${value.padEnd(12)} ${watch.name}${tag(watch)}`;
}
