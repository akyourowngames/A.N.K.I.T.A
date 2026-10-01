import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ISLAND_WIDTH, ISLAND_HEIGHT_COMPACT, ISLAND_HEIGHT_EXPANDED, ISLAND_EDGE_MARGIN,
  ISLAND_MODE_HIDDEN, ISLAND_MODE_COMPACT, ISLAND_MODE_EXPANDED,
  ISLAND_PETIT_WIDTH, ISLAND_PETIT_HEIGHT, ISLAND_HOME_WIDTH, ISLAND_PEEK_PX,
  ISLAND_VIEW_PETIT, ISLAND_VIEW_HOME, ISLAND_VIEW_HOME_EXPANDED, ISLAND_VIEW_TUCKED,
  ISLAND_COORD_MIN, ISLAND_COORD_MAX,
  islandBounds, islandCoord, islandHeightFor, islandModeFor, islandSizeFor, islandYFor,
} from '../../desktop/electron/island.mjs';
import { ApprovalRegistry } from '../../desktop/electron/approvals.mjs';

test('island sits top-centre of the work area', () => {
  const bounds = islandBounds({ x: 0, y: 0, width: 1920, height: 1040 });
  assert.equal(bounds.width, ISLAND_WIDTH);
  assert.equal(bounds.x, Math.round((1920 - ISLAND_WIDTH) / 2));
  assert.equal(bounds.y, 0);
});

test('island respects a work area offset (taskbar reservation)', () => {
  const bounds = islandBounds({ x: 1920, y: 40, width: 1920, height: 1000 });
  assert.equal(bounds.x, 1920 + Math.round((1920 - ISLAND_WIDTH) / 2));
  assert.equal(bounds.y, 40);
});

test('island shrinks with edge margins on narrow displays', () => {
  const bounds = islandBounds({ x: 0, y: 0, width: 200, height: 400 });
  assert.equal(bounds.width, 200 - ISLAND_EDGE_MARGIN * 2);
  assert.equal(bounds.x, ISLAND_EDGE_MARGIN);
});

test('island is hidden while the main window is visible', () => {
  assert.equal(islandModeFor({ mainVisible: true, approvalCount: 0 }), ISLAND_MODE_HIDDEN);
  assert.equal(islandModeFor({ mainVisible: true, approvalCount: 3 }), ISLAND_MODE_HIDDEN);
});

test('island appears compact when the main window is gone and expands for approvals', () => {
  assert.equal(islandModeFor({ mainVisible: false, approvalCount: 0 }), ISLAND_MODE_COMPACT);
  assert.equal(islandModeFor({ mainVisible: false, approvalCount: 2 }), ISLAND_MODE_EXPANDED);
});

test('island heights match the compact and expanded modes', () => {
  assert.equal(islandHeightFor(ISLAND_MODE_HIDDEN), ISLAND_HEIGHT_COMPACT);
  assert.equal(islandHeightFor(ISLAND_MODE_COMPACT), ISLAND_HEIGHT_COMPACT);
  assert.equal(islandHeightFor(ISLAND_MODE_EXPANDED), ISLAND_HEIGHT_EXPANDED);
});

test('petit tab is smaller than the home card, which grows with approvals', () => {
  assert.deepEqual(islandSizeFor(ISLAND_VIEW_PETIT, 0), { width: ISLAND_PETIT_WIDTH, height: ISLAND_PETIT_HEIGHT });
  assert.ok(ISLAND_PETIT_WIDTH < ISLAND_HOME_WIDTH);
  assert.deepEqual(islandSizeFor(ISLAND_VIEW_HOME, 0), { width: ISLAND_HOME_WIDTH, height: ISLAND_HEIGHT_COMPACT });
  assert.deepEqual(islandSizeFor(ISLAND_VIEW_HOME_EXPANDED, 2), { width: ISLAND_HOME_WIDTH, height: ISLAND_HEIGHT_EXPANDED });
  assert.deepEqual(islandSizeFor('bogus', 0), { width: ISLAND_PETIT_WIDTH, height: ISLAND_PETIT_HEIGHT });
});

test('tucked views hang above the edge with only a sliver showing', () => {
  assert.equal(islandYFor(ISLAND_VIEW_TUCKED, 0), -(ISLAND_PETIT_HEIGHT - ISLAND_PEEK_PX));
  assert.equal(islandYFor(ISLAND_VIEW_PETIT, 40), 40);
  assert.equal(islandYFor(ISLAND_VIEW_HOME, 40), 40);
  assert.ok(ISLAND_PEEK_PX > 0 && ISLAND_PEEK_PX < ISLAND_PETIT_HEIGHT);
});

test('registry lists pending tool approvals without resolve functions', async () => {
  const seen = [];
  const approvals = new ApprovalRegistry(event => seen.push(event));
  const pending = approvals.request('chief', 'write_file', 'Create a file');
  const listed = approvals.list();
  assert.equal(listed.length, 1);
  assert.equal(listed[0].requestId, seen[0].requestId);
  assert.equal(listed[0].toolName, 'write_file');
  assert.equal(listed[0].detail, 'Create a file');
  assert.equal(typeof listed[0].resolve, 'undefined');
  assert.equal(JSON.parse(JSON.stringify(listed)).length, 1);
  assert.equal(approvals.respond(seen[0].requestId, 'yes'), true);
  assert.equal(await pending, true);
  assert.deepEqual(approvals.list(), []);
});

test('island coordinates are int32-safe and never negative zero', () => {
  // Regression: Math.round(-0.4) is -0, which Number.isInteger accepts but
  // Electron's native converter rejects, crashing the main process from a
  // slide tick whenever interpolation crossed zero (e.g. y=-1 sliding to 0).
  const negZero = islandCoord(Math.round(-0.4), 0);
  assert.equal(negZero, 0);
  assert.equal(Object.is(negZero, -0), false);
  assert.equal(islandCoord(563.7, 0), 564);
  assert.equal(islandCoord(-50.2, 0), -50);
});

test('island coordinates fall back and clamp instead of throwing', () => {
  assert.equal(islandCoord(Number.NaN, 42), 42);
  assert.equal(islandCoord(undefined, 42), 42);
  assert.equal(islandCoord(Number.POSITIVE_INFINITY, 7), 7);
  assert.equal(islandCoord(1e20, 0), ISLAND_COORD_MAX);
  assert.equal(islandCoord(-1e20, 0), ISLAND_COORD_MIN);
  assert.equal(islandCoord(Number.NaN), 0);
});

test('every step of a zero-crossing slide is int32-safe', () => {
  // A slide from a frozen mid-flight position (y=-1) to y=0 must never emit
  // -0 or a non-integer at any easing value.
  for (let i = 0; i <= 100; i++) {
    const eased = i / 100;
    for (const [from, to] of [[-1, 0], [-68, -50], [0, -24], [-50, 0]]) {
      const step = islandCoord(from + (to - from) * eased, to);
      assert.equal(Number.isInteger(step), true);
      assert.equal(Object.is(step, -0), false);
      assert.ok(step >= ISLAND_COORD_MIN && step <= ISLAND_COORD_MAX);
    }
  }
});
