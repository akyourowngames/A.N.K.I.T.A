import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DesktopEngine } from '../../desktop/electron/engine.mjs';
import { ProjectStore } from '../../src/memory/projects.mjs';

test('desktop projects assign real workspace paths and carry decisions and tasks into the teammate brief', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-projects-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const workspace = path.join(dir, 'work');
  fs.mkdirSync(workspace);
  const engine = new DesktopEngine({
    teammateFile: path.join(dir, 'teammates.json'), projectsFile: path.join(dir, 'projects.json'),
    settingsFile: path.join(dir, 'settings.json'), channelsFile: path.join(dir, 'channels.json'), sessionsDir: dir,
    config: { provider: 'test', tools: false, agentName: 'Ankita', username: 'User' },
    bootstrap: async () => ({ client: {}, tool: null, models: [], model: '', provider: { name: 'test' } }),
    mcp: { reconcile: async () => {}, ensureComposio: async () => {}, closeAll: async () => {}, summaries: () => [], connectedIds: [] },
  });
  await engine.init();
  const project = engine.createProject({ name: 'Widget', summary: 'Build the widget', path: workspace, conventions: ['Keep changes small'] });
  const teammate = engine.listTeammates()[0];
  engine.assignProject(teammate.id, project.id);
  const agent = engine.agentFor(teammate.id);
  assert.equal(agent.cwd, workspace);
  assert.match(agent.project, /Keep changes small/);
  engine.addProjectTodo(project.id, 'Finish the desktop');
  assert.match(agent.project, /Finish the desktop/);
  engine.addProjectRecord(project.id, 'decision', 'Use the existing agent runtime');
  assert.match(agent.project, /Use the existing agent runtime/);
  assert.equal(engine.listProjects()[0].todos.length, 1);
  engine.completeProjectTodo(project.id, 't1');
  assert.doesNotMatch(agent.project, /Finish the desktop/);
  engine.assignProject(teammate.id, null);
  assert.equal(agent.projectId, null);
  assert.equal(agent.cwd, process.cwd());
  await engine.close();
});

test('external project edits refresh the desktop and assigned agent context', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-project-watch-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const projectsFile = path.join(dir, 'projects.json');
  const events = [];
  const engine = new DesktopEngine({
    teammateFile: path.join(dir, 'teammates.json'), projectsFile,
    settingsFile: path.join(dir, 'settings.json'), channelsFile: path.join(dir, 'channels.json'), sessionsDir: dir,
    config: { provider: 'test', tools: false, agentName: 'Ankita', username: 'User' },
    bootstrap: async () => ({ client: {}, tool: null, models: [], model: '', provider: { name: 'test' } }),
    mcp: { reconcile: async () => {}, ensureComposio: async () => {}, closeAll: async () => {}, summaries: () => [], connectedIds: [] },
    emit: event => events.push(event),
  });
  t.after(() => engine.close());
  await engine.init();
  const project = engine.createProject({ name: 'Live project' });
  const teammate = engine.listTeammates()[0];
  engine.assignProject(teammate.id, project.id);
  const agent = engine.agentFor(teammate.id);
  engine.projectFileVersion = fs.readFileSync(projectsFile, 'utf8');
  events.length = 0;
  new ProjectStore(projectsFile).load().addTodo(project.id, 'Task from another process');
  const deadline = Date.now() + 3000;
  while (!events.some(event => event.type === 'projects-changed') && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 50));
  assert.ok(events.some(event => event.type === 'projects-changed'));
  assert.match(agent.project, /Task from another process/);
});

test('a changed turn on an assigned project records work and announces activity without touching the teammate', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-desktop-work-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const workspace = path.join(dir, 'work');
  fs.mkdirSync(workspace);
  const teammateFile = path.join(dir, 'teammates.json');
  const events = [];
  const engine = new DesktopEngine({
    teammateFile, projectsFile: path.join(dir, 'projects.json'),
    settingsFile: path.join(dir, 'settings.json'), channelsFile: path.join(dir, 'channels.json'), sessionsDir: dir,
    config: { provider: 'test', tools: false, agentName: 'Ankita', username: 'User' },
    bootstrap: async () => ({ client: {}, tool: null, models: [], model: '', provider: { name: 'test' } }),
    mcp: { reconcile: async () => {}, ensureComposio: async () => {}, closeAll: async () => {}, summaries: () => [], connectedIds: [] },
    emit: event => events.push(event),
  });
  t.after(() => engine.close());
  await engine.init();
  const project = engine.createProject({ name: 'Widget', path: workspace });
  const teammate = engine.listTeammates()[0];
  engine.assignProject(teammate.id, project.id);
  const agent = engine.agentFor(teammate.id);
  agent.journal = () => null; // never write to the real journal directory
  agent.streamTurn = async () => {
    agent.turnAudit.changed = true;
    agent.turnAudit.files.push('src/widget.js');
    return { content: 'Edited the widget.', toolCalls: [] };
  };
  const teammatesBefore = fs.readFileSync(teammateFile, 'utf8');
  events.length = 0;

  await agent.send('edit the widget');

  const stored = new ProjectStore(path.join(dir, 'projects.json')).load().find(project.id);
  assert.equal(stored.worklog.length, 1);
  assert.match(stored.worklog[0].text, /src\/widget\.js/);
  assert.ok(events.some(event => event.type === 'project-activity' && event.projectId === project.id && event.written >= 1));
  assert.ok(events.some(event => event.type === 'projects-changed'));
  assert.equal(engine.listProjects()[0].worklog.length, 1);
  assert.equal(fs.readFileSync(teammateFile, 'utf8'), teammatesBefore, 'automatic work never edits the teammate record');
});
