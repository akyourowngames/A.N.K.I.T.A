import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { validatePalette } from '../palette/index.mjs';
import { startupProfile } from './startup-profile.mjs';
import { SKILL_FILE, MANIFEST_FILE } from '../skills/layout.mjs';
import { registeredSkillRoots } from '../skills/roots.mjs';
import { parseToolName } from '../integrations/mcp-manager.mjs';

const TOOL_METADATA_CHARS = 200; // Characters per tool-hint/activation field; bounds catalog metadata.
const PERMISSION_CHARS = 200; // Characters per permission manifest field; keeps install prompts readable.
const TOOL_NAME_RE = /^[a-z][a-z0-9_-]*$/; // Native tool identifiers, never page text or query matching.
const PERMISSION_SCOPE_RE = /^[a-z][a-z0-9_.-]*$/; // Permission scopes (files, network, shell, browser); validated tokens.
const AUTO_SKILL_PROMPT_CHARS = 6000; // Total characters of automatic instruction blocks per turn; load whole bodies only.

export const SKILL_NAME_RE = /^[a-z0-9-]{1,64}$/;

const cache = new Map(); // One entry per root so discovering custom folders preserves warm bundled parses.

export function skillsDir() {
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'skills');
}

export function parseSkillFile(text, dirName) {
  const diskLines = String(text).replace(/^\uFEFF/, '').split('\n');
  const lines = diskLines.map(line => line.replace(/\r$/, ''));
  if (lines[0] !== '---') return { error: 'missing frontmatter' };
  const end = lines.indexOf('---', 1);
  if (end < 0) return { error: 'unterminated frontmatter' };

  const fields = {};
  let lastKey = null;
  for (const line of lines.slice(1, end)) {
    const pair = /^([a-z-]+):\s*(.*)$/.exec(line);
    if (pair) {
      fields[pair[1]] = pair[2].trim();
      lastKey = pair[1];
    } else if (/^\s+\S/.test(line) && lastKey === 'description') {
      fields.description += ` ${line.trim()}`;
    } else if (line.trim()) {
      return { error: 'invalid frontmatter line' };
    }
  }

  const name = fields.name || '';
  const description = (fields.description || '').replace(/\s+/g, ' ').trim();
  const suggestedTools = fields['suggested-tools'] || '';
  const automatic = fields['auto-tools'] || '';
  const autoTools = [...new Set(automatic.split(',').map(tool => tool.trim()).filter(Boolean))];
  // Permission manifest (v1: parse + validate, enforcement opt-in).
  // Declares what the skill touches: files, network, shell, browser.
  const allowedToolsRaw = fields['allowed-tools'] || '';
  const allowedTools = [...new Set(allowedToolsRaw.split(',').map(tool => tool.trim()).filter(Boolean))];
  const touchesRaw = fields.touches || '';
  const touches = [...new Set(touchesRaw.split(',').map(scope => scope.trim().toLowerCase()).filter(Boolean))];
  const rawBody = diskLines.slice(end + 1).join('\n');
  const body = lines.slice(end + 1).join('\n').trim();
  if (!SKILL_NAME_RE.test(name) || name !== dirName) return { error: 'invalid or mismatched name' };
  if (description.length < 10 || description.length > 300) return { error: 'description must be 10–300 characters' };
  if (suggestedTools.length > TOOL_METADATA_CHARS) return { error: `suggested-tools exceeds ${TOOL_METADATA_CHARS} characters` };
  if (automatic.length > TOOL_METADATA_CHARS || autoTools.some(tool => !TOOL_NAME_RE.test(tool))) return { error: `auto-tools must be comma-separated tool names within ${TOOL_METADATA_CHARS} characters` };
  if (allowedToolsRaw.length > PERMISSION_CHARS || allowedTools.some(tool => !TOOL_NAME_RE.test(tool))) return { error: `allowed-tools must be comma-separated tool names within ${PERMISSION_CHARS} characters` };
  if (touchesRaw.length > PERMISSION_CHARS || touches.some(scope => !PERMISSION_SCOPE_RE.test(scope))) return { error: `touches must be comma-separated scopes within ${PERMISSION_CHARS} characters` };
  if (!body || rawBody.length > 12000) return { error: 'body must be 1–12000 characters on disk' };
  return { name, description, suggestedTools, autoTools, allowedTools, touches, body };
}

export function reloadSkills() {
  cache.clear();
}

export function loadSkills(dir) {
  if (dir === undefined) {
    let installed = [];
    try { installed = registeredSkillRoots(); }
    catch (error) { console.error(`Skipping custom skill roots: ${error.message}`); }
    const catalog = new Map();
    // Bundled skills win name collisions; the first registered custom root wins thereafter.
    for (const root of new Set([skillsDir(), ...installed])) {
      for (const skill of loadSkills(root)) if (!catalog.has(skill.name)) catalog.set(skill.name, skill);
    }
    return [...catalog.values()].sort((left, right) => left.name.localeCompare(right.name));
  }
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true })
      .filter(entry => entry.isDirectory())
      .sort((a, b) => a.name.localeCompare(b.name));
  } catch {
    return [];
  }

  const files = entries.map(entry => {
    const file = path.join(dir, entry.name, SKILL_FILE);
    const manifest = path.join(dir, entry.name, MANIFEST_FILE);
    let manifestStamp = 'missing';
    try { const stat = fs.statSync(manifest); manifestStamp = `${stat.mtimeMs}:${stat.ctimeMs}:${stat.size}`; } catch {}
    try {
      const stat = fs.statSync(file);
      return { name: entry.name, file, manifest, stamp: stat.isFile() ? `${stat.mtimeMs}:${stat.ctimeMs}:${stat.size}:${manifestStamp}` : 'missing' };
    } catch {
      return { name: entry.name, file, stamp: 'missing' };
    }
  });
  const root = path.resolve(dir);
  const key = JSON.stringify(files.map(({ name, stamp }) => [name, stamp]));
  const previous = cache.get(root);
  if (previous?.key === key) return previous.skills;

  const skills = [];
  for (const { name, file, manifest, stamp } of files) {
    if (stamp === 'missing') continue;
    const started = startupProfile.now();
    let status = 'error';
    try {
      const parsed = parseSkillFile(fs.readFileSync(file, 'utf8'), name);
      if (parsed.error) {
        console.error(`Skipping skill ${name}: ${parsed.error}`);
        continue;
      }
      let palette = [];
      if (fs.existsSync(manifest)) palette = validatePalette(JSON.parse(fs.readFileSync(manifest, 'utf8')).palette);
      skills.push({ ...parsed, palette, path: file });
      status = 'ready';
    } catch (error) {
      console.error(`Skipping skill ${name}: ${error.message}`);
    } finally { startupProfile.finish('skill', name, started, status); }
  }
  cache.set(root, { key, skills });
  return skills;
}

const automaticBlock = skill => `Automatically loaded skill: ${skill.name}\n${skill.body}`;

export function permissionSummary(skill) {
  const parts = [];
  if (Array.isArray(skill.allowedTools) && skill.allowedTools.length) parts.push(`allowed-tools: ${skill.allowedTools.join(', ')}`);
  if (Array.isArray(skill.touches) && skill.touches.length) parts.push(`touches: ${skill.touches.join(', ')}`);
  return parts.join('; ');
}

export function activeAutomaticSkills(skills, activatedTools = []) {
  // Match advertised MCP tool names independently of the user's chosen server id.
  const tools = new Set([...activatedTools].flatMap(name => [name, parseToolName(name)?.toolName].filter(Boolean)));
  let remaining = AUTO_SKILL_PROMPT_CHARS;
  return skills.filter(skill => {
    if (!skill.autoTools?.some(tool => tools.has(tool))) return false;
    const chars = automaticBlock(skill).length;
    if (chars > remaining) return false;
    remaining -= chars;
    return true;
  });
}

export function skillPromptLines(skills, activatedTools = []) {
  if (!skills.length) return [];
  const active = activeAutomaticSkills(skills, activatedTools);
  const loaded = new Set(active.map(skill => skill.name));
  return [
    'Available skills (interactive chats, progressive disclosure):',
    ...skills.map(skill => {
      const hint = skill.suggestedTools ? ` Suggested tools: ${skill.suggestedTools}.` : '';
      const perms = permissionSummary(skill) ? ` Permissions: ${permissionSummary(skill)}.` : '';
      const trigger = skill.autoTools?.length ? `Loads automatically when ${skill.autoTools.join(', ')} is discovered or used. ` : '';
      const instructions = loaded.has(skill.name) ? 'Instructions already loaded below for this turn.' : `${trigger}To read manually, call skill({"name":"${skill.name}"}).`;
      return `  - ${skill.name}: ${skill.description}${hint}${perms} ${instructions}`;
    }),
    'Skills are instructions only. Suggested tools are hints, not requirements. When allowed-tools is present, prefer those tools and ask before using others. Use find_tools to load tools if needed.',
    ...active.map(automaticBlock),
  ];
}
