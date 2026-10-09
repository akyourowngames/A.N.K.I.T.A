import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DesktopEngine } from '../../desktop/electron/engine.mjs';

test('desktop file selection is unavailable to remote and background turns', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'desktop-upload-'));
  let selections = 0;
  const engine = new DesktopEngine({
    teammateFile: path.join(directory, 'teammates.json'), projectsFile: path.join(directory, 'projects.json'), settingsFile: path.join(directory, 'settings.json'),
    channelsFile: path.join(directory, 'channels.json'), sessionsDir: directory, browserFile: path.join(directory, 'browser.json'), credentialFile: path.join(directory, 'credentials.json'),
    config: { provider: 'test', tools: false, agentName: 'Ankita', username: 'User' },
    bootstrap: async () => ({ client: {}, tool: null, models: [], model: '', provider: { name: 'test' } }),
    mcp: { reconcile: async () => {}, ensureComposio: async () => {}, closeAll: async () => {}, summaries: () => [], connectedIds: [] },
    selectBrowserUpload: async () => { selections++; return path.join(directory, 'selected.txt'); },
  });
  t.after(async () => { await engine.close(); fs.rmSync(directory, { recursive: true, force: true }); });
  await engine.init();
  const agent = engine.agentFor(engine.listTeammates()[0].id);
  assert.equal(typeof agent.toolContext.selectBrowserUpload, 'function');
  await assert.rejects(agent.toolContext.selectBrowserUpload({}), /desktop/);
  assert.equal(selections, 0);
  agent.browserCredentialAllowed = true;
  assert.equal(await agent.toolContext.selectBrowserUpload({}), path.join(directory, 'selected.txt'));
  assert.equal(selections, 1);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(agent.toolContext.selectBrowserUpload({ signal: controller.signal }), /abort/i);
  assert.equal(selections, 1);
});
