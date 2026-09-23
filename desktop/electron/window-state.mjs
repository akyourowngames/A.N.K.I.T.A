import fs from 'node:fs';
import path from 'node:path';

/**
 * Remembers where the window was, so the app reopens the way the user left it.
 * Bounds are validated on load and re-checked against the connected displays in
 * main, because a saved position can point at a monitor that is no longer there.
 */

export const DEFAULT_BOUNDS = { width: 1280, height: 800 };

const between = (value, min, max) => (Number.isFinite(value) && value >= min && value <= max ? Math.round(value) : null);

export function loadWindowState(file, defaults = DEFAULT_BOUNDS) {
  let parsed = {};
  try {
    parsed = JSON.parse(fs.readFileSync(file, 'utf8')) || {};
  } catch {
    parsed = {};
  }
  const bounds = parsed.bounds || {};
  return {
    width: between(bounds.width, 840, 20000) ?? defaults.width,
    height: between(bounds.height, 560, 20000) ?? defaults.height,
    x: Number.isInteger(bounds.x) ? bounds.x : undefined,
    y: Number.isInteger(bounds.y) ? bounds.y : undefined,
    maximized: parsed.maximized === true,
  };
}

export function saveWindowState(file, win) {
  try {
    const bounds = win.getNormalBounds();
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify({ bounds, maximized: win.isMaximized() }, null, 2));
  } catch {
    // A failed state write must never take the app down.
  }
}

/** Drop a saved position that no longer overlaps any connected display. */
export function visibleBounds(bounds, displays) {
  if (!Number.isInteger(bounds.x) || !Number.isInteger(bounds.y)) return bounds;
  const matches = displays.some(display => {
    const area = display.workArea;
    return bounds.x < area.x + area.width && bounds.x + bounds.width > area.x
      && bounds.y < area.y + area.height && bounds.y + bounds.height > area.y;
  });
  return matches ? bounds : { width: bounds.width, height: bounds.height, x: undefined, y: undefined, maximized: bounds.maximized };
}
