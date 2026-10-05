import test from 'node:test';
import assert from 'node:assert/strict';
import { SIDEBAR_WIDTH, sidebarWidth } from '../../desktop/shared/desktop-layout.mjs';

test('restored and dragged sidebar widths stay within the roster layout bounds', () => {
  assert.equal(sidebarWidth(SIDEBAR_WIDTH.min - 1), SIDEBAR_WIDTH.min);
  assert.equal(sidebarWidth(SIDEBAR_WIDTH.max + 1), SIDEBAR_WIDTH.max);
  assert.equal(sidebarWidth(SIDEBAR_WIDTH.default), SIDEBAR_WIDTH.default);
});

test('corrupt persisted sidebar widths fall back rather than making the layout unusable', () => {
  for (const value of [undefined, null, '288', NaN, Infinity, -Infinity, {}]) assert.equal(sidebarWidth(value), SIDEBAR_WIDTH.default);
});
