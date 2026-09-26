import fs from "node:fs";
import { rememberPlan, executionPlan } from '../shared/_approval-plan.mjs';
import { resolvePath, assertReadable, readTextFile, writeTextFile, restoreTrailing } from "../shared/_shared.mjs";
import { diffText, renderDiff, stats, touchedRange } from "../shared/_diff.mjs";

export const name = "edit_file";
export const description =
  "Edit an existing file by replacing exact strings. Either pass one old_string/new_string pair, " +
  "or pass an `edits` array to apply several replacements as one atomic operation (if any of them " +
  "fails to match, nothing is written). Matching tries exact text, normalized line endings, trimmed trailing whitespace, then ignored indentation; " +
  "must be unique unless replace_all is true. The diff is shown to the user for approval.";

export const parameters = {
  type: "object",
  properties: {
    path: { type: "string", description: "File path, absolute or relative to the working directory." },
    old_string: { type: "string", description: "Exact text to find (single-edit form)." },
    new_string: { type: "string", description: "Replacement text. Use \"\" to delete the match." },
    replace_all: { type: "boolean", description: "Replace every occurrence. Default false." },
    edits: {
      type: "array",
      description:
        "Multiple replacements applied atomically, in order. Use instead of old_string/new_string.",
      items: {
        type: "object",
        properties: {
          old_string: { type: "string", description: "Exact text to find." },
          new_string: { type: "string", description: "Replacement text." },
          replace_all: { type: "boolean", description: "Replace every occurrence." },
        },
        required: ["old_string", "new_string"],
      },
    },
  },
  required: ["path"],
};

function normalized(text, rung) {
  let value = "";
  const offsets = [];
  const excluded = new Set();
  if (rung >= 2) for (const match of text.matchAll(/[\t ]+(?=\r?$)/gm)) {
    for(let i=match.index;i<match.index+match[0].length;i++) excluded.add(i);
  }
  if (rung >= 3) for (const match of text.matchAll(/^[\t ]+/gm)) {
    for(let i=match.index;i<match.index+match[0].length;i++) excluded.add(i);
  }
  for(let i=0;i<text.length;i++) {
    if (excluded.has(i) || (rung >= 1 && text[i] === '\r' && text[i+1] === '\n')) continue;
    value += text[i]; offsets.push(i);
  }
  return { value, offsets };
}

function findMatches(text, needle) {
  const labels = ['exact', 'line-endings', 'trailing-whitespace', 'indentation'];
  for(let rung=0;rung<labels.length;rung++) {
    const source = normalized(text,rung), target = normalized(needle,rung).value;
    if(!target) continue;
    const ranges = [];
    for(let at=source.value.indexOf(target);at!==-1;at=source.value.indexOf(target,at+target.length)) {
      ranges.push([source.offsets[at],source.offsets[at+target.length-1]+1]);
    }
    if(ranges.length) return { ranges, match: labels[rung] };
  }
  return { ranges: [] };
}

function collect(args) {
  if (Array.isArray(args.edits) && args.edits.length) {
    return args.edits.map((e, i) => ({
      index: i,
      oldString: e.old_string ?? "",
      newString: e.new_string ?? "",
      replaceAll: Boolean(e.replace_all),
    }));
  }
  if (args.old_string !== undefined) {
    return [
      {
        index: 0,
        oldString: args.old_string,
        newString: args.new_string ?? "",
        replaceAll: Boolean(args.replace_all),
      },
    ];
  }
  return null;
}

/** Applies every edit to an in-memory copy. Returns { text, applied } or { error }. */
function applyEdits(original, edits) {
  let text = original;
  const applied = [];

  for (const edit of edits) {
    if (edit.oldString === "") {
      return { error: `edit ${edit.index + 1}: old_string must not be empty.` };
    }
    if(typeof edit.oldString !== 'string' || typeof edit.newString !== 'string') return {error:'old_string and new_string must be strings.'};
    const found = findMatches(text, edit.oldString);
    const count = found.ranges.length;
    if (count === 0) {
      return {
        error:
          `edit ${edit.index + 1}: old_string not found. ` +
          `Read the file and copy the exact text (check indentation).`,
      };
    }
    if (count > 1 && !edit.replaceAll) {
      return {
        error:
          `edit ${edit.index + 1}: old_string matches ${count} times. ` +
          `Add surrounding context to make it unique, or set replace_all: true.`,
      };
    }
    const replacement = edit.newString.replace(/\r\n/g,'\n');
    const eol = text.includes('\r\n') ? '\r\n' : '\n';
    for(const [start,end] of found.ranges.reverse()) {
      text = text.slice(0,start) + replacement.replace(/\n/g,eol) + text.slice(end);
    }
    applied.push({ index: edit.index, count, match: found.match });
  }

  return { text, applied };
}

export function prepare(args, ctx) {
  const p = resolvePath(args.path, ctx);
  const edits = collect(args);
  if (!edits) return { error: "provide old_string/new_string, or an edits array." };

  let file;
  try {
    const stat = assertReadable(p);
    if (stat.size > 5_000_000) return { error: `file too large to edit safely (${stat.size} bytes).` };
    file = readTextFile(p);
  } catch (err) {
    return { error: err.message };
  }

  const result = applyEdits(file.raw, edits);
  if (result.error) return { error: result.error };

  const next = restoreTrailing(result.text.replace(/\r\n/g,'\n'), file.trailingNewline);
  const diff = diffText(file.text, next);
  return { p, file, next, diff, applied: result.applied, edits };
}

function describe(plan) {
  const range = touchedRange(plan.diff);
  const where = range ? ` at lines ${range.from}-${range.to}` : "";
  const plural = plan.applied.length > 1 ? ` (${plan.applied.length} edits)` : "";
  return `${stats(plan.diff)} \u00b7 ${plan.diff.ops.filter((o) => o.type !== " ").length} line${
    plan.diff.ops.filter((o) => o.type !== " ").length === 1 ? "" : "s"
  } changed${where}${plural}`;
}

export function approval(args, ctx, ui) {
  const plan = rememberPlan(name, args, ctx, prepare(args, ctx));
  if (plan.error) return `${resolvePath(args.path, ctx)}\n\n${ui.red(plan.error)}`;
  const body = ui.diff(plan.file.text, plan.next);
  return `${ui.bold(plan.p)}  ${ui.dim(describe(plan))}\n\n${body}`;
}

export function run(args, ctx) {
  const plan = executionPlan(name, args, ctx, prepare);
  if (plan.error) return `Error: ${plan.error}`;
  if (!plan.diff.changed) return `No change: ${plan.p} already contains that text.`;

  writeTextFile(plan.p, plan.next, plan.file.eol);
  return `Edited ${plan.p}\n${describe(plan)}\n${plan.applied.map(e => `edit ${e.index+1}: ${e.match} match (${e.count})`).join('\n')}`;
}
