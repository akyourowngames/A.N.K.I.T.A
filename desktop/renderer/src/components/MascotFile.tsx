import type { MascotInteraction } from '../lib/useMascotInteraction';
import { INTERACTION_MS } from '../../../shared/mascot-interaction.mjs';

export function MascotFile({ interaction }: {interaction: MascotInteraction}) {
  return interaction.phase === 'gulp' ? <span className="mascot-swallow-file" style={{'--companion-swallow-ms': INTERACTION_MS.gulp + 'ms'} as React.CSSProperties} key={interaction.started} aria-hidden="true"><span>▤</span><small>{interaction.label}</small></span> : null;
}
