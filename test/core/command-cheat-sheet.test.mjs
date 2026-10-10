import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { FLAGS, SLASH_GROUPS, LOCAL_COMMANDS } from '../../src/core/commands.mjs';
import { COMMANDS } from '../../src/palette/index.mjs';

const url = new URL('../../src/core/cheat-sheet.mjs', import.meta.url);
async function api() { assert.ok(fs.existsSync(url), 'generated command cheat sheet exists'); return import(url.href); }

test('sheet includes every terminal flag, command and real palette action without inventing parity', async () => {
  const { commandCheatSheet } = await api();
  const sheet = commandCheatSheet({ skills: [] });
  for (const group of SLASH_GROUPS) for (const item of group.items) assert.ok(sheet.includes(item.name), item.name);
  for (const flag of FLAGS) assert.ok(sheet.includes(flag.long), flag.long);
  for (const item of LOCAL_COMMANDS) assert.ok(sheet.includes(item.name), item.name);
  for (const item of COMMANDS) assert.ok(sheet.includes(item.title), item.title);
  assert.match(sheet, /Terminal only/);
  assert.match(sheet, /Ctrl\+K/);
});

test('sheet searches skills and escapes table syntax from contributed descriptions', async () => {
  const { commandCheatSheet } = await api();
  const skill = { name: 'sample', description: 'Explain | rows\nclearly', palette: [{ id: 'row', title: 'Explain rows', keywords: ['tabular'] }] };
  const sheet = commandCheatSheet({ query: 'tabular', skills: [skill] });
  assert.match(sheet, /Explain rows/);
  assert.doesNotMatch(sheet, /--api-key/);
  assert.match(commandCheatSheet({ skills: [skill] }), /Explain \\?\| rows clearly/);
  assert.match(commandCheatSheet({ query: 'missing-query', skills: [] }), /No matching commands/);
});

test('real CLI generates the searchable sheet without provider login', async t => {
  await api();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'offline-cheat-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const output = execFileSync(process.execPath, ['chat.mjs', 'commands', 'skills'], { encoding: 'utf8', timeout: 10000, env: { ...process.env, CONFIG_DIR: root, PROVIDER: 'invalid-offline-provider' } });
  assert.match(output, /Plugins and skills/);
});
