/**
 * Line diffing, used to show the user exactly what an edit changes.
 * Pure data + presentation helpers: no filesystem access, no globals.
 */

const MAX_LCS_CELLS = 1_500_000;

export function splitLines(text) {
  return String(text ?? "").replace(/\r\n?/g, "\n").split("\n");
}

function lcsOps(a, b) {
  const n = a.length;
  const m = b.length;

  if (n * m > MAX_LCS_CELLS) {
    return [
      ...a.map((text) => ({ type: "-", text })),
      ...b.map((text) => ({ type: "+", text })),
    ];
  }

  const w = m + 1;
  const dp = new Uint32Array((n + 1) * w);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i * w + j] =
        a[i] === b[j]
          ? dp[(i + 1) * w + (j + 1)] + 1
          : Math.max(dp[(i + 1) * w + j], dp[i * w + (j + 1)]);
    }
  }

  const ops = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      ops.push({ type: " ", text: a[i] });
      i++;
      j++;
    } else if (dp[(i + 1) * w + j] >= dp[i * w + (j + 1)]) {
      ops.push({ type: "-", text: a[i] });
      i++;
    } else {
      ops.push({ type: "+", text: b[j] });
      j++;
    }
  }
  while (i < n) ops.push({ type: "-", text: a[i++] });
  while (j < m) ops.push({ type: "+", text: b[j++] });
  return ops;
}

/**
 * Diffs two strings. Common leading and trailing lines are trimmed first, so
 * a small edit inside a large file stays cheap.
 */
export function diffText(oldText, newText) {
  const a = splitLines(oldText);
  const b = splitLines(newText);

  let head = 0;
  while (head < a.length && head < b.length && a[head] === b[head]) head++;

  let tail = 0;
  while (tail < a.length - head && tail < b.length - head && a[a.length - 1 - tail] === b[b.length - 1 - tail]) {
    tail++;
  }

  const ops = [
    ...a.slice(0, head).map((text) => ({ type: " ", text })),
    ...lcsOps(a.slice(head, a.length - tail), b.slice(head, b.length - tail)),
    ...a.slice(a.length - tail).map((text) => ({ type: " ", text })),
  ];

  let aNo = 1;
  let bNo = 1;
  for (const op of ops) {
    op.aNo = op.type === "+" ? null : aNo;
    op.bNo = op.type === "-" ? null : bNo;
    if (op.type !== "+") aNo++;
    if (op.type !== "-") bNo++;
  }

  let added = 0;
  let removed = 0;
  for (const op of ops) {
    if (op.type === "+") added++;
    else if (op.type === "-") removed++;
  }

  return { ops, added, removed, changed: added + removed > 0 };
}

export function stats(diff) {
  const parts = [];
  if (diff.added) parts.push("+" + diff.added);
  if (diff.removed) parts.push("-" + diff.removed);
  return parts.length ? parts.join(" ") : "no change";
}

/** Groups a diff into unified-diff hunks with `context` unchanged lines. */
export function toHunks(diff, context = 2) {
  const groups = [];
  let current = null;

  diff.ops.forEach((op, idx) => {
    if (op.type === " ") return;
    if (current && idx - current.end - 1 <= context * 2) current.end = idx;
    else {
      current = { start: idx, end: idx };
      groups.push(current);
    }
  });

  return groups.map((g) => {
    const from = Math.max(0, g.start - context);
    const to = Math.min(diff.ops.length - 1, g.end + context);
    const lines = diff.ops.slice(from, to + 1);
    const first = lines.find((l) => l.aNo != null) ?? lines[0];
    const firstNew = lines.find((l) => l.bNo != null) ?? lines[0];
    return {
      aStart: first.aNo ?? 0,
      bStart: firstNew.bNo ?? 0,
      aCount: lines.filter((l) => l.type !== "+").length,
      bCount: lines.filter((l) => l.type !== "-").length,
      lines,
    };
  });
}

/** First and last line number touched, for "at lines 12-19" summaries. */
export function touchedRange(diff) {
  const nums = diff.ops.filter((o) => o.type !== " ").map((o) => o.aNo ?? o.bNo);
  if (!nums.length) return null;
  return { from: Math.min(...nums), to: Math.max(...nums) };
}

/**
 * Renders a colored unified diff for the approval prompt.
 * Returns "" when nothing changed.
 */
export function renderDiff(oldText, newText, { ui, context = 2, maxLines = Infinity, width = Infinity } = {}) {
  const diff = diffText(oldText, newText);
  if (!diff.changed) return "";

  const hunks = toHunks(diff, context);
  const out = [];
  const numberW = String(Math.max(...diff.ops.map((o) => o.aNo ?? o.bNo ?? 1))).length;

  outer: for (const hunk of hunks) {
    out.push(
      ui.cyan(
        `@@ -${hunk.aStart},${hunk.aCount} +${hunk.bStart},${hunk.bCount} @@`
      )
    );
    for (const line of hunk.lines) {
      if (out.length >= maxLines) {
        out.push(ui.dim(`... diff truncated (${hunks.length} hunks, ${stats(diff)})`));
        break outer;
      }
      const no = line.type === "+" ? line.bNo : line.aNo;
      const gutter = ui.dim(String(no ?? "").padStart(numberW));
      const body = line.text;
      if (line.type === "-") out.push(`${ui.dim("\u2502")} ${gutter} ${ui.red("- " + body)}`);
      else if (line.type === "+") out.push(`${ui.dim("\u2502")} ${gutter} ${ui.green("+ " + body)}`);
      else out.push(`${ui.dim("\u2502")} ${gutter}   ${ui.dim(body)}`);
    }
  }
  return out.join("\n");
}
