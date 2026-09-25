import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

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
  const rawBody = diskLines.slice(end + 1).join('\n');
  const body = lines.slice(end + 1).join('\n').trim();
  if (!SKILL_NAME_RE.test(name) || name !== dirName) return { error: 'invalid or mismatched name' };
  if (description.length < 10 || description.length > 300) return { error: 'description must be 10–300 characters' };
  if (suggestedTools.length > 200) return { error: 'suggested-tools exceeds 200 characters' };
  if (!body || rawBody.length > 12000) return { error: 'body must be 1–12000 characters on disk' };
  return { name, description, suggestedTools, body };
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
    const file = path.join(dir, entry.name, 'SKILL.md');
    try {
      const stat = fs.statSync(file);
      return { name: entry.name, file, stamp: stat.isFile() ? `${stat.mtimeMs}:${stat.ctimeMs}:${stat.size}` : 'missing' };
    } catch {
      return { name: entry.name, file, stamp: 'missing' };
    }
  });
  const key = JSON.stringify([path.resolve(dir), files.map(({ name, stamp }) => [name, stamp])]);
  if (cache?.key === key) return cache.skills;

  const skills = [];
  for (const { name, file, stamp } of files) {
    if (stamp === 'missing') continue;
    try {
      const parsed = parseSkillFile(fs.readFileSync(file, 'utf8'), name);
      if (parsed.error) {
        console.error(`Skipping skill ${name}: ${parsed.error}`);
        continue;
      }
      skills.push({ ...parsed, path: file });
    } catch (error) {
      console.error(`Skipping skill ${name}: ${error.message}`);
    }
  }
  cache = { key, skills };
  return skills;
}

export function skillPromptLines(skills) {
  if (!skills.length) return [];
  return [
    'Available skills (interactive chats, progressive disclosure):',
    ...skills.map(skill =>
      `  - ${skill.name}: ${skill.description}${skill.suggestedTools ? ` Suggested tools: ${skill.suggestedTools}.` : ''} To use, call skill({"name":"${skill.name}"}).`),
    'Skills are instructions only. Suggested tools are hints, not requirements. Use find_tools to load tools if needed.',
  ];
}
