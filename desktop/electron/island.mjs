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
export const ISLAND_WIDTH = 640;
export const ISLAND_HEIGHT_COMPACT = 76;
export const ISLAND_HEIGHT_EXPANDED = 232;
// Chat gets a tall card so the log never clips: header + tabs + ~5 messages + input.
export const ISLAND_HEIGHT_CHAT = 420;
// Minimum margin kept between the island and the left/right screen edges when
// the display is narrower than the island itself.
export const ISLAND_EDGE_MARGIN = 8;

export const ISLAND_MODE_HIDDEN = 'hidden';
export const ISLAND_MODE_COMPACT = 'compact';
export const ISLAND_MODE_EXPANDED = 'expanded';

// Petit tab (collapsed) vs home card (expanded) sizes, logical pixels.
// Coucou-style: a small tab stuck to the top-centre opens into the full card.
export const ISLAND_PETIT_WIDTH = 288;
export const ISLAND_PETIT_HEIGHT = 64;
export const ISLAND_HOME_WIDTH = ISLAND_WIDTH;

export const ISLAND_VIEW_PETIT = 'petit';
export const ISLAND_VIEW_HOME = 'home';
export const ISLAND_VIEW_HOME_EXPANDED = 'home-expanded';
export const ISLAND_VIEW_HOME_CHAT = 'home-chat';
export const ISLAND_VIEW_TUCKED = 'tucked';

/** Named island views, mirroring Coucou's IslandViewName subset that has an
 * Ankita data source (mail/searching/result stay placeholders upstream too). */
export const ISLAND_VIEW_OVERVIEW = 'overview';
export const ISLAND_VIEW_EMPTY = 'empty';
export const ISLAND_VIEW_APPROVAL = 'approval';
export const ISLAND_VIEW_ERROR = 'error';
export const ISLAND_VIEW_FINISHED = 'finished';
export const ISLAND_VIEW_NOTE = 'note';
export const ISLAND_VIEW_PROMPT = 'prompt';
export const ISLAND_VIEW_SETTINGS = 'settings';

// Visible sliver of the petit tab while tucked above the screen edge —
// Coucou's wake strip: just enough to hover and click.
export const ISLAND_PEEK_PX = 14;

/** Window size for an island view. Home grows taller while approvals pend.
 * Clamped to the known presets so a bad caller can never stretch the window. */
export function islandSizeFor(view, approvalCount) {
  const raw = innerIslandSizeFor(view, approvalCount);
  return {
    width: Math.min(ISLAND_HOME_WIDTH, Math.max(ISLAND_PETIT_WIDTH, raw.width)),
    height: Math.min(ISLAND_HEIGHT_CHAT, Math.max(ISLAND_PETIT_HEIGHT, raw.height)),
  };
}

/** Fit a window height under the work-area bottom so a tall card (chat) never
 * runs off-screen on short displays. Pure so tests can cover it. */
export function islandClampHeight(height, y, area) {
  const room = (area?.y ?? 0) + (area?.height ?? height) - y;
  return Math.min(height, Math.max(ISLAND_PETIT_HEIGHT, room));
}

function innerIslandSizeFor(view, approvalCount) {
  if (view === ISLAND_VIEW_HOME_CHAT) {
    return { width: ISLAND_HOME_WIDTH, height: ISLAND_HEIGHT_CHAT };
  }
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

/** Fit the remembered center and requested size to the current display, in logical pixels. */
export function islandFittedBounds(area, size, anchorCX = null, view = ISLAND_VIEW_HOME) {
  const centered = islandBounds(area, size.width);
  const left = area.x + ISLAND_EDGE_MARGIN;
  const right = Math.max(left, area.x + area.width - ISLAND_EDGE_MARGIN - centered.width);
  const preferredX = anchorCX == null ? centered.x : anchorCX - centered.width / 2;
  const y = islandYFor(view, area.y);
  return { x: islandCoord(Math.min(right, Math.max(left, preferredX))), y: islandCoord(y),
    width: centered.width, height: islandClampHeight(size.height, y, area) };
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

/** Default home-card view from live counts — Coucou's State.defaultView()
 * reduced to the views that have an Ankita data source. */
export function islandDefaultView({ approvalCount, runningCount }) {
  if (Number(approvalCount) > 0) return ISLAND_VIEW_APPROVAL;
  if (Number(runningCount) > 0) return ISLAND_VIEW_OVERVIEW;
  return ISLAND_VIEW_EMPTY;
}
