import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { loadSkills } from '../../src/core/skills.mjs';

test('palette includes installed skills, commands and jobs, with title-first fuzzy ranking', async () => {
  const { buildIndex, search, COMMANDS } = await import('../../src/palette/index.mjs');
  const skills = [{ name: 'reminder', description: 'Create a timed reminder' }, { name: 'research', description: 'Find facts', palette: [{ id: 'rem', title: 'Research reminders', keywords: ['reminder'] }] }];
  const jobs = [{ id: 'daily-reminder', name: 'Reminder daily', cronLabel: 'daily at 09:00', nextRunAt: '2026-09-30T09:00:00Z' }];
  const entries = buildIndex({ skills, jobs });
  assert.equal(entries.filter(entry => entry.source === 'skill').length, 3);
  assert.equal(entries.filter(entry => entry.source === 'command').length, COMMANDS.length);
  assert.equal(entries.filter(entry => entry.source === 'job').length, jobs.length);
  assert.equal(search(entries, 'rem')[0].title, 'reminder');
  assert.equal(search(entries, 'rmndr').length, 4, 'fuzzy titles plus matching command keywords');
  assert.ok(search(entries, 'zzzzzzz').length === 0);
});
test('skill manifest palette validates actions and refreshes when installed or modified', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'palette-skill-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const skill = path.join(directory, 'reminder'); fs.mkdirSync(skill);
  fs.writeFileSync(path.join(skill, 'SKILL.md'), '---\nname: reminder\ndescription: Create a timed reminder task\n---\nFollow the requested schedule.');
  assert.equal(loadSkills(directory)[0].palette?.length || 0, 0);
  const manifest = path.join(skill, 'plugin.json');
  fs.writeFileSync(manifest, JSON.stringify({ palette: [{ id: 'ten', title: 'Remind in ten minutes', hint: 'A one-shot reminder', keywords: ['alarm'] }] }));
  assert.equal(loadSkills(directory)[0].palette.length, 1);
  fs.writeFileSync(manifest, JSON.stringify({ palette: [{ id: '../bad', title: '' }] }));
  assert.equal(loadSkills(directory).length, 0, 'bad manifest rejected, not callable');
});
