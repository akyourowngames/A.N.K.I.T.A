import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { CONFIG_DIR } from '../core/config.mjs';
import { loadSkills, parseSkillFile, reloadSkills, SKILL_NAME_RE, skillsDir } from '../core/skills.mjs';
import { registerSkillRoot, registeredSkillRoots, SKILL_ROOTS_FILE } from './roots.mjs';
import { SKILL_FILE, SKILL_OUTPUT_BYTES } from './layout.mjs';

const SEARCH_ENDPOINT = 'https://skills.sh/api/search'; // Public catalogue used by the open skills CLI.
const GITHUB_API = 'https://api.github.com'; // Fixed public API origin; user input cannot choose hosts.
const GITHUB_RAW = 'https://raw.githubusercontent.com'; // Immutable commit-addressed instruction downloads.
const GITHUB_HOST = 'github.com'; // Accepted HTTPS source-link host.
const INVALID_SOURCE = 'Invalid skill source: use a public GitHub owner/repo'; // Shared source-validation failure.
const REQUEST_TIMEOUT_MS = 15000; // Milliseconds per request including streamed response reading.
const RESPONSE_MAX_BYTES = 1024 * 1024; // Bytes per catalogue/tree/download; reject larger sources explicitly.
const SEARCH_LIMIT = 12; // Candidate count per search to bound model context.
const QUERY_MAX_CHARS = 200; // Characters per user search/ref; avoids unbounded service input.
const SOURCE_RE = /^[a-z0-9][a-z0-9-]*\/[a-z0-9][a-z0-9._-]*$/i; // Public GitHub owner/repository shorthand.
const COMMIT_RE = /^[a-f0-9]{40}$/; // Full Git SHA-1 commits, never mutable refs during installation.
const HASH_RE = /^[a-f0-9]{64}$/; // SHA-256 digest of the exact UTF-8 instruction file.
const REGULAR_MODES = new Set(['100644', '100755']); // Git tree regular-file modes; links/submodules are rejected.
const ANCILLARY_FILE_RE = /^(?:readme|license|copying|notice)(?:[.-][a-z0-9.-]+)?$/i; // Human/legal metadata allowed beside a self-contained entrypoint.
const DEFAULT_GIT_REF = 'HEAD'; // Preview follows the repository's current default; install always requires a full commit.
const SUPPORT_FILE_RE = /(?:^|\/)(?:scripts|references|assets)\/|\]\((?!https?:|#|mailto:)[^)]+\)/i; // Dependencies unavailable to a single-file import.
const RELATIVE_RESOURCE_RE = /(?:^|[\s`'"(>])\.{1,2}[\\/]|^\s*\[[^\]]+\]:\s*<?(?!https?:|#|mailto:)\S+|\b(?:href|src)\s*=\s*["'](?!https?:|#|mailto:)[^"']+/im; // Plain/code parent paths, reference-style Markdown and HTML resources.
const PROVENANCE_FILE = 'source.json'; // Audit receipt beside imported instructions, never executed.
const JSON_INDENT = 2; // Spaces in human-readable import receipts.
export const INSTALLED_SKILLS_DIR = path.join(CONFIG_DIR, 'skills'); // Profile-local skills survive packaged-app upgrades.
export const SKILL_MANAGER_TOOL = 'skill_manage'; // Shared discovery and interactive-only execution identifier.
export const SKILL_MANAGER_CATEGORY = 'skill-manager'; // Deferred family, distinct from the always-on instruction reader.
export const SKILL_MANAGER_USAGE = 'ankita skills list | search <query> | preview <owner/repo> <name> [--ref ref] [--path file] | install <owner/repo> <name> --commit sha --path file --sha256 hash';

function sourceName(input) {
  let source = String(input ?? '');
  if (source.startsWith('https://')) {
    const url = new URL(source);
    if (url.hostname !== GITHUB_HOST || url.port || url.username || url.password || url.search || url.hash) throw new Error(INVALID_SOURCE);
    source = url.pathname.replace(/^\//, '').replace(/\/$/, '');
  }
  if (!SOURCE_RE.test(source) || source.includes('..')) throw new Error(INVALID_SOURCE);
  return source;
}

function checkedPath(value) {
  if (typeof value !== 'string' || !value || value.includes('\\') || value.startsWith('/') || value.split('/').some(part => !part || part === '.' || part === '..') || path.posix.basename(value) !== SKILL_FILE) throw new Error('Invalid skill path');
  return value;
}

const digest = text => createHash('sha256').update(text).digest('hex');
const encodePath = text => text.split('/').map(encodeURIComponent).join('/');

export class SkillManager {
  constructor({ root = INSTALLED_SKILLS_DIR, rootsFile = SKILL_ROOTS_FILE, fetchImpl = globalThis.fetch, signal } = {}) {
    this.root = path.resolve(root);
    this.rootsFile = rootsFile;
    this.fetch = fetchImpl;
    this.signal = signal;
  }

  async request(url, { json = true } = {}) {
    const timeout = AbortSignal.timeout(REQUEST_TIMEOUT_MS);
    const signal = this.signal ? AbortSignal.any([timeout, this.signal]) : timeout;
    const response = await this.fetch(url, { redirect: 'error', signal, headers: { Accept: 'application/json' } });
    if (!response.ok) { await response.body?.cancel(); throw new Error(`Skill service HTTP ${response.status}; retry later or check the public repository`); }
    if (Number(response.headers.get('content-length')) > RESPONSE_MAX_BYTES) { await response.body?.cancel(); throw new Error('Skill response exceeds download limit'); }
    const reader = response.body?.getReader();
    if (!reader) throw new Error('Invalid skill service response');
    const chunks = [];
    let size = 0;
    try {
      while (true) {
        signal.throwIfAborted();
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > RESPONSE_MAX_BYTES) throw new Error('Skill response exceeds download limit');
        chunks.push(Buffer.from(value));
      }
    } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
    const text = new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks));
    return json ? JSON.parse(text) : text;
  }

  list() {
    const roots = [...new Set([skillsDir(), ...registeredSkillRoots(this.rootsFile), this.root])];
    const skills = new Map();
    for (const root of roots) for (const skill of loadSkills(root)) if (!skills.has(skill.name)) skills.set(skill.name, { name: skill.name, description: skill.description, path: skill.path });
    return [...skills.values()].sort((a, b) => a.name.localeCompare(b.name));
  }

  async search(query) {
    if (typeof query !== 'string' || !query.trim() || query.length > QUERY_MAX_CHARS) throw new Error(`Search query must contain 1–${QUERY_MAX_CHARS} characters`);
    const url = new URL(SEARCH_ENDPOINT);
    url.searchParams.set('q', query.trim());
    const response = await this.request(url);
    if (!Array.isArray(response?.skills)) throw new Error('Invalid skills search response');
    const results = [];
    for (const item of response.skills) {
      if (!item || typeof item.name !== 'string' || !SKILL_NAME_RE.test(item.name)) continue;
      try {
        const source = sourceName(item.source);
        results.push({ name: item.name, source, installs: Number.isSafeInteger(item.installs) && item.installs >= 0 ? item.installs : null });
      } catch { /* Malformed service entries cannot become install selectors. */ }
      if (results.length === SEARCH_LIMIT) break;
    }
    return results;
  }

  async preview({ source: rawSource, name, ref = DEFAULT_GIT_REF, path: requestedPath } = {}) {
    const source = sourceName(rawSource);
    if (typeof name !== 'string' || !SKILL_NAME_RE.test(name)) throw new Error('Invalid skill name');
    if (requestedPath !== undefined) checkedPath(requestedPath);
    if (typeof ref !== 'string' || !ref.trim() || ref.length > QUERY_MAX_CHARS || /[\r\n\0]/.test(ref)) throw new Error('Invalid Git ref');
    const resolved = await this.request(`${GITHUB_API}/repos/${source}/commits/${encodeURIComponent(ref)}`);
    if (!COMMIT_RE.test(resolved?.sha)) throw new Error('Invalid resolved GitHub commit');
    const commit = resolved.sha;
    const listing = await this.request(`${GITHUB_API}/repos/${source}/git/trees/${commit}?recursive=1`);
    if (listing?.truncated) throw new Error('Repository tree is truncated; use a smaller skill repository');
    if (!Array.isArray(listing?.tree)) throw new Error('Invalid GitHub tree response');
    const candidates = listing.tree.filter(item => requestedPath ? item.path === requestedPath : item.path === SKILL_FILE || item.path?.endsWith(`/${name}/${SKILL_FILE}`));
    if (candidates.length !== 1) throw new Error('Skill path missing or ambiguous; provide the exact path from GitHub');
    const entry = candidates[0];
    const file = checkedPath(entry.path);
    // Reject link ancestors as well as the selected file.
    if (entry.type !== 'blob' || !REGULAR_MODES.has(entry.mode) || listing.tree.some(item => file.startsWith(`${item.path}/`) && item.mode === '120000')) throw new Error('Skill uses a link or is not a regular instruction file');
    const parent = path.posix.dirname(file);
    const prefix = parent === '.' ? '' : `${parent}/`;
    if (listing.tree.some(item => {
      if (!item.path?.startsWith(prefix) || item.path === file) return false;
      const sibling = item.path.slice(prefix.length);
      return sibling.includes('/') || item.type !== 'blob' || !REGULAR_MODES.has(item.mode) || !ANCILLARY_FILE_RE.test(sibling);
    })) throw new Error('Skill needs support files; this importer accepts self-contained instructions only');
    const content = await this.request(`${GITHUB_RAW}/${source}/${commit}/${encodePath(file)}`, { json: false });
    const parsed = parseSkillFile(content, name);
    if (parsed.error) throw new Error(`Skill is not compatible with ANKITA: ${parsed.error}`);
    if (Buffer.byteLength(parsed.body) > SKILL_OUTPUT_BYTES) throw new Error(`Skill body exceeds the ${SKILL_OUTPUT_BYTES}-byte instruction read limit`);
    if (SUPPORT_FILE_RE.test(parsed.body) || RELATIVE_RESOURCE_RE.test(parsed.body)) throw new Error('Skill needs a relative support file; use a self-contained skill');
    // Ancillary files may be omitted only when the instructions never refer to them.
    if (listing.tree.some(item => item.path?.startsWith(prefix) && item.path !== file &&
      parsed.body.toLowerCase().includes(path.posix.basename(item.path).toLowerCase()))) throw new Error('Skill refers to an omitted support file; use a self-contained skill');
    return { source, name, commit, path: file, sha256: digest(content), description: parsed.description, content };
  }

  async install(selection = {}) {
    if (!COMMIT_RE.test(selection.commit)) throw new Error('Install needs the full commit from preview');
    if (!HASH_RE.test(selection.sha256)) throw new Error('Install needs the SHA-256 hash from preview');
    checkedPath(selection.path);
    const preview = await this.preview({ ...selection, ref: selection.commit });
    if (preview.commit !== selection.commit || preview.sha256 !== selection.sha256) throw new Error('Skill content changed or hash does not match the preview');
    if (this.list().some(skill => skill.name === preview.name)) throw new Error(`Skill already installed or bundled: ${preview.name}`);
    this.signal?.throwIfAborted();
    fs.mkdirSync(this.root, { recursive: true });
    const canonical = fs.realpathSync(this.root);
    if (fs.lstatSync(this.root).isSymbolicLink()) throw new Error('Install root must not be a link');
    const directory = path.join(canonical, preview.name);
    fs.mkdirSync(directory); // Exclusive creation: never replace a skill, link or concurrent install.
    try {
      fs.writeFileSync(path.join(directory, SKILL_FILE), preview.content, { flag: 'wx' });
      const { content, ...provenance } = preview;
      fs.writeFileSync(path.join(directory, PROVENANCE_FILE), JSON.stringify(provenance, null, JSON_INDENT) + '\n', { flag: 'wx' });
      registerSkillRoot(canonical, this.rootsFile);
      reloadSkills();
      return { ...provenance, directory };
    } catch (error) {
      // Only roll back the exclusively-created folder whose resolved parent we checked.
      if (path.dirname(directory) === canonical && fs.realpathSync(directory) === directory) fs.rmSync(directory, { recursive: true, force: true });
      throw error;
    }
  }
}
