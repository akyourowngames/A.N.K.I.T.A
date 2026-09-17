import { resolvePath, assertReadable, readTextFile, writeTextFile } from "./_shared.mjs";
import { diffText, stats, touchedRange } from "./_diff.mjs";

export const name = "edit_lines";
export const description =
  "Edit a file by line number, for changes that string matching handles badly (inserting whole blocks, " +
  "deleting ranges, replacing a function body). Every edit is validated before anything is written, so a " +
  "bad line number changes nothing. Modes: replace (default), insert_before, insert_after, delete.";

export const parameters = {
  type: "object",
  properties: {
    path: { type: "string", description: "File path, absolute or relative to the working directory." },
    edits: {
      type: "array",
      description: "Line edits applied atomically. Ranges refer to the original file.",
      items: {
        type: "object",
        properties: {
          start_line: { type: "integer", description: "1-based first line of the range." },
          end_line: {
            type: "integer",
            description: "1-based last line of the range, inclusive. Defaults to start_line.",
          },
          mode: {
            type: "string",
            enum: ["replace", "insert_before", "insert_after", "delete"],
            description: "What to do with the range. Default replace.",
          },
          content: {
            type: "string",
            description: "Text to write. Multi-line strings are split on \\n. Required unless mode is delete.",
          },
        },
        required: ["start_line"],
      },
    },
  },
  required: ["path", "edits"],
};

const MODES = new Set(["replace", "insert_before", "insert_after", "delete"]);

function bodyLines(text, trailingNewline) {
  const body = trailingNewline ? text.replace(/\n$/, "") : text;
  return body === "" ? [] : body.split("\n");
}

function validate(list, total) {
  const normalised = [];

  for (let i = 0; i < list.length; i++) {
    const raw = list[i] ?? {};
    const mode = raw.mode ?? "replace";
    if (!MODES.has(mode)) return { error: `edit ${i + 1}: unknown mode "${raw.mode}".` };

    const start = Number(raw.start_line);
    if (!Number.isInteger(start)) return { error: `edit ${i + 1}: start_line must be an integer.` };
    let end = raw.end_line === undefined || raw.end_line === null ? start : Number(raw.end_line);
    if (!Number.isInteger(end)) return { error: `edit ${i + 1}: end_line must be an integer.` };
    if (end < start) return { error: `edit ${i + 1}: end_line (${end}) is before start_line (${start}).` };

    // Insert modes may address one past the last line, which appends.
    const isInsert = mode === "insert_before" || mode === "insert_after";
    const maxLine = isInsert ? total + 1 : total;
    if (start < 1 || start > maxLine) {
      return {
        error: `edit ${i + 1}: start_line ${start} is out of range (file has ${total} line${total === 1 ? "" : "s"}${isInsert ? `, so 1-${total + 1} is valid` : ""}).`,
      };
    }
    if (end > maxLine) {
      return { error: `edit ${i + 1}: end_line ${end} is past the end of the file (${total} lines).` };
    }

    const content = raw.content;
    if (mode !== "delete" && content === undefined) {
      return { error: `edit ${i + 1}: content is required for mode "${mode}".` };
    }
    const lines = Array.isArray(content)
      ? content.map(String)
      : String(content ?? "").replace(/\r\n?/g, "\n").split("\n");

    normalised.push({ index: i, mode, start, end, lines });
  }

  const ordered = [...normalised].sort((a, b) => a.start - b.start);
  for (let i = 1; i < ordered.length; i++) {
    if (ordered[i].start <= ordered[i - 1].end) {
      return {
        error: `edits ${ordered[i - 1].index + 1} and ${ordered[i].index + 1} overlap (lines ${ordered[i - 1].start}-${ordered[i - 1].end} and ${ordered[i].start}-${ordered[i].end}).`,
      };
    }
  }
  return { edits: normalised };
}

export function prepare(args, ctx) {
  const p = resolvePath(args.path, ctx);
  const list = Array.isArray(args.edits) ? args.edits : null;
  if (!list || !list.length) return { error: "provide an edits array with at least one entry." };

  let file;
  try {
    const stat = assertReadable(p);
    if (stat.size > 5_000_000) return { error: `file too large to edit safely (${stat.size} bytes).` };
    file = readTextFile(p);
  } catch (err) {
    return { error: err.message };
  }

  const lines = bodyLines(file.text, file.trailingNewline);
  const checked = validate(list, lines.length);
  if (checked.error) return { error: checked.error };

  // Apply from the bottom up so earlier range numbers stay valid.
  let working = [...lines];
  for (const edit of [...checked.edits].sort((a, b) => b.start - a.start)) {
    const at = edit.start - 1;
    const removeCount = edit.mode === "replace" || edit.mode === "delete" ? edit.end - edit.start + 1 : 0;
    const insertAt = Math.min(edit.mode === "insert_after" ? edit.end : at, working.length);
    const inserted = edit.mode === "delete" ? [] : edit.lines;
    working.splice(insertAt, removeCount, ...inserted);
  }

  const nextBody = working.join("\n");
  const next = file.trailingNewline ? nextBody + "\n" : nextBody;
  const diff = diffText(file.text, next);

  return { p, file, next, diff, count: checked.edits.length, edits: checked.edits };
}

function describe(plan) {
  const range = touchedRange(plan.diff);
  const where = range ? ` at lines ${range.from}-${range.to}` : "";
  const plural = plan.count > 1 ? ` (${plan.count} edits)` : "";
  return `${stats(plan.diff)}${where}${plural}`;
}

export function approval(args, ctx, ui) {
  const plan = prepare(args, ctx);
  if (plan.error) return `${resolvePath(args.path, ctx)}\n\n${ui.red(plan.error)}`;
  if (!plan.diff.changed) return `${ui.bold(plan.p)}\n\n${ui.dim("no change")}`;
  return `${ui.bold(plan.p)}  ${ui.dim(describe(plan))}\n\n${ui.diff(
    plan.file.text,
    plan.next,
    { width: ctx.width }
  )}`;
}

export function run(args, ctx) {
  const plan = prepare(args, ctx);
  if (plan.error) return `Error: ${plan.error}`;
  if (!plan.diff.changed) return `No change: ${plan.p}`;

  writeTextFile(plan.p, plan.next, plan.file.eol);
  return `Edited ${plan.p} by line\n${stats(plan.diff)}${
    touchedRange(plan.diff) ? ` \u00b7 lines ${touchedRange(plan.diff).from}-${touchedRange(plan.diff).to}` : ""
  }\n${plan.edits.map((e) => `  ${e.mode} lines ${e.start}-${e.end}`).join("\n")}`;
}
