import path from "node:path";
import { isFileEffectTool, GENERATED_ARTIFACT_TOOLS } from "../core/tool-effects.mjs";

/**
 * A bounded record of what one turn actually did.
 *
 * The journal stores the conversation; this stores only evidence of work:
 * tool names and touched paths. No arguments, no output, no commands - the
 * point is a reliable "what changed" line, not a transcript.
 */

export const AUDIT_MAX_TOOLS = 20;
export const AUDIT_MAX_FILES = 20;
export const AUDIT_MAX_BYTES = 2048;
export const AUDIT_MAX_PATH_CHARS = 200;

export function createTurnAudit({ maxTools = AUDIT_MAX_TOOLS, maxFiles = AUDIT_MAX_FILES } = {}) {
  return {
    tools: [],
    files: [],
    changed: false,
    dropped: 0,
    limits: { maxTools: Math.max(1, maxTools), maxFiles: Math.max(1, maxFiles) },
  };
}

export function noteToolUse(audit, name) {
  if (!audit) return;
  const tool = String(name ?? "").trim();
  if (!tool) return;
  if (isFileEffectTool(tool)) audit.changed = true;
  if (audit.tools.includes(tool)) return;
  if (audit.tools.length >= audit.limits.maxTools) {
    audit.dropped++;
    return;
  }
  audit.tools.push(tool);
}

function patchPaths(patch) {
  const paths = [];
  for (const line of String(patch ?? "").split("\n")) {
    const renamed = /^rename (?:from|to) (.+)$/.exec(line.trim());
    if (renamed) {
      paths.push(renamed[1].trim());
      continue;
    }
    const file = /^(?:\+\+\+|---) ([ab]\/[^\t]+|\/dev\/null)/.exec(line);
    if (file && file[1] !== "/dev/null") paths.push(file[1].replace(/^[ab]\//, ""));
  }
  return paths;
}

function rawPaths(name, args = {}) {
  if (name === "move_file") return [args.source, args.destination];
  if (name === "apply_patch") return patchPaths(args.patch);
  if (GENERATED_ARTIFACT_TOOLS.includes(name)) return [];
  return [args.path];
}

function displayPath(value, cwd) {
  const text = String(value ?? "").trim();
  if (!text) return null;
  const absolute = path.resolve(cwd || process.cwd(), text);
  const relative = path.relative(cwd || process.cwd(), absolute);
  // Inside the workspace a relative path is the useful form; outside it, an
  // absolute one is the only honest form.
  const shown = relative && !relative.startsWith("..") && !path.isAbsolute(relative) ? relative : absolute;
  return shown.split(path.sep).join("/").slice(0, AUDIT_MAX_PATH_CHARS);
}

export function noteFileEffects(audit, name, args, cwd) {
  if (!audit || !isFileEffectTool(name)) return;
  audit.changed = true;
  for (const value of rawPaths(name, args)) {
    const shown = displayPath(value, cwd);
    if (!shown || audit.files.includes(shown)) continue;
    if (audit.files.length >= audit.limits.maxFiles) {
      audit.dropped++;
      continue;
    }
    audit.files.push(shown);
  }
}

/** Freezes the audit for the journal, trimming until it fits the byte bound. */
export function finishTurnAudit(audit, { termination = null, turnId = null } = {}) {
  const output = {
    turnId: turnId || null,
    tools: [...(audit?.tools || [])],
    files: [...(audit?.files || [])],
    changed: Boolean(audit?.changed),
    termination: termination || null,
    dropped: audit?.dropped || 0,
  };
  const size = () => Buffer.byteLength(JSON.stringify(output), "utf8");
  while (size() > AUDIT_MAX_BYTES && output.files.length) {
    output.files.pop();
    output.dropped++;
  }
  while (size() > AUDIT_MAX_BYTES && output.tools.length) {
    output.tools.pop();
    output.dropped++;
  }
  return output;
}
