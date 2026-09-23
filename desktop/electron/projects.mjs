import fs from 'node:fs';

/** Keep project context useful without filling every model request with the whole log. */
export function projectContext(project) {
  if (!project) return '';
  const lines = [`Project: ${project.name} (${project.id})`];
  if (project.summary) lines.push(`Purpose: ${project.summary}`);
  if (project.path) lines.push(`Workspace: ${project.path}`);
  if (project.repo) lines.push(`Repository: ${project.repo}`);
  if (project.client) lines.push(`Client: ${project.client}`);
  if (project.conventions?.length) lines.push(`Conventions: ${project.conventions.slice(0, 5).join('; ').slice(0, 500)}`);
  const decisions = (project.decisions || []).slice(-4);
  if (decisions.length) lines.push('Recent decisions:', ...decisions.map(item => `- ${String(item.text).slice(0, 240)}`));
  const open = (project.todos || []).filter(item => !item.done).slice(0, 6);
  if (open.length) lines.push('Open tasks:', ...open.map(item => `- ${String(item.text).slice(0, 240)}`));
  const notes = (project.notes || []).slice(-3);
  if (notes.length) lines.push('Recent notes:', ...notes.map(item => `- ${String(item.text).slice(0, 240)}`));
  return lines.join('\n');
}

export function projectWorkspace(project) {
  if (!project?.path) return null;
  try { return fs.statSync(project.path).isDirectory() ? project.path : null; }
  catch { return null; }
}

export function projectSummary(project) {
  return {
    id: project.id, name: project.name, summary: project.summary || '',
    path: project.path || '', repo: project.repo || '', client: project.client || '',
    conventions: project.conventions || [], status: project.status || 'active',
    archived: Boolean(project.archived), decisions: (project.decisions || []).slice(-8),
    notes: (project.notes || []).slice(-8), todos: project.todos || [],
    lastUsedAt: project.lastUsedAt || null,
  };
}
