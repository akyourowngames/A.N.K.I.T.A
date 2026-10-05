// Island home-card view names and default routing.
// Mirrors Coucou's IslandViewName + State.defaultView() reduced to the views
// with an Ankita data source (MIT License, (c) Louis Raille).

export type IslandHomeView =
  | 'overview'
  | 'empty'
  | 'approval'
  | 'error'
  | 'finished'
  | 'note'
  | 'prompt'
  | 'settings';

// Default routing rule (approvals → approval, running → overview, else empty)
// lives in desktop/electron/island.mjs as islandDefaultView() with tests;
// Island.tsx applies the same rule inline so the renderer stays dependency-free.
