import { useState } from 'react';
import type { SubagentActivity } from '../../../shared/subagent-state.mjs';
import { humanizeTool, summarizeArgs } from '../lib/format';
import { SUBAGENT_TOOL_STATE_LABEL, subagentToolHint } from '../lib/subagent';
import { Icon } from './Icons';

type Tool = SubagentActivity['tools'][number];
type ToolGroup = { name: string; tools: Tool[] };

// Runs longer than this fold into one expandable row so an explore child reading
// dozens of pages does not bury the rest of the panel.
const GROUP_OPEN_LIMIT = 3; // rows — short runs stay open, long runs start folded

// Consecutive calls keep their order and honest sequence; only same-name runs fold.
function groupRuns(tools: Tool[]): ToolGroup[] {
  const groups: ToolGroup[] = [];
  for (const tool of tools) {
    const last = groups[groups.length - 1];
    if (last && last.name === tool.name) last.tools.push(tool);
    else groups.push({ name: tool.name, tools: [tool] });
  }
  return groups;
}

function stateIcon(state: string) {
  return state === 'running' ? 'pulse' : state === 'ok' ? 'check' : 'alert';
}

function groupState(tools: Tool[]) {
  if (tools.some(tool => tool.state === 'running')) return { key: 'running', label: 'Running' };
  const failed = tools.filter(tool => tool.state !== 'ok' && tool.state !== 'stopped').length;
  if (failed) return { key: 'failed', label: `${failed} failed` };
  if (tools.every(tool => tool.state === 'stopped')) return { key: 'stopped', label: 'Stopped' };
  return { key: 'ok', label: 'Done' };
}

function ToolRow({ tool }: { tool: Tool }) {
  const hint = subagentToolHint(tool.args);
  return <li className={`subagent-tool-row ${tool.state}`}>
    <Icon name={stateIcon(tool.state)} size={13} />
    <span>{humanizeTool(tool.name)}</span>
    {hint && <small title={summarizeArgs(tool.args)}>{hint}</small>}
    <em>{SUBAGENT_TOOL_STATE_LABEL[tool.state] || tool.state}</em>
  </li>;
}

export function SubagentTools({ tools }: { tools: SubagentActivity['tools'] }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  if (!tools.length) return null;
  return <ol className="subagent-tools">
    {groupRuns(tools).map(group => {
      if (group.tools.length === 1) return <ToolRow key={group.tools[0].callId} tool={group.tools[0]} />;
      const key = group.tools[0].callId;
      const state = groupState(group.tools);
      const expanded = open[key] ?? group.tools.length <= GROUP_OPEN_LIMIT;
      return <li key={key} className={`subagent-tool-group ${state.key}`}>
        <button type="button" className="subagent-tool-group-head" aria-expanded={expanded} onClick={() => setOpen(current => ({ ...current, [key]: !expanded }))}>
          <Icon name={stateIcon(state.key)} size={13} />
          <span>{humanizeTool(group.name)}</span>
          <small className="subagent-tool-count">{group.tools.length} calls</small>
          <em>{state.label}</em>
          <Icon name="chevron" size={12} />
        </button>
        {expanded && <ol className="subagent-tool-rows">
          {group.tools.map(tool => <ToolRow key={tool.callId} tool={tool} />)}
        </ol>}
      </li>;
    })}
  </ol>;
}
