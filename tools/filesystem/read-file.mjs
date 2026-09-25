import fs from "node:fs";
import { resolvePath, assertReadable, isBinary } from "../shared/_shared.mjs";

export const name = "read_file";
export const description =
  "Read a UTF-8 text file. Returns contents with 1-based line numbers, which you can then pass to edit_lines.";

export const parameters = {
  type: "object",
  properties: {
    path: { type: "string", description: "File path, absolute or relative to the working directory." },
    offset: { type: "integer", description: "First line to read (1-indexed). Default 1." },
    limit: { type: "integer", description: "Maximum lines to return. Default 400." },
  },
  required: ["path"],
};

export const readOnly = true;
export const needsApproval = false;

export function run(args, ctx) {
  const p = resolvePath(args.path, ctx);
  const stat = assertReadable(p);
  if (stat.size > 5_000_000) return `Error: file too large (${stat.size} bytes) to read in full.`;

  const buf = fs.readFileSync(p);
  if (isBinary(buf)) return `Error: ${p} looks like a binary file.`;

  // A trailing newline does not start a new line, so that the numbers here
  // match the numbers edit_file/edit_lines expect.
  const raw = buf.toString("utf8");
  const trimmed = raw.replace(/\r\n/g, "\n").replace(/\n$/, "");
  const lines = trimmed === "" ? [] : trimmed.split("\n");
  const total = lines.length;
  const start = Math.max(1, Number(args.offset) || 1);
  const limit = Math.max(1, Number(args.limit) || 400);
  const end = Math.min(total, start + limit - 1);

  if (start > total) return `Error: offset ${start} is past the end of ${p} (${total} lines).`;
  if (total === 0) return `(empty file) ${p}`;

  const body = lines
    .slice(start - 1, end)
    .map((line, i) => `${start + i}: ${line}`)
    .join("\n");

  const notes = [];
  if (end < total) notes.push(`showing lines ${start}-${end} of ${total}`);
  if (!raw.endsWith("\n") && raw.length) notes.push("file does not end with a newline");

  return body + (notes.length ? `\n\n[${notes.join("; ")}]` : "");
}
