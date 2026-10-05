export type InteractionPhase = 'rest' | 'anticipate' | 'grab' | 'gulp' | 'reading' | 'success' | 'error';
export type InteractionFrame = {mouth: number; sx: number; sy: number; tilt: number; lift: number; fileProgress: number; done: boolean};
export const INTERACTION_MS: Record<InteractionPhase, number>;
export function interactionFrame(phase: InteractionPhase, elapsedMs: number, reducedMotion?: boolean): InteractionFrame;
