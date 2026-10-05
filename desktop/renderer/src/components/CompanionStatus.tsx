import { useRef, useState } from 'react';
import type { ChatMessage, Teammate } from '../../../shared/wire';
import { islandToolState, summarizeIslandTool } from '../../../shared/island-state.mjs';
import { Mascot } from './Mascot';
import { useMascotInteraction } from '../lib/useMascotInteraction';
import { useMascotCapture } from '../lib/useMascotCapture';
import { FILE_DROP_EVENT } from '../../../browser-helper/protocol.mjs';
import { MascotFile } from './MascotFile';
import { BrowserHelperSetup } from './BrowserHelperSetup';

const HEADER_MASCOT_PX = 42; // CSS pixels; companion fits the desktop title bar.
export function CompanionStatus({ messages, running, teammate }: { messages: ChatMessage[]; running: boolean; teammate: Teammate }) {
  const lookRef = useRef({ x: 0, y: 0 });
  const {interaction, pose, reset} = useMascotInteraction(teammate.id);
  const capture = useMascotCapture();
  const [helperOpen, setHelperOpen] = useState(false);
  const dragDepth = useRef(0);
  const lastUser = messages.length - 1 - [...messages].reverse().findIndex(item => item.role === 'user');
  const currentTurn = messages.slice(lastUser + 1);
  const tool = [...currentTurn].reverse().find((item): item is Extract<ChatMessage, { role: 'tool' }> => item.role === 'tool' && !item.hidden && !item.endedAt);
  const state = running ? tool ? islandToolState(tool.name) : 'thinking' : 'idle';
  const detail = running ? tool ? summarizeIslandTool(tool.name, tool.args) : 'Thinking' : 'Ready when you are';
  return <span className="header-companion" title={capture.message || detail + ' · Drag onto a webpage; drop files here'} data-mascot-state={state}
    onMouseEnter={() => { if (!capture.setup?.paired) void capture.refresh(); }}
    draggable onDragStart={event => { if (capture.start(event, teammate.id)) pose('grab'); }} onDragEnd={event => { capture.end(event); reset(); }}
    onDragEnter={event => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); dragDepth.current++; pose('anticipate'); } }}
    onDragOver={event => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; } }}
    onDragLeave={() => { if (--dragDepth.current <= 0) { dragDepth.current = 0; if (interaction.phase === 'anticipate') reset(); } }}
    onDrop={event => { if (!event.dataTransfer.files.length) return; event.preventDefault(); dragDepth.current = 0; window.dispatchEvent(new CustomEvent(FILE_DROP_EVENT, {detail: {threadId: teammate.id, files: Array.from(event.dataTransfer.files)}})); }}
    onPointerMove={event => {
      const rect = event.currentTarget.getBoundingClientRect();
      lookRef.current = { x: (event.clientX - rect.left) / rect.width * 2 - 1, y: 1 - (event.clientY - rect.top) / rect.height * 2 };
    }} onPointerLeave={() => { lookRef.current = { x: 0, y: 0 }; }}>
    <Mascot state={state} size={HEADER_MASCOT_PX} lookRef={lookRef} interaction={interaction} color={teammate.color} />
    <MascotFile interaction={interaction} />
    <button className="companion-helper-toggle" type="button" aria-label="Browser helper" onClick={() => {setHelperOpen(!helperOpen); void capture.refresh();}}>↗</button>
    {helperOpen && <span className="companion-helper-popover" draggable={false}><BrowserHelperSetup /></span>}
    {capture.message && <span className="companion-capture-toast" role="status">{capture.message}</span>}
    <span className="sr-only">{detail}</span>
  </span>;
}
