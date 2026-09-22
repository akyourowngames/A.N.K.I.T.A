import fs from 'node:fs';
import path from 'node:path';
import { diffText, stats } from './_diff.mjs';

export const name = 'apply_patch';
export const description = 'Apply a standard unified diff across workspace files, including creation, deletion, and renames. All hunks are validated before writing; staged replacements are rolled back on failure. Binary patches and symlinks are unsupported. Shows all changes for approval.';
export const needsApproval = true;
export const parameters = {
  type: 'object',
  properties: { patch: { type: 'string', description: 'Standard unified diff (optionally with diff --git headers). Use workspace-relative a/ and b/ paths, /dev/null for creation/deletion, and rename from/to for moves.' } },
  required: ['patch'],
  additionalProperties: false,
};

function fail(message) { throw new Error(message); }

// Git quotes non-ASCII path bytes using C-style octal escapes.
function unquote(value) {
  if (!value.startsWith('"')) return value;
  if (!value.endsWith('"')) fail('Malformed quoted patch path.');
  const bytes = [];
  const escapes = { a: 7, b: 8, t: 9, n: 10, v: 11, f: 12, r: 13, '\\': 92, '"': 34 };
  for (let i = 1; i < value.length - 1; i++) {
    if (value[i] !== '\\') {
      const cp = value.codePointAt(i);
      bytes.push(...Buffer.from(String.fromCodePoint(cp)));
      if (cp > 0xffff) i++;
      continue;
    }
    const next = value[++i];
    if (/[0-7]/.test(next ?? '')) {
      let digits = next;
      while (digits.length < 3 && /[0-7]/.test(value[i + 1] ?? '')) digits += value[++i];
      bytes.push(parseInt(digits, 8));
    } else if (Object.hasOwn(escapes, next)) bytes.push(escapes[next]);
    else fail('Unsupported escape in patch path.');
  }
  return new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(bytes));
}

function headerPath(value, prefix) {
  const quoted = value.match(/^"(?:[^"\\]|\\.)*"/);
  const raw = quoted ? quoted[0] : value.split('\t')[0];
  const name = unquote(raw);
  if (name === '/dev/null') return null;
  return name.startsWith(prefix + '/') ? name.slice(2) : name;
}

function gitPaths(line) {
  const value = line.slice('diff --git '.length);
  if (value.startsWith('"')) {
    const match = value.match(/^("(?:[^"\\]|\\.)*") ("(?:[^"\\]|\\.)*"|.+)$/);
    if (!match) fail('Malformed diff --git paths.');
    return [headerPath(match[1], 'a'), headerPath(match[2], 'b')];
  }
  const match = value.match(/^(a\/.*?) (b\/.+|"(?:[^"\\]|\\.)*")$/);
  if (!match) fail('Malformed diff --git paths.');
  return [headerPath(match[1], 'a'), headerPath(match[2], 'b')];
}

function mode(value) {
  if (!/^100[0-7]{3}$/.test(value)) fail(`Unsupported file mode ${value}; only regular files are supported.`);
  return parseInt(value.slice(3), 8);
}

function parse(patch) {
  if (typeof patch !== 'string' || !patch.trim()) fail('patch must be a non-empty unified diff string.');
  if (patch.includes('\0')) fail('Binary patches are unsupported.');
  const rawLines = patch.split('\n');
  const lines = rawLines.map(line => line.endsWith('\r') ? line.slice(0, -1) : line);
  const files = [];
  let file = null;
  const finish = () => {
    if (!file) return;
    if (Boolean(file.renameFrom !== undefined) !== Boolean(file.renameTo !== undefined)) fail('Incomplete rename metadata.');
    if (file.renameFrom !== undefined) {
      if (file.old !== file.renameFrom || file.next !== file.renameTo) fail('Rename metadata does not match patch paths.');
    }
    if (file.old === null && file.next === null) fail('Patch cannot have /dev/null on both sides.');
    if (!file.hunks.length && !file.metadata) fail('Patch contains no hunks or file operation.');
    files.push(file);
    file = null;
  };
  for (let i = 0; i < lines.length;) {
    const line = lines[i];
    if (line.startsWith('diff --git ')) {
      finish();
      const [old, next] = gitPaths(line);
      file = { old, next, hunks: [] };
      i++;
    } else if (line.startsWith('--- ')) {
      if (file?.headers) finish();
      file ??= { hunks: [] };
      if (!lines[i + 1]?.startsWith('+++ ')) fail('Missing +++ file header.');
      const old = headerPath(line.slice(4), 'a');
      const next = headerPath(lines[i + 1].slice(4), 'b');
      if (file.old !== undefined && file.old !== old && !(file.created && old === null)) fail('Conflicting old file paths.');
      if (file.next !== undefined && file.next !== next && !(file.deleted && next === null)) fail('Conflicting new file paths.');
      Object.assign(file, { old, next, headers: true });
      i += 2;
    } else if (line.startsWith('@@')) {
      if (!file?.headers) fail('Hunk requires --- and +++ file headers.');
      const match = line.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$/);
      if (!match) fail('Malformed unified diff hunk header.');
      const hunk = { oldStart: Number(match[1]), oldCount: Number(match[2] ?? 1), newStart: Number(match[3]), newCount: Number(match[4] ?? 1), lines: [] };
      if (![hunk.oldStart, hunk.oldCount, hunk.newStart, hunk.newCount].every(Number.isSafeInteger)) fail('Invalid hunk coordinates.');
      let oldCount = 0, newCount = 0;
      i++;
      while (oldCount < hunk.oldCount || newCount < hunk.newCount) {
        const body = lines[i++];
        if (body === '\\ No newline at end of file') {
          const last = hunk.lines.at(-1);
          if (!last || last.noNewline) fail('Misplaced no-newline marker.');
          last.noNewline = true;
          continue;
        }
        if (!body || ![' ', '+', '-'].includes(body[0])) fail('Hunk line counts do not match its header.');
        const type = body[0];
        if (type !== '+') oldCount++;
        if (type !== '-') newCount++;
        if (oldCount > hunk.oldCount || newCount > hunk.newCount) fail('Hunk line counts exceed its header.');
        hunk.lines.push({ type, text: body.slice(1), noNewline: false, crlf: rawLines[i - 1].endsWith('\r') });
      }
      if (lines[i] === '\\ No newline at end of file') {
        if (!hunk.lines.length) fail('Misplaced no-newline marker.');
        hunk.lines.at(-1).noNewline = true;
        i++;
      }
      file.hunks.push(hunk);
    } else if (/^(GIT binary patch|Binary files )/.test(line)) {
      fail('Binary patches are unsupported.');
    } else if (file && /^(new file mode |deleted file mode |old mode |new mode )/.test(line)) {
      const value = mode(line.slice(line.lastIndexOf(' ') + 1));
      file.metadata = true;
      if (line.startsWith('new file mode ')) Object.assign(file, { old: null, created: true, newMode: value });
      else if (line.startsWith('deleted file mode ')) Object.assign(file, { next: null, deleted: true, oldMode: value });
      else file[line.startsWith('old mode ') ? 'oldMode' : 'newMode'] = value;
      i++;
    } else if (file && /^(rename from |rename to )/.test(line)) {
      const from = line.startsWith('rename from ');
      file[from ? 'renameFrom' : 'renameTo'] = unquote(line.slice(from ? 12 : 10));
      file.metadata = true;
      i++;
    } else if (file && /^(index [0-9a-f]+\.\.[0-9a-f]+(?: [0-7]+)?|(?:dis)?similarity index \d+%)$/.test(line)) {
      const indexMode = line.match(/^index .* ([0-7]+)$/);
      if (indexMode) mode(indexMode[1]);
      i++;
    } else if (line === '' && (i === lines.length - 1 || !file)) i++;
    else fail(`Unsupported or malformed patch line: ${line.slice(0, 120)}`);
  }
  finish();
  if (!files.length) fail('No file changes found in patch.');
  return files;
}

function safePath(root, relative) {
  if (relative === null) return null;
  if (typeof relative !== 'string' || !relative || /[\\:\x00-\x1f\x7f]/.test(relative) || path.isAbsolute(relative)) fail(`Unsafe patch path: ${relative}`);
  const segments = relative.split('/');
  if (segments.some(p => !p || p === '.' || p === '..' || /[ .]$/.test(p) || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(p))) fail(`Unsafe patch path: ${relative}`);
  let current = root;
  for (const segment of segments) {
    current = path.join(current, segment);
    let stat;
    try { stat = fs.lstatSync(current); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (stat?.isSymbolicLink()) fail(`Symbolic links are unsupported in patch paths: ${relative}`);
    if (stat && current !== path.join(root, ...segments) && !stat.isDirectory()) fail(`Parent path is not a directory: ${relative}`);
  }
  return current;
}

function snapshot(p) {
  try {
    const stat = fs.lstatSync(p);
    if (!stat.isFile()) fail(`Not a regular file: ${p}`);
    const bytes = fs.readFileSync(p);
    if (bytes.includes(0)) fail(`Binary files are unsupported: ${p}`);
    const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
    return { bytes, text, mode: stat.mode & 0o777, dev: stat.dev, ino: stat.ino };
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
}

function textLines(text) {
  const result = [];
  const regex = /([^\n]*)(\n|$)/g;
  for (const match of text.matchAll(regex)) {
    if (!match[0]) break;
    const crlf = match[2] && match[1].endsWith('\r');
    result.push({ text: crlf ? match[1].slice(0, -1) : match[1], eol: crlf ? '\r\n' : match[2] });
  }
  return result;
}

function applyHunks(file, original) {
  const source = textLines(original);
  const eol = source.find(line => line.eol)?.eol ?? '\n';
  const output = [];
  let cursor = 0;
  for (const hunk of file.hunks) {
    const start = hunk.oldCount ? hunk.oldStart - 1 : hunk.oldStart;
    const nextStart = hunk.newCount ? hunk.newStart - 1 : hunk.newStart;
    if (start < cursor || start > source.length || nextStart !== output.length + start - cursor) fail(`Invalid or overlapping hunk coordinates in ${file.old ?? file.next}.`);
    output.push(...source.slice(cursor, start));
    cursor = start;
    for (const line of hunk.lines) {
      if (line.type !== '+') {
        const actual = source[cursor++];
        if (!actual || actual.text !== line.text || (actual.eol === '') !== line.noNewline) fail(`Hunk context mismatch in ${file.old ?? file.next} at line ${cursor}.`);
        if (line.type === ' ') output.push(actual);
      } else output.push({ text: line.text, eol: line.noNewline ? '' : line.crlf ? '\r\n' : eol });
    }
  }
  output.push(...source.slice(cursor));
  if (output.some((line, index) => !line.eol && index < output.length - 1)) fail(`No-newline marker occurs before end of file: ${file.next}`);
  return output.map(line => line.text + line.eol).join('');
}

export function prepare(args, ctx) {
  try {
    const root = fs.realpathSync(path.resolve(ctx?.cwd ?? process.cwd()));
    const files = parse(args?.patch);
    const inputs = new Set(), outputs = new Set(), snapshots = new Map();
    const key = p => process.platform === 'win32' ? p.toLowerCase() : p;
    for (const file of files) {
      file.from = safePath(root, file.old);
      file.to = safePath(root, file.next);
      if (file.from && inputs.has(key(file.from))) fail(`Duplicate source path: ${file.old}`);
      if (file.to && outputs.has(key(file.to))) fail(`Duplicate destination path: ${file.next}`);
      if (file.from) inputs.add(key(file.from));
      if (file.to) outputs.add(key(file.to));
      for (const p of [file.from, file.to].filter(Boolean)) if (!snapshots.has(p)) snapshots.set(p, snapshot(p));
      file.original = file.from ? snapshots.get(file.from) : null;
      if (file.from && !file.original) fail(`Source file does not exist: ${file.old}`);
      if (file.to && file.to !== file.from && snapshots.get(file.to)) fail(`Destination already exists: ${file.next}`);
      if (file.oldMode !== undefined && process.platform !== 'win32' && file.original?.mode !== file.oldMode) fail(`Original file mode does not match: ${file.old}`);
      file.text = applyHunks(file, file.original?.text ?? '');
      if (!file.to && file.text !== '') fail(`Deletion patch does not remove the entire file: ${file.old}`);
      file.mode = file.newMode ?? file.original?.mode ?? (0o666 & ~process.umask());
      file.diff = diffText(file.original?.text ?? '', file.text);
    }
    for (const file of files) if (file.to && file.from !== file.to && inputs.has(key(file.to))) fail(`Overlapping move paths are unsupported: ${file.next}`);
    return { root, files, snapshots };
  } catch (error) { return { error: error.message }; }
}

function describe(file) {
  const operation = !file.from ? 'Create' : !file.to ? 'Delete' : file.from !== file.to ? 'Move' : 'Update';
  const target = file.from && file.to && file.from !== file.to ? `${file.old} -> ${file.next}` : file.next ?? file.old;
  const permissions = file.newMode !== undefined ? `; mode ${file.newMode.toString(8)}` : '';
  return `${operation} ${target} (${stats(file.diff)}${permissions})`;
}

export function approval(args, ctx, ui) {
  const plan = prepare(args, ctx);
  if (plan.error) return ui.red(`Error: ${plan.error}`);
  return plan.files.map(file => `${ui.bold(describe(file))}\n${ui.diff(file.original?.text ?? '', file.text)}`).join('\n\n');
}

function verify(plan) {
  for (const [p, original] of plan.snapshots) {
    safePath(plan.root, path.relative(plan.root, p).split(path.sep).join('/'));
    const now = snapshot(p);
    if (Boolean(original) !== Boolean(now) || (original && (original.mode !== now.mode || original.ino !== now.ino || original.dev !== now.dev || !original.bytes.equals(now.bytes)))) fail(`File changed while preparing patch: ${p}`);
  }
}

function commit(plan) {
  const tempDirs = [], createdDirs = [], backups = new Map(), stages = new Map(), changed = [];
  let keepBackups = false;
  function ensureDir(dir) {
    if (fs.existsSync(dir)) return;
    ensureDir(path.dirname(dir));
    fs.mkdirSync(dir);
    createdDirs.push(dir);
  }
  function tempDir(p) {
    ensureDir(path.dirname(p));
    const dir = fs.mkdtempSync(path.join(path.dirname(p), '.ankita-patch-'));
    tempDirs.push(dir);
    return dir;
  }
  try {
    // Stage every output and backup before the first mutation of a user's file.
    for (const [p, original] of plan.snapshots) {
      const dir = tempDir(p);
      if (original) {
        const backup = path.join(dir, 'original');
        fs.writeFileSync(backup, original.bytes, { flag: 'wx', mode: original.mode });
        fs.chmodSync(backup, original.mode);
        backups.set(p, backup);
      }
      const file = plan.files.find(file => file.to === p);
      if (file) {
        const stage = path.join(dir, 'replacement');
        fs.writeFileSync(stage, file.text, { flag: 'wx', mode: file.mode });
        fs.chmodSync(stage, file.mode);
        stages.set(p, stage);
      }
    }
    verify(plan);
    for (const [p, stage] of stages) {
      fs.renameSync(stage, p);
      changed.push(p);
    }
    for (const file of plan.files) if (file.from && file.from !== file.to) {
      fs.unlinkSync(file.from);
      changed.push(file.from);
    }
  } catch (error) {
    const rollbackErrors = [];
    for (const p of changed.reverse()) {
      try {
        if (backups.has(p)) fs.renameSync(backups.get(p), p);
        else fs.unlinkSync(p);
      } catch (rollbackError) { rollbackErrors.push(`${p}: ${rollbackError.message}`); }
    }
    if (rollbackErrors.length) {
      keepBackups = true;
      fail(`${error.message}; rollback incomplete: ${rollbackErrors.join('; ')}. Recovery backups retained in: ${tempDirs.join(', ')}`);
    }
    throw error;
  } finally {
    if (!keepBackups) {
      for (const dir of tempDirs.reverse()) { try { fs.rmSync(dir, { recursive: true, force: true }); } catch { /* Never mask the write result with cleanup failure. */ } }
      for (const dir of createdDirs.reverse()) { try { fs.rmdirSync(dir); } catch { /* Successful output directories are nonempty. */ } }
    }
  }
}

export function run(args, ctx) {
  const plan = prepare(args, ctx);
  if (plan.error) return `Error: ${plan.error}`;
  try {
    commit(plan);
    return `Applied patch to ${plan.files.length} file${plan.files.length === 1 ? '' : 's'}.\n${plan.files.map(describe).join('\n')}`;
  } catch (error) { return `Error: ${error.message}`; }
}
