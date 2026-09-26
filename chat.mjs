#!/usr/bin/env node
import { main } from "./src/core/cli.mjs";
import { shutdownFileToolWorkers } from "./src/tooling/tool-worker.mjs";

// The resident inspection worker is unref'd, so it never blocks exit on its
// own; this makes the teardown explicit rather than incidental.
process.on("exit", shutdownFileToolWorkers);

main().catch((err) => {
  console.error("\n  fatal: " + err.message);
  if (err.detail) console.error("  " + JSON.stringify(err.detail));
  process.exit(1);
});
