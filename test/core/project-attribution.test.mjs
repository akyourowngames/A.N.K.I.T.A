import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-attribution-'));
process.env.CONFIG_DIR = sandbox;
test.after(() => fs.rmSync(sandbox, { recursive: true, force: true }));

const { Agent } = await import('../../src/core/agent.mjs');
const { ProjectStore } = await import('../../src/memory/projects.mjs');
const { noteFileEffects } = await import('../../src/memory/turn-audit.mjs');
const { PROJECT_WORK_GUIDANCE, UNTRACKED_REPO_GUIDANCE } = await import('../../src/memory/project-guidance.mjs');

const config = { tools: false, memoryConsolidation: true, projectAutoDetect: true, contextWindow: 32768, historyMessages: 20 };

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-attribution-work-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const repo = path.join(root, 'repo');
  const nested = path.join(repo, 'src');
  fs.mkdirSync(path.join(repo, '.git'), { recursive: true });
  fs.mkdirSync(nested);
  const projectsFile = path.join(root, 'projects.json');
  const store = new ProjectStore(projectsFile).load();
  const project = store.add({ name: 'Atlas', path: repo });
  return { root, repo, nested, projectsFile, store, project };
}

test('the working directory attaches its project without changing the saved active project', (t) => {
  const f = fixture(t);
  const agent = new Agent({ client: {}, config, workspacePath: f.nested, toolContext: { projectsFile: f.projectsFile }, skillsEnabled: false });
  assert.equal(agent.projectId, f.project.id);
  assert.equal(agent.projectSource, 'path');
  assert.match(agent.project, /Atlas/);
  assert.ok(agent.state.activatedTools.has('project_memory'), 'the project write tool is directly callable');
  assert.equal(new ProjectStore(f.projectsFile).load().activeId, null, 'detection is session-scoped');
});

test('an explicit project always wins over the folder', (t) => {
  const f = fixture(t);
  const other = f.store.add({ name: 'Other' });
  const agent = new Agent({ client: {}, config, workspacePath: f.nested, project: 'Project: Other', projectId: other.id,
    toolContext: { projectsFile: f.projectsFile }, skillsEnabled: false });
  assert.equal(agent.projectSource, 'explicit');
  assert.equal(agent.projectId, other.id);
});

test('the desktop opt-out keeps an unassigned workspace unattributed', (t) => {
  const f = fixture(t);
  const agent = new Agent({ client: {}, config, autoProject: false, workspacePath: f.nested, toolContext: { projectsFile: f.projectsFile }, skillsEnabled: false });
  assert.equal(agent.projectId, null);
  assert.equal(agent.projectSource, 'none');
  assert.equal(agent.project, '');
  assert.equal(agent.messages[0].content.includes(PROJECT_WORK_GUIDANCE), false);
});

test('an attached project tells the model that work is logged, without loosening the stop rule', (t) => {
  const f = fixture(t);
  const agent = new Agent({ client: {}, config, workspacePath: f.nested, toolContext: { projectsFile: f.projectsFile }, skillsEnabled: false });
  assert.ok(agent.messages[0].content.includes(PROJECT_WORK_GUIDANCE));
  assert.match(agent.messages[0].content, /summarise and stop still applies/);
});

test('an untracked git folder gets one suggestion and is never attached silently', (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-attribution-hint-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, '.git'));
  const projectsFile = path.join(root, 'projects.json');
  new ProjectStore(projectsFile).load();
  const agent = new Agent({ client: {}, config, workspacePath: root, toolContext: { projectsFile }, skillsEnabled: false });
  assert.equal(agent.projectId, null);
  assert.ok(agent.messages[0].content.includes(UNTRACKED_REPO_GUIDANCE));
  assert.equal(agent.messages[0].content.includes(PROJECT_WORK_GUIDANCE), false);
});

test('work capture off keeps the journal a plain transcript', async (t) => {
  const f = fixture(t);
  let journaled = null;
  const completions = [];
  const agent = new Agent({ client: {}, config: { ...config, projectWorkCapture: false }, workspacePath: f.nested,
    toolContext: { projectsFile: f.projectsFile }, skillsEnabled: false,
    journal: turn => { journaled = turn; return null; },
    onTurnComplete: async info => completions.push(info) });
  agent.streamTurn = async () => {
    noteFileEffects(agent.turnAudit, 'write_file', { path: 'src/a.js' }, agent.cwd);
    return { content: 'Done.', toolCalls: [] };
  };
  await agent.sendRequest('edit the file');
  assert.equal(journaled.projectId, f.project.id);
  assert.equal(journaled.audit, null);
  assert.equal(completions.length, 1);
  assert.equal(completions[0].audit, null);
});

test('a journaled turn carries the audited paths and fires project maintenance once', async (t) => {
  const f = fixture(t);
  let journaled = null;
  const completions = [];
  const agent = new Agent({ client: {}, config, workspacePath: f.nested, toolContext: { projectsFile: f.projectsFile }, skillsEnabled: false,
    journal: turn => { journaled = turn; return path.join(sandbox, 'journal.json'); },
    onTurnComplete: async info => completions.push(info) });
  agent.streamTurn = async () => {
    noteFileEffects(agent.turnAudit, 'write_file', { path: 'src/a.js' }, agent.cwd);
    return { content: 'Edited it.', toolCalls: [] };
  };
  await agent.sendRequest('edit the file');

  assert.equal(journaled.projectId, f.project.id);
  assert.deepEqual(journaled.audit.files, ['src/a.js']);
  assert.equal(journaled.audit.changed, true);
  assert.equal(journaled.audit.termination, 'model_answer');
  assert.equal(journaled.audit.turnId, journaled.turnId);
  assert.equal(completions.length, 1);
  assert.equal(completions[0].projectId, f.project.id);
  assert.equal(completions[0].journalFile, path.join(sandbox, 'journal.json'));
  assert.equal(new ProjectStore(f.projectsFile).load().activeId, null);
});
