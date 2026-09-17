#!/usr/bin/env node
import { main } from "./src/cli.mjs";

main().catch((err) => {
  console.error("\n  fatal: " + err.message);
  if (err.detail) console.error("  " + JSON.stringify(err.detail));
  process.exit(1);
});
