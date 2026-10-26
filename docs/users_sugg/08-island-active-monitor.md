# Problem: island doesn't follow the monitor you're working on

## Problem

The companion island anchors to the display nearest the main window
(`islandArea()` in `desktop/electron/main.mjs`), falling back to the primary
display. It does not follow the cursor or the active screen. So if the main
window was minimized on monitor 1 while the user is working on monitor 2,
the island shows up on monitor 1 — the wrong screen for the approvals it
exists to surface.

The positioning math itself is fine: `islandBounds` in
`desktop/electron/island.mjs` is pure of the display work area, so the island
lands correctly on whatever display it is given. Only the display choice is
wrong.

Source: mp6nfjxhrlxc, Oct 11, 2026, on "Ankita v2.5.0: a desktop companion
island that never misses an approval". Status: agreed in thread ("a fair gap
to name").

## Design

The island should follow the user's attention, not the main window's last
resting place. "Never misses an approval" fails if the approval surface is
on a screen the user is not looking at.

## Solution

1. Track the active display — the display with the cursor, or the display
   holding the currently focused window — and anchor the island there.
2. Keep the existing fallbacks in order: active display, then display
   nearest the main window, then primary.
3. Re-evaluate the anchor when focus moves screens, not only when the island
   is created, so it follows the user through the session.

## Acceptance

- Manual test: main window minimized on monitor 1, work on monitor 2 →
  island appears on monitor 2.
- Single-monitor behaviour unchanged; fallback order preserved when no
  active display can be determined.
