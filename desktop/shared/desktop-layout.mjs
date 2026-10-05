// CSS pixels; the expanded sidebar contains the navigation rail and teammate roster.
export const SIDEBAR_WIDTH = Object.freeze({ min: 256, default: 288, max: 416 });
export const COMPOSE_EVENT = 'ankita:compose'; // Renderer event; prepare a draft without sending a turn.

export function sidebarWidth(value) {
  return Number.isFinite(value) ? Math.min(SIDEBAR_WIDTH.max, Math.max(SIDEBAR_WIDTH.min, value)) : SIDEBAR_WIDTH.default;
}
