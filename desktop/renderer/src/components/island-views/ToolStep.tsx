import { Icon } from './icons';
import type { IslandTool } from '../../../../shared/island-state.mjs';

export const TOOL_ICON = { running: 'chevronRight', ok: 'check', error: 'xmark' } as const; // Tool-state icon contract, shared with the rolling overview.
export const TOOL_STATUS = { running: 'Running', ok: 'Completed', error: 'Failed' } as const; // Accessible UI labels for the same tool states on both surfaces.
export const TOOL_ICON_SIZE_PX = 12; // CSS pixels; identical tool icons in overview and conversation.
export const TOOL_ICON_STROKE = 2; // SVG units; common tool icon weight.

/** One tool identity, with its real arguments and result available by keyboard or click. */
export function ToolStep({ tool }: { tool: IslandTool }) {
  const args = typeof tool.args === 'string' ? tool.args : JSON.stringify(tool.args, null, 2);
  return <details className={'island-tool ' + tool.state}>
    <summary role="button" aria-label={tool.detail + ', ' + TOOL_STATUS[tool.state]}>
      <Icon name={TOOL_ICON[tool.state]} size={TOOL_ICON_SIZE_PX} stroke={TOOL_ICON[tool.state] === 'xmark' ? undefined : TOOL_ICON_STROKE} />
      <span className="island-tool-label">{tool.detail}</span>
      <span className="island-tool-state">{TOOL_STATUS[tool.state]}</span>
    </summary>
    <div className="island-tool-output">
      {args && <pre aria-label="Tool arguments">{args}</pre>}
      <pre aria-label="Tool result">{tool.result || (tool.state === 'running' ? 'Waiting for output…' : 'No output returned.')}</pre>
    </div>
  </details>;
}
