import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { writeTextFile } from '../../tools/_shared.mjs';

const defaults = () => ({ version: 1, teammates: [
  { id: 'chief', name: 'Chief', color: '#b9a27c', emoji: '✦', persona: 'Coordinate the work. Be clear, decisive, and thoughtful.', projectId: null, model: null, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), lastMessage: '', lastMessageAt: null },
  { id: 'new-agent', name: 'New agent', color: '#8eb8ad', emoji: '◌', persona: '', projectId: null, model: null, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), lastMessage: '', lastMessageAt: null },
] });

function cleanName(value) {
  const name = String(value || '').trim();
  if (!name || name.length > 48) throw new Error('Teammate name must be 1–48 characters');
  return name;
}

function cleanColor(value) {
  const color = String(value || '#9aa6b2');
  if (!/^#[0-9a-fA-F]{6}$/.test(color)) throw new Error('Choose a six-digit color');
  return color;
}

export class TeammateStore {
  constructor(file) {
    this.file = file;
    this.data = defaults();
  }

  load() {
    try {
      const parsed = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      this.data = { version: 1, teammates: Array.isArray(parsed.teammates) ? parsed.teammates.filter(item => item && item.id) : [] };
    } catch (err) {
      this.data = defaults();
      if (err.code === 'ENOENT') this.save();
    }
    return this;
  }

  save() {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    writeTextFile(this.file, JSON.stringify(this.data, null, 2));
    return this;
  }

  list() { return [...this.data.teammates]; }

  find(id) { return this.data.teammates.find(item => item.id === id) || null; }

  create(input = {}) {
    this.load();
    const name = cleanName(input.name);
    const now = new Date().toISOString();
    const teammate = {
      id: `${name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 24) || 'teammate'}-${randomUUID().slice(0, 8)}`,
      name, color: cleanColor(input.color), emoji: String(input.emoji || '✦').slice(0, 4),
      persona: String(input.persona || '').slice(0, 4000), projectId: input.projectId || null,
      model: input.model || null, createdAt: now, updatedAt: now, lastMessage: '', lastMessageAt: null,
    };
    this.data.teammates.push(teammate);
    this.save();
    return teammate;
  }

  update(id, patch = {}) {
    this.load();
    const item = this.find(id);
    if (!item) throw new Error('Teammate not found');
    if (patch.name !== undefined) item.name = cleanName(patch.name);
    if (patch.color !== undefined) item.color = cleanColor(patch.color);
    if (patch.emoji !== undefined) item.emoji = String(patch.emoji).slice(0, 4);
    if (patch.persona !== undefined) item.persona = String(patch.persona).slice(0, 4000);
    if (patch.projectId !== undefined) item.projectId = patch.projectId || null;
    if (patch.model !== undefined) item.model = patch.model || null;
    item.updatedAt = new Date().toISOString();
    this.save();
    return item;
  }

  touch(id, message) {
    this.load();
    const item = this.find(id);
    if (!item) return null;
    item.lastMessage = String(message || '').replace(/\s+/g, ' ').trim().slice(0, 140);
    item.lastMessageAt = new Date().toISOString();
    item.updatedAt = item.lastMessageAt;
    this.save();
    return item;
  }

  delete(id) {
    this.load();
    const before = this.data.teammates.length;
    this.data.teammates = this.data.teammates.filter(item => item.id !== id);
    if (this.data.teammates.length === before) return false;
    this.save();
    return true;
  }
}
