import fs from 'node:fs';
import path from 'node:path';
import { promisify } from 'node:util';
import { execFile } from 'node:child_process';
import { jobInfo } from '../../tools/shared/_jobs.mjs';
import { run as stopJob } from '../../tools/process/job-stop.mjs';
import { diffText, toHunks } from '../../tools/shared/_diff.mjs';

const exec = promisify(execFile);
const MAX_FILES = 200;
const MAX_DIFF = 256_000;

async function git(cwd, args) {
  const { stdout } = await exec('git', ['--no-pager', '-c', 'core.fsmonitor=false', ...args], {
    cwd, windowsHide: true, timeout: 12_000, maxBuffer: 4_000_000,
    env: { ...process.env, GIT_OPTIONAL_LOCKS: '0', GIT_PAGER: 'cat', GIT_TERMINAL_PROMPT: '0' },
    encoding: 'utf8',
  });
  return stdout;
}

export async function changedFiles(cwd) {
  let root, raw;
  try {
    root = (await git(cwd, ['rev-parse', '--show-toplevel'])).trim();
    raw = await git(root, ['status', '--porcelain=v1', '-z', '--untracked-files=all']);
  } catch { return { root: cwd, files: [] }; }
  const tokens = raw.split('\0');
  const files = [];
  for (let i = 0; i < tokens.length && files.length < MAX_FILES; i++) {
    const record = tokens[i];
    if (!record || record.length < 4) continue;
    const status = record.slice(0, 2);
    const file = record.slice(3);
    if (/[RC]/.test(status)) i++; // porcelain -z includes the source path next
    files.push({ path: file, status, untracked: status === '??' });
  }
  return { root, files };
}

export async function fileDiff(cwd, requested) {
  const { root, files } = await changedFiles(cwd);
  const item = files.find(file => file.path === requested);
  if (!item) throw new Error('That file is no longer in the changes list');
  const absolute = path.resolve(root, requested);
  if (path.relative(root, absolute).startsWith('..')) throw new Error('File is outside the repository');
  if (item.untracked) {
    const stat = fs.statSync(absolute);
    if (!stat.isFile() || stat.size > MAX_DIFF) return { path: requested, diff: '', message: 'Preview unavailable for this file size or type.' };
    const bytes = fs.readFileSync(absolute);
    if (bytes.includes(0)) return { path: requested, diff: '', message: 'Binary file preview unavailable.' };
    const lines = bytes.toString('utf8').split(/\r?\n/);
    if (lines.at(-1) === '') lines.pop();
    return { path: requested, diff: `--- /dev/null\n+++ b/${requested}\n@@ -0,0 +1,${lines.length} @@\n${lines.map(line => `+${line}`).join('\n')}`, untracked: true };
  }
  const diff = await git(root, ['diff', 'HEAD', '--no-ext-diff', '--no-textconv', '--', requested]);
  return { path: requested, diff: diff.slice(0, MAX_DIFF), truncated: diff.length > MAX_DIFF };
}

function containedFile(cwd, name) {
  if (typeof name !== 'string' || !name.trim()) return null;
  const absolute = path.resolve(cwd, name);
  const relative = path.relative(cwd, absolute);
  return relative.startsWith('..') || path.isAbsolute(relative) ? null : absolute;
}

function textAt(file) {
  try {
    const stat = fs.statSync(file);
    if (!stat.isFile() || stat.size > MAX_DIFF) return null;
    const bytes = fs.readFileSync(file);
    return bytes.includes(0) ? null : bytes.toString('utf8');
  } catch (error) { return error.code === 'ENOENT' ? '' : null; }
}

/** Capture small text files before a file tool runs, including non-Git folders. */
export function captureToolFiles(name, args, cwd) {
  if (!['write_file', 'edit_file', 'edit_lines', 'apply_patch', 'move_file', 'delete_file'].includes(name)) return [];
  const names = [args?.path, args?.destination, args?.to];
  if (name === 'apply_patch' && typeof args?.patch === 'string') {
    for (const match of args.patch.matchAll(/^\+\+\+\s+(?:b\/)?([^\t\r\n]+)/gm)) if (match[1] !== '/dev/null') names.push(match[1]);
  }
  return [...new Set(names.map(value => containedFile(cwd, value)).filter(Boolean))].slice(0, 30)
    .map(file => ({ file, before: textAt(file) })).filter(item => item.before !== null);
}

export function completedFileDiffs(captured) {
  const output = [];
  for (const item of captured) {
    const after = textAt(item.file);
    if (after === null || after === item.before) continue;
    const data = diffText(item.before, after);
    if (!data.changed) continue;
    const lines = [`--- ${item.before ? `a/${path.basename(item.file)}` : '/dev/null'}`, `+++ ${after ? `b/${path.basename(item.file)}` : '/dev/null'}`];
    for (const hunk of toHunks(data, 3)) {
      lines.push(`@@ -${hunk.aStart},${hunk.aCount} +${hunk.bStart},${hunk.bCount} @@`);
      lines.push(...hunk.lines.map(line => `${line.type}${line.text}`));
    }
    output.push({ path: item.file, diff: lines.join('\n').slice(0, MAX_DIFF) });
  }
  return output;
}

function safeFile(cwd, name) {
  const absolute = path.resolve(cwd, name);
  const relative = path.relative(cwd, absolute);
  if (relative.startsWith('..') || path.isAbsolute(relative)) return null;
  try { return fs.statSync(absolute).isFile() ? absolute : null; }
  catch { return null; }
}

export function recentArtifacts(cwd, messages = []) {
  const found = new Map();
  for (const message of messages) {
    if (message.role !== 'tool' || message.isError || !message.result || /^(Error|Not run:|No change:|The user denied|Action cancelled)/i.test(message.result)) continue;
    if (['image_generate', 'image_download'].includes(message.name)) {
      try {
        const image = JSON.parse(message.result);
        if (['generated_image', 'downloaded_image'].includes(image.type) && typeof image.path === 'string') {
          const absolute = safeFile(cwd, image.path);
          if (absolute) found.set(absolute, { path: absolute, name: path.basename(absolute) });
        }
      } catch {}
      continue;
    }
    if (message.name === 'browser') {
      // Browser screenshot actions return a JSON receipt; surface the PNG so
      // the user can see the capture in the work review.
      try {
        const shot = JSON.parse(message.result);
        if (shot?.type === 'browser_screenshot' && typeof shot.path === 'string') {
          const absolute = safeFile(cwd, shot.path);
          if (absolute) found.set(absolute, { path: absolute, name: path.basename(absolute) });
        }
      } catch {}
      continue;
    }
    if (/^mcp__.+__browser_(take_)?screenshot/.test(message.name || '')) {
      // Raw browser MCP servers report captures as text (sometimes a bare
      // path, sometimes a markdown link). Surface any workspace image they
      // name so the capture is visible in the work review.
      try {
        for (const match of String(message.result || '').matchAll(/[\w\-./\\:]+?\.(png|jpe?g|webp)/gi)) {
          const absolute = safeFile(cwd, match[0]);
          if (absolute) found.set(absolute, { path: absolute, name: path.basename(absolute) });
        }
      } catch {}
      continue;
    }
    if (!['write_file', 'edit_file', 'edit_lines', 'move_file', 'apply_patch'].includes(message.name)) continue;
    const args = message.args && typeof message.args === 'object' ? message.args : {};
    const names = [args.path, args.destination, args.to];
    if (message.name === 'apply_patch') {
      for (const match of String(message.result).matchAll(/^(?:Create|Update|Move)\s+(.+?)(?:\s+\(|$)/gm)) names.push(match[1].split(' -> ').at(-1));
    }
    for (const name of names) {
      if (typeof name !== 'string') continue;
      const absolute = safeFile(cwd, name);
      if (absolute) found.set(absolute, { path: absolute, name: path.basename(absolute) });
    }
  }
  return [...found.values()].slice(-30).reverse();
}

export function jobList(agent) {
  return [...(agent?.state?.jobs?.values() || [])].map(job => ({
    ...jobInfo(job), output: job.out?.recent?.toString('utf8').slice(-12_000) || '',
  })).reverse();
}

export async function stopAgentJob(agent, id) {
  if (!agent) throw new Error('Open the teammate that started this job');
  const result = await stopJob({ job_id: String(id) }, { state: agent.state });
  if (result.startsWith('Error:')) throw new Error(result);
  return result;
}
