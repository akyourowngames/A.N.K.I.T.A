/**
 * The companion island: a small always-on-top pill that appears at the top
 * edge of the screen whenever the main window is not visible (minimized or
 * hidden to the tray). Clicking it restores the main window.
 *
 * This module is deliberately free of Electron imports so the geometry and
 * visibility rules stay unit-testable with plain node:test.
 */

// Pixel dimensions of the island window. The compact bar shows the mascot and
// a status line; the expanded bar also lists pending approvals.
export const ISLAND_WIDTH = 368;
export const ISLAND_HEIGHT_COMPACT = 76;
export const ISLAND_HEIGHT_EXPANDED = 232;
// Minimum margin kept between the island and the left/right screen edges when
// the display is narrower than the island itself.
export const ISLAND_EDGE_MARGIN = 8;

export const ISLAND_MODE_HIDDEN = 'hidden';
export const ISLAND_MODE_COMPACT = 'compact';
export const ISLAND_MODE_EXPANDED = 'expanded';

// Petit tab (collapsed) vs home card (expanded) sizes, logical pixels.
// Coucou-style: a small tab stuck to the top-centre opens into the full card.
export const ISLAND_PETIT_WIDTH = 240;
export const ISLAND_PETIT_HEIGHT = 64;
export const ISLAND_HOME_WIDTH = 368;

export const ISLAND_VIEW_PETIT = 'petit';
export const ISLAND_VIEW_HOME = 'home';
export const ISLAND_VIEW_HOME_EXPANDED = 'home-expanded';
export const ISLAND_VIEW_TUCKED = 'tucked';

// Visible sliver of the petit tab while tucked above the screen edge —
// Coucou's wake strip: just enough to hover and click.
export const ISLAND_PEEK_PX = 14;

/** Window size for an island view. Home grows taller while approvals pend.
 * Clamped to the known presets so a bad caller can never stretch the window. */
export function islandSizeFor(view, approvalCount) {
  const raw = innerIslandSizeFor(view, approvalCount);
  return {
    width: Math.min(ISLAND_HOME_WIDTH, Math.max(ISLAND_PETIT_WIDTH, raw.width)),
    height: Math.min(ISLAND_HEIGHT_EXPANDED, Math.max(ISLAND_PETIT_HEIGHT, raw.height)),
  };
}

function innerIslandSizeFor(view, approvalCount) {
  if (view === ISLAND_VIEW_HOME_EXPANDED) {
    return { width: ISLAND_HOME_WIDTH, height: islandHeightFor(ISLAND_MODE_EXPANDED) };
  }
  if (view === ISLAND_VIEW_HOME) {
    return { width: ISLAND_HOME_WIDTH, height: islandHeightFor(ISLAND_MODE_COMPACT) };
  }
  return { width: ISLAND_PETIT_WIDTH, height: ISLAND_PETIT_HEIGHT };
}

/** Top edge for an island view: tucked views hang above the screen edge. */
export function islandYFor(view, areaY) {
  if (view === ISLAND_VIEW_TUCKED) return Math.round(areaY - (ISLAND_PETIT_HEIGHT - ISLAND_PEEK_PX));
  return Math.round(areaY);
}

// Electron's native int converter rejects values outside the signed 32-bit
// range (and negative zero), throwing "conversion failure" from setPosition /
// setSize. Window coordinates must therefore be int32-safe, not merely
// integers: Math.round(-0.4) is -0, which Number.isInteger accepts but the
// converter rejects, crashing the main process from inside a slide tick.
export const ISLAND_COORD_MIN = -2147483647;
export const ISLAND_COORD_MAX = 2147483647;

/** Sanitise a window coordinate for Electron: int32-safe integer, never -0.
 * Non-finite input falls back so a bad caller can never throw from setPosition. */
export function islandCoord(value, fallback = 0) {
  const input = Number.isFinite(value) ? value : fallback;
  const rounded = (Number.isFinite(input) ? Math.round(input) : 0) + 0; // +0 turns -0 into +0.
  if (rounded < ISLAND_COORD_MIN) return ISLAND_COORD_MIN;
  if (rounded > ISLAND_COORD_MAX) return ISLAND_COORD_MAX;
  return rounded;
}

/**
 * Top-centre position for the island inside a display work area, Coucou-style:
 * hugging the top edge of the screen instead of hiding inside a notch.
 * Pure function of { x, y, width, height } so tests can pass a fake work area.
 */
export function islandBounds(workArea, width = ISLAND_WIDTH) {
  const area = { x: workArea?.x || 0, y: workArea?.y || 0, width: workArea?.width || width };
  const fitted = Math.max(0, Math.min(width, area.width - ISLAND_EDGE_MARGIN * 2));
  return {
    width: Math.round(fitted),
    x: Math.round(area.x + (area.width - fitted) / 2),
    // Hug the top edge of the work area (below the taskbar reservation, if any).
    y: Math.round(area.y),
  };
}

export function islandHeightFor(mode) {
  if (mode === ISLAND_MODE_EXPANDED) return ISLAND_HEIGHT_EXPANDED;
  return ISLAND_HEIGHT_COMPACT;
}

/**
 * Which mode the island should be in. The island is a stand-in for the main
 * window, so it is only visible while the main window is not: minimized or
 * hidden to the tray. While visible it expands whenever approvals are pending.
 */
export function islandModeFor({ mainVisible, approvalCount }) {
  if (mainVisible) return ISLAND_MODE_HIDDEN;
  if (Number(approvalCount) > 0) return ISLAND_MODE_EXPANDED;
  return ISLAND_MODE_COMPACT;
}
