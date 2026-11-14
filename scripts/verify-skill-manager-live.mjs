import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

// Public upstream smoke-test fixture; no personal profile or account writes.
const SOURCE = 'anthropics/skills';
const NAME = 'brand-guidelines';
const EXPECTED_HEADING = /Anthropic Brand Styling/i; // Known public fixture; imported only into a disposable profile.
const CLI_TIMEOUT_MS = 20000; // Milliseconds for provider-free child CLI discovery.
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-skill-live-'));
process.env.CONFIG_DIR = directory;
try {
  const { SkillManager } = await import('../src/skills/manager.mjs');
  const { loadSkills } = await import('../src/core/skills.mjs');
  const { run } = await import('../tools/skills/skill.mjs');
  const { DesktopEngine } = await import('../desktop/electron/engine.mjs');
  const manager = new SkillManager();
  const found = await manager.search('mobile');
  assert.ok(found.length, 'live catalogue returns candidates');
  const preview = await manager.preview({ source: SOURCE, name: NAME });
  const installed = await manager.install(preview);
  assert.ok(loadSkills().some(skill => skill.name === NAME));
  assert.match(run({ name: NAME }), EXPECTED_HEADING);
  assert.ok(run({ name: NAME }).includes(loadSkills().find(skill => skill.name === NAME).body), 'complete instructions survive import and manual reading');
  const desktop = DesktopEngine.prototype.listSkills.call({ desktopSettings: { data: {} } });
  assert.ok(desktop.some(skill => skill.name === NAME));
  const cli = JSON.parse(execFileSync(process.execPath, ['chat.mjs', 'skills', 'list'], { encoding: 'utf8', timeout: CLI_TIMEOUT_MS, env: process.env }));
  assert.ok(cli.some(skill => skill.name === NAME), 'installed root survives process restart');
  console.log(JSON.stringify({ searchCandidates: found.length, installed: NAME, source: SOURCE, commit: installed.commit, sha256: installed.sha256, chat: true, desktop: true, restartedCli: true, profile: 'temporary' }));
} finally {
  // Only remove the absolute directory created above, inside the runtime temp root.
  const relative = path.relative(fs.realpathSync(os.tmpdir()), fs.realpathSync(directory));
  assert.ok(relative && !relative.startsWith('..') && !path.isAbsolute(relative));
  fs.rmSync(directory, { recursive: true, force: true });
}
