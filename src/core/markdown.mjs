import { colorEnabled } from "./ui.mjs";

const ANSI_RE = /\x1b\[[0-9;]*m/g;

export function visibleWidth(s) {
  return String(s).replace(ANSI_RE, "").length;
}

const sgr = (code) => (s) => (colorEnabled ? `\x1b[${code}m${s}\x1b[0m` : String(s));

const paint = {
  bold: sgr("1"),
  dim: sgr("90"),
  italic: sgr("3"),
  strike: sgr("9"),
  red: sgr("31"),
  green: sgr("32"),
  yellow: sgr("33"),
  blue: sgr("34"),
  magenta: sgr("35"),
  cyan: sgr("36"),
  gray: sgr("38;5;245"),
  code: sgr("38;5;180"),
  link: sgr("4;36"),
  kw: sgr("38;5;170"),
  str: sgr("38;5;114"),
  num: sgr("38;5;180"),
  com: sgr("38;5;242;3"),
  fn: sgr("38;5;116"),
  op: sgr("38;5;245"),
  ty: sgr("38;5;222"),
  head: sgr("1;38;5;111"),
};

/* ------------------------------------------------------------------ */
/* syntax highlighting                                                 */
/* ------------------------------------------------------------------ */

const COMMON_KW =
  "if else for while return break continue function class const let var new delete typeof instanceof in of this super import export from default try catch finally throw async await yield switch case do with extends static get set";

const LANGS = {
  js: {
    line: ["//"],
    block: ["/*", "*/"],
    kw: COMMON_KW + " null true false undefined void",
    types: "String Number Boolean Object Array Promise Map Set Error JSON Math Date",
  },
  ts: {
    line: ["//"],
    block: ["/*", "*/"],
    kw: COMMON_KW + " null true false undefined void interface type enum implements readonly private public protected abstract as satisfies keyof infer",
    types: "string number boolean any unknown never void object Array Promise Record Partial Omit Pick",
  },
  py: {
    line: ["#"],
    block: ['"""', '"""'],
    kw: "def class return if elif else for while in is not and or None True False import from as with try except finally raise lambda pass break continue global nonlocal yield assert del async await match case",
    types: "str int float bool list dict set tuple bytes object print len range enumerate zip open",
  },
  sh: {
    line: ["#"],
    kw: "if then else elif fi for while do done case esac function return in export local readonly set unset echo cd exit source alias",
    types: "",
  },
  ps: {
    line: ["#"],
    kw: "if else elseif foreach for while do until switch function return param begin process end try catch finally throw exit break continue",
    types: "Write-Host Write-Output Get-ChildItem Get-Content Set-Content Remove-Item New-Item Test-Path Select-Object Where-Object ForEach-Object Measure-Object Join-Path",
  },
  json: { line: [], block: [], kw: "true false null", types: "" },
  css: {
    line: ["//"],
    block: ["/*", "*/"],
    kw: "",
    types: "",
  },
  sql: {
    line: ["--"],
    block: ["/*", "*/"],
    kw: "select from where insert into values update set delete create table drop alter add index join left right inner outer on group by order having limit offset union distinct as and or not null is in like between exists count sum avg min max",
    types: "int varchar text boolean timestamp date",
  },
  yaml: { line: ["#"], block: [], kw: "true false null", types: "" },
  go: {
    line: ["//"],
    block: ["/*", "*/"],
    kw: "func package import return if else for range switch case default var const type struct interface map chan go defer select break continue nil true false",
    types: "string int int64 float64 bool byte rune error make new len cap append print println fmt",
  },
  rust: {
    line: ["//"],
    block: ["/*", "*/"],
    kw: "fn let mut const struct enum impl trait for while loop if else match return use mod pub crate self super where async await move ref dyn box",
    types: "i32 i64 u32 u64 usize f32 f64 bool String str Vec Option Result Some None Ok Err println",
  },
  c: {
    line: ["//"],
    block: ["/*", "*/"],
    kw: "if else for while do return break continue switch case default goto sizeof struct union enum typedef static extern const volatile inline void",
    types: "int char float double long short unsigned signed size_t bool NULL",
  },
  rb: {
    line: ["#"],
    block: [],
    kw: "def end class module if elsif else unless while until for in do return yield begin rescue ensure raise require attr_accessor nil true false and or not then",
    types: "puts print p gets new",
  },
};

// Language specs are module-local and stable across lines, blocks, and redraws.
for (const spec of Object.values(LANGS)) {
  spec.kw = new Set(spec.kw.split(/\s+/).filter(Boolean));
  spec.types = new Set(spec.types.split(/\s+/).filter(Boolean));
}

const ALIASES = {
  javascript: "js",
  jsx: "js",
  mjs: "js",
  cjs: "js",
  node: "js",
  typescript: "ts",
  tsx: "ts",
  python: "py",
  py3: "py",
  bash: "sh",
  shell: "sh",
  zsh: "sh",
  console: "sh",
  powershell: "ps",
  pwsh: "ps",
  ps1: "ps",
  golang: "go",
  rs: "rust",
  cpp: "c",
  "c++": "c",
  h: "c",
  hpp: "c",
  java: "c",
  cs: "c",
  csharp: "c",
  ruby: "rb",
  yml: "yaml",
  jsonc: "json",
  json5: "json",
  html: "css",
  xml: "css",
  md: "yaml",
  markdown: "yaml",
  toml: "yaml",
  ini: "yaml",
  env: "yaml",
  text: null,
  txt: null,
  "": null,
};

function langSpec(lang) {
  if (!lang) return null;
  const key = String(lang).toLowerCase().trim();
  if (key in ALIASES) {
    const target = ALIASES[key];
    return target ? LANGS[target] : null;
  }
  return LANGS[key] || null;
}

const ID_START = /[A-Za-z_$]/;
const ID_CHAR = /[A-Za-z0-9_$]/;

function highlightLine(line, spec, state) {
  let out = "";
  let i = 0;
  const kw = spec?.kw;
  const types = spec?.types;
  const lineComments = spec ? spec.line : ["//", "#"];

  while (i < line.length) {
    if (state.blockEnd) {
      const end = line.indexOf(state.blockEnd, i);
      if (end === -1) return out + paint.com(line.slice(i));
      out += paint.com(line.slice(i, end + state.blockEnd.length));
      i = end + state.blockEnd.length;
      state.blockEnd = null;
      continue;
    }

    if (lineComments.some((p) => p && line.startsWith(p, i))) {
      return out + paint.com(line.slice(i));
    }
    if (spec) {
      const opener = spec.block.find((p, idx) => idx % 2 === 0 && p && line.startsWith(p, i));
      if (opener) {
        const closer = spec.block[spec.block.indexOf(opener) + 1];
        const end = closer ? line.indexOf(closer, i + opener.length) : -1;
        if (end === -1) {
          state.blockEnd = closer || null;
          return out + paint.com(line.slice(i));
        }
        out += paint.com(line.slice(i, end + closer.length));
        i = end + closer.length;
        continue;
      }
    }

    const ch = line[i];

    if (ch === '"' || ch === "'" || ch === "`") {
      let j = i + 1;
      while (j < line.length) {
        if (line[j] === "\\") j += 2;
        else if (line[j] === ch) {
          j++;
          break;
        } else j++;
      }
      out += paint.str(line.slice(i, j));
      i = j;
      continue;
    }

    if (/[0-9]/.test(ch) && !ID_CHAR.test(line[i - 1] || "")) {
      let j = i;
      while (j < line.length && /[0-9a-fA-FxX._]/.test(line[j])) j++;
      out += paint.num(line.slice(i, j));
      i = j;
      continue;
    }

    if (ID_START.test(ch)) {
      let j = i;
      while (j < line.length && ID_CHAR.test(line[j])) j++;
      const word = line.slice(i, j);
      let rest = j;
      while (rest < line.length && line[rest] === " ") rest++;
      const called = line[rest] === "(";

      if (kw?.has(word)) out += paint.kw(word);
      else if (types?.has(word) || /^[A-Z][A-Za-z0-9_]*$/.test(word)) out += paint.ty(word);
      else if (called) out += paint.fn(word);
      else out += word;
      i = j;
      continue;
    }

    if (/[{}()[\];:,.<>=+\-*/%!&|^~?@]/.test(ch)) {
      let j = i;
      while (j < line.length && /[{}()[\];:,.<>=+\-*/%!&|^~?@]/.test(line[j])) j++;
      out += paint.op(line.slice(i, j));
      i = j;
      continue;
    }

    out += ch;
    i++;
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* inline spans                                                        */
/* ------------------------------------------------------------------ */

const INLINE_RE = new RegExp(
  [
    /(\*\*|__)([^*_]+)\1/, // bold
    /~~([^~]+)~~/, // strike
    /`([^`]+)`/, // code
    /\*([^*\n]+)\*/, // italic
    /_([^_\n]+)_/, // italic
    /\[([^\]]*)\]\(([^)\s]+)\)/, // link
  ]
    .map((r) => r.source)
    .join("|"),
  "g"
);

/** Splits inline markdown into styled runs: [{ text, style }]. */
function inlineRuns(text) {
  const runs = [];
  let last = 0;
  INLINE_RE.lastIndex = 0;
  let m;

  const push = (t, style) => {
    if (t) runs.push({ text: t, style });
  };

  while ((m = INLINE_RE.exec(text))) {
    if (m.index > last) push(text.slice(last, m.index), null);
    const [full, boldA, boldB, strike, code, italA, italB, linkText, linkUrl] = m;

    if (boldA !== undefined) push(boldB, paint.bold);
    else if (strike !== undefined) push(strike, paint.strike);
    else if (code !== undefined) push(code, paint.code);
    else if (italA !== undefined) push(italA, paint.italic);
    else if (italB !== undefined) push(italB, paint.italic);
    else if (linkUrl !== undefined) {
      push(linkText || linkUrl, paint.link);
      if (linkText && linkText !== linkUrl) push(" (" + linkUrl + ")", paint.dim);
    }
    last = m.index + full.length;
  }
  if (last < text.length) push(text.slice(last), null);
  if (!runs.length) push(text, null);
  return runs;
}

const style = (s) => (s ? s : (x) => x);

/** Word-wraps styled runs into lines, each at most `width` visible columns. */
function layout(runs, width, firstPrefix, contPrefix) {
  const words = [];
  for (const r of runs) {
    for (const piece of r.text.split(/(\s+)/)) {
      if (piece !== "") words.push({ text: piece, style: r.style });
    }
  }

  const lines = [];
  let line = firstPrefix;
  let len = visibleWidth(firstPrefix);
  let hasWord = false;

  for (const w of words) {
    if (/^\s+$/.test(w.text)) {
      if (hasWord) {
        line += " ";
        len += 1;
      }
      continue;
    }
    const wl = visibleWidth(w.text);
    if (hasWord && len + wl > width) {
      lines.push(line.replace(/\s+$/, ""));
      line = contPrefix;
      len = visibleWidth(contPrefix);
      hasWord = false;
    }
    line += style(w.style)(w.text);
    len += wl;
    hasWord = true;
  }

  lines.push(hasWord ? line.replace(/\s+$/, "") : line.replace(/\s+$/, ""));
  return lines;
}

/** ANSI-aware hard wrap, used for code where long tokens cannot be broken on spaces. */
function hardWrap(str, width) {
  if (visibleWidth(str) <= width) return [str];
  const out = [];
  let cur = "";
  let len = 0;
  let i = 0;
  while (i < str.length) {
    if (str[i] === "\x1b") {
      const end = str.indexOf("m", i);
      if (end !== -1) {
        cur += str.slice(i, end + 1);
        i = end + 1;
        continue;
      }
    }
    if (len >= width) {
      out.push(cur + (colorEnabled ? "\x1b[0m" : ""));
      cur = "";
      len = 0;
    }
    cur += str[i++];
    len++;
  }
  if (cur) out.push(cur);
  return out;
}

/* ------------------------------------------------------------------ */
/* block renderer                                                      */
/* ------------------------------------------------------------------ */

const GUTTER = "  \u2502 "; //  "  │ "
const BLANK = "  \u2502";
const CONT = "  \u2502 ";

/**
 * Renders markdown to an array of terminal lines.
 * Every returned line is guaranteed to be <= width visible columns.
 */
// Greedy body: the closing fence is the *last* one, so a nested code block
// inside the reply does not terminate the match early.
const WHOLE_FENCE = /^\s*```[ \t]*([\w+#.-]*)[ \t]*\r?\n([\s\S]*)\r?\n?[ \t]*```\s*$/;
const MARKDOWN_LANGS = new Set(["", "markdown", "md", "mdx", "gfm"]);

/** Models often wrap the entire reply in a ```markdown fence. Unwrap those. */
function unwrapWholeFence(text) {
  let current = text;
  for (let i = 0; i < 3; i++) {
    const m = WHOLE_FENCE.exec(current);
    if (!m || !MARKDOWN_LANGS.has((m[1] || "").toLowerCase())) break;
    current = m[2];
  }
  return current;
}

export function renderMarkdown(text, { width = 80 } = {}) {
  const W = Math.max(20, width);
  const contentW = W - visibleWidth(GUTTER) - 1;
  const out = [];
  const src = unwrapWholeFence(String(text ?? "").replace(/\r\n?/g, "\n")).split("\n");

  const emit = (lines) => out.push(...lines);
  const para = (runs, firstPrefix = GUTTER, contPrefix = CONT) =>
    emit(layout(runs, contentW, firstPrefix, contPrefix));

  const codeBlock = (codeLines, lang) => {
    while (codeLines.length && /^\s*$/.test(codeLines[codeLines.length - 1])) codeLines.pop();
    while (codeLines.length && /^\s*$/.test(codeLines[0])) codeLines.shift();
    if (!codeLines.length) return;

    const total = W - 3;
    const innerW = total - 6;
    const label = lang ? " " + lang + " " : "";
    const lead = lang ? "\u2500" + label : "";
    const fill = Math.max(0, total - 4 - visibleWidth(lead));
    out.push(paint.dim("  \u256d" + lead + "\u2500".repeat(fill) + "\u256e"));

    let state = { blockEnd: null };
    const spec = langSpec(lang);
    for (const raw of codeLines) {
      const painted = highlightLine(raw, spec, state);
      const chunks = hardWrap(painted, innerW);
      for (const chunk of chunks) {
        const pad = " ".repeat(Math.max(0, innerW - visibleWidth(chunk)));
        out.push(paint.dim("  \u2502 ") + chunk + pad + paint.dim(" \u2502"));
      }
    }
    out.push(paint.dim("  \u2570" + "\u2500".repeat(total - 4) + "\u256f"));
  };

  const table = (rows) => {
    const cells = rows.map((r) =>
      r
        .replace(/^\s*\|/, "")
        .replace(/\|\s*$/, "")
        .split("|")
        .map((c) => c.trim())
    );
    const header = cells[0];
    const body = cells.slice(1);
    const widths = header.map((h, i) =>
      Math.max(visibleWidth(h), ...body.map((r) => visibleWidth(r[i] ?? "")))
    );

    const row = (cells, paintFn) =>
      (
        GUTTER +
        cells
          .map((cell, i) => {
            const raw = cell ?? "";
            const pad = " ".repeat(Math.max(0, widths[i] - visibleWidth(raw)));
            return paintFn ? paintFn(raw) + pad : raw + pad;
          })
          .join(paint.dim("  \u2502 "))
      ).replace(/\s+$/, "");

    const total = widths.reduce((a, b) => a + b, 0) + 4 * (widths.length - 1);
    if (total + 4 <= W) {
      out.push(row(header, paint.head));
      out.push(
        paint.dim(GUTTER + widths.map((w) => "\u2500".repeat(w)).join("\u2500\u2500\u253c\u2500"))
      );
      for (const r of body) out.push(row(r, null));
    } else {
      for (const r of body) para(inlineRuns(`${r[0]}: ${r.slice(1).join(" ")}`));
    }
  };

  const isTableDivider = (l) => /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(l) && l.includes("-");
  const isTableRow = (l) => /^\s*\|.*\|\s*$/.test(l);

  for (let i = 0; i < src.length; i++) {
    const line = src[i];

    const fence = line.match(/^\s*(`{3,}|~{3,})\s*([\w+#.-]*)\s*$/);
    if (fence) {
      const marker = fence[1][0];
      const lang = fence[2];
      const body = [];
      i++;
      while (i < src.length && !new RegExp("^\\s*" + marker + "{3,}\\s*$").test(src[i])) {
        body.push(src[i]);
        i++;
      }
      codeBlock(body, lang);
      continue;
    }

    if (/^\s*$/.test(line)) {
      out.push(BLANK);
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      const level = heading[1].length;
      const text = inlineRuns(heading[2]);
      const runs = text.map((r) => ({ ...r, style: level <= 2 ? paint.head : paint.bold }));
      para(runs);
      if (level === 1) out.push(paint.dim(GUTTER + "\u2500".repeat(Math.min(contentW, 40))));
      continue;
    }

    if (/^\s*([-*_])\s*(\1\s*){2,}$/.test(line)) {
      out.push(paint.dim(GUTTER + "\u2500".repeat(Math.min(contentW, 40))));
      continue;
    }

    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) {
      para(inlineRuns(quote[1]).map((r) => ({ ...r, style: paint.italic })), GUTTER + paint.dim("\u2502 "), GUTTER + paint.dim("\u2502 "));
      continue;
    }

    if (isTableRow(line) && i + 1 < src.length && isTableDivider(src[i + 1])) {
      const rows = [line];
      i += 2;
      while (i < src.length && isTableRow(src[i])) {
        rows.push(src[i]);
        i++;
      }
      i--;
      table(rows);
      continue;
    }

    const bullet = line.match(/^(\s*)([-*+])\s+(.*)$/);
    if (bullet) {
      const depth = Math.min(3, Math.floor(bullet[1].replace(/\t/g, "  ").length / 2));
      const glyph = depth === 0 ? paint.cyan("\u2022") : paint.dim("\u25e6");
      const prefix = GUTTER + "  ".repeat(depth) + glyph + " ";
      para(inlineRuns(bullet[3]), prefix, GUTTER + "  ".repeat(depth + 1) + "  ");
      continue;
    }

    const ordered = line.match(/^(\s*)(\d+)[.)]\s+(.*)$/);
    if (ordered) {
      const depth = Math.min(3, Math.floor(ordered[1].replace(/\t/g, "  ").length / 2));
      const prefix = GUTTER + "  ".repeat(depth) + paint.dim(ordered[2] + ".") + " ";
      para(inlineRuns(ordered[3]), prefix, GUTTER + "  ".repeat(depth + 1) + "   ");
      continue;
    }

    const paragraph = [line];
    while (
      i + 1 < src.length &&
      !/^\s*$/.test(src[i + 1]) &&
      !/^\s*(`{3,}|~{3,})/.test(src[i + 1]) &&
      !/^#{1,6}\s/.test(src[i + 1]) &&
      !/^\s*([-*+])\s+/.test(src[i + 1]) &&
      !/^\s*\d+[.)]\s+/.test(src[i + 1]) &&
      !/^\s*>\s?/.test(src[i + 1]) &&
      !isTableRow(src[i + 1])
    ) {
      paragraph.push(src[i + 1]);
      i++;
    }
    para(inlineRuns(paragraph.join(" ")));
  }

  return out.map((l) => (visibleWidth(l) > W ? cutTo(l, W - 1) : l));
}

/** ANSI-aware truncation to `width` visible columns. */
function cutTo(str, width) {
  let cur = "";
  let len = 0;
  let i = 0;
  while (i < str.length && len < width) {
    if (str[i] === "\x1b") {
      const end = str.indexOf("m", i);
      if (end !== -1) {
        cur += str.slice(i, end + 1);
        i = end + 1;
        continue;
      }
    }
    cur += str[i++];
    len++;
  }
  return cur + (colorEnabled ? "\x1b[0m" : "");
}

/* ------------------------------------------------------------------ */
/* live streaming renderer                                             */
/* ------------------------------------------------------------------ */

export class LiveRenderer {
  constructor({ write = (s) => process.stdout.write(s), width = process.stdout.columns || 80 } = {}) {
    this.write = write;
    this.width = Math.max(24, width);
    this.buf = "";
    this.tty = Boolean(process.stdout.isTTY && process.stdout.rows);
    this.drawTimer = null;
    this.closed = false;

    // Lines above the cursor that are finished and never redrawn.
    this.committed = 0;
    // Lines between `committed` and the cursor: the redrawable region.
    this.drawn = 0;
    this.lastLines = [];

    this.onResize = () => {
      if (this.closed) return;
      this.width = Math.max(24, process.stdout.columns || 80);
      if (this.tty) this.draw();
    };
    if (this.tty) process.stdout.on("resize", this.onResize);
  }

  lines() {
    return renderMarkdown(this.buf, { width: this.width });
  }

  /**
   * Redraws the live region only.
   *
   * Long replies would otherwise have a live region taller than the terminal,
   * which makes cursor-up escape codes land off-screen. Instead the top of the
   * render is "committed": left on screen above the cursor, never rewritten,
   * keeping the redrawable region at most one screen tall.
   *
   * A line is only committed once it is byte-identical to what the previous
   * render produced, so a block that reflows (a table, an unwrapped fence)
   * can never leave a stale line stranded in the scrollback.
   */
  draw() {
    if (this.closed) return;
    const lines = this.lines();

    if (!this.tty) {
      this.lastLines = lines;
      return;
    }

    const rows = process.stdout.rows || 40;
    const maxLive = Math.max(6, rows - 4);

    let stable = 0;
    const n = Math.min(this.lastLines.length, lines.length);
    while (stable < n && this.lastLines[stable] === lines[stable]) stable++;

    const wantCommit = Math.max(0, lines.length - maxLive);
    const hardCap = Math.max(0, lines.length - 3);
    const target = Math.min(wantCommit, hardCap);
    const newCommitted = Math.min(Math.max(this.committed, target), Math.max(this.committed, stable));

    let frame = "";
    if (this.drawn > 0) frame += `\x1b[${this.drawn}A`;
    frame += "\x1b[J";
    if (newCommitted > this.committed) {
      frame += lines.slice(this.committed, newCommitted).join("\n") + "\n";
    }
    frame += lines.slice(newCommitted).join("\n") + "\n";
    this.write(frame);

    this.committed = newCommitted;
    this.drawn = lines.length - newCommitted;
    this.lastLines = lines;
  }

  push(delta) {
    if (this.closed || !delta) return;
    this.buf += delta;
    if (this.tty && this.drawTimer === null) {
      // Keep a fixed frame deadline: continuous tokens must not postpone it.
      this.drawTimer = setTimeout(() => {
        this.drawTimer = null;
        this.draw();
      }, 20);
    }
  }

  finish() {
    if (this.closed) return this.buf;
    if (this.drawTimer !== null) {
      clearTimeout(this.drawTimer);
      this.drawTimer = null;
    }
    if (this.tty) process.stdout.removeListener("resize", this.onResize);

    try {
      if (!this.tty) {
        this.write(renderMarkdown(this.buf, { width: this.width }).join("\n") + "\n");
      } else if (this.buf) {
        this.draw();
      }
      return this.buf;
    } finally {
      this.closed = true;
    }
  }
}
