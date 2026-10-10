import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { validatePalette } from '../palette/index.mjs';
import { startupProfile } from './startup-profile.mjs';
import { SKILL_FILE, MANIFEST_FILE } from '../skills/layout.mjs';

const TOOL_METADATA_CHARS = 200; // Characters per tool-hint/activation field; bounds catalog metadata.
const TOOL_NAME_RE = /^[a-z][a-z0-9_-]*$/; // Native tool identifiers, never page text or query matching.
const AUTO_SKILL_PROMPT_CHARS = 6000; // Total characters of automatic instruction blocks per turn; load whole bodies only.

export const SKILL_NAME_RE = /^[a-z0-9-]{1,64}$/;

let cache = null;

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
  const rawBody = diskLines.slice(end + 1).join('\n');
  const body = lines.slice(end + 1).join('\n').trim();
  if (!SKILL_NAME_RE.test(name) || name !== dirName) return { error: 'invalid or mismatched name' };
  if (description.length < 10 || description.length > 300) return { error: 'description must be 10–300 characters' };
  if (suggestedTools.length > TOOL_METADATA_CHARS) return { error: `suggested-tools exceeds ${TOOL_METADATA_CHARS} characters` };
  if (automatic.length > TOOL_METADATA_CHARS || autoTools.some(tool => !TOOL_NAME_RE.test(tool))) return { error: `auto-tools must be comma-separated tool names within ${TOOL_METADATA_CHARS} characters` };
  if (!body || rawBody.length > 12000) return { error: 'body must be 1–12000 characters on disk' };
  return { name, description, suggestedTools, autoTools, body };
}

export function reloadSkills() {
  cache = null;
}

export function loadSkills(dir = skillsDir()) {
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
  const key = JSON.stringify([path.resolve(dir), files.map(({ name, stamp }) => [name, stamp])]);
  if (cache?.key === key) return cache.skills;

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
  cache = { key, skills };
  return skills;
}

const automaticBlock = skill => `Automatically loaded skill: ${skill.name}\n${skill.body}`;

export function activeAutomaticSkills(skills, activatedTools = []) {
  const tools = new Set(activatedTools);
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
      const trigger = skill.autoTools?.length ? `Loads automatically when ${skill.autoTools.join(', ')} is discovered or used. ` : '';
      const instructions = loaded.has(skill.name) ? 'Instructions already loaded below for this turn.' : `${trigger}To read manually, call skill({"name":"${skill.name}"}).`;
      return `  - ${skill.name}: ${skill.description}${hint} ${instructions}`;
    }),
    'Skills are instructions only. Suggested tools are hints, not requirements. Use find_tools to load tools if needed.',
    ...active.map(automaticBlock),
  ];
}
