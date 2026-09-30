# Chrome local — packaged app fails to spawn MCP server

**Implemented 2026-09-27.** The original diagnosis below is preserved. The pinned
bridge is shipped/unpacked and Electron-owned MCP children enter Node mode.
Actual packaged verification reproduced legacy exit 0/no initialize, then opened
a CDP page with 30 bundled tools and empty PATH/npm cache. Final traces and limits
are in [the implementation ledger](browser-packaged-vault-implementation.md) and
[browser findings](../browser-screenshot-findings.md).

Date: 2026-09-26. Source: dev-vs-installed report + Plugins screenshot
(`MCP server exited (code 0) while waiting for initialize`, `Chrome local` stuck on `Setup needed`).

## 1. The issue

- In dev (`electron .` / `desktop:dev`), **Chrome local** connects to the real Chrome via a spawned `npx -y chrome-devtools-mcp@1.10.1` bridge.
- In the installed build (NSIS/portable from the GitHub release), pressing **Start connection** never brings Chrome up. The Plugins page shows `MCP server exited (code 0) while waiting for initialize`.
- Code `0` means the child quit cleanly before answering the first MCP `initialize` request — it never was an MCP server at all.

## 2. What is causing it

1. `src/integrations/browser-plugins.mjs:103-108` builds the Chrome bridge as `{ command: 'npx', args: [...] }`. `chrome-devtools-mcp` is **not a dependency** in `package.json` and is **not shipped** in `desktop/packaging/electron-builder.yml` (`files:` covers `src/tools/skills/desktop` plus auto-included `playwright`/`electron-updater` only). Every fresh machine must therefore download it through `npx` at connect time.
2. `src/integrations/mcp-client.mjs:71-98` `commandCandidates('npx')` on win32 rewrites `npx` to `{ command: process.execPath, args: [npx-cli.js] }` (likewise `resolveLaunch()`, lines 159-171, rewrites a cached `npx <pkg>` to `process.execPath <cached-entry.js>`). In dev `process.execPath` is `node`/dev-Electron, so this runs fine. Packaged, it is `Ankita.exe`.
3. `McpClient.connect()` (`mcp-client.mjs:410-420`) spawns with `serverEnv()` and **never sets `ELECTRON_RUN_AS_NODE=1`** — unlike `installChromium()` in `desktop/electron/browser-plugins.mjs:124-128`, which does. So the "server" child boots as a **second Ankita GUI instance**, hits the single-instance lock in `desktop/electron/main.mjs:274-276` (`if (!gotLock) app.quit()`), and exits with code `0`. The pending `initialize` in `mcp-client.mjs:456-467` is then rejected with exactly the screenshot's error.
4. Fallback is no better on machines without system Node: `npmRoots()` (`mcp-client.mjs:38-44`) first probes `dirname(Ankita.exe)/node_modules` (never exists packaged), then `%APPDATA%`/`%ProgramFiles%`. With no Node installed, `shimScript()` returns null and candidates degrade to `npx.exe / npx.cmd / npx`, which need Node on `PATH`. Dev box has Node; clean user box often does not.

Secondary (not the silent failure, but bites after any update): `configureChrome()` (`desktop/electron/browser-plugins.mjs:49-59`) deletes + re-adds the `ankita-chrome` record whenever command/args change (e.g. a version-pin bump), which voids `approvedHash` (`src/integrations/mcp-store.mjs:141-143`) and forces one fresh approval. This surfaces as a re-approval prompt, not as exit-code-0.

## 3. What is affected / not working

- **Broken:** Chrome local in the installed/packaged app — all three modes (`profile`, `port`, `active`), first connect and reconnects. The `initialize` handshake can never complete because the spawned process is a duplicate app instance, not the MCP bridge. Cold download and warm cached-launch paths are both affected since both go through `process.execPath`.
- **Not broken:** Playwright Browser (`Ready` in the same screenshot) — it runs in-process through the bundled `playwright` dep, no `npx` spawn involved. Terminal/CLI use on a Node-equipped dev machine also still works for the same reason.
- **Fix direction (not applied):** bundle `chrome-devtools-mcp` as a real dependency, ship it in `electron-builder.yml` `files`, and spawn its entry under a Node runtime (`ELECTRON_RUN_AS_NODE=1`, mirroring `installChromium()`), plus pre-warm on enable so first connect is not a cold download. Confirm via `%USERPROFILE%\.copilot-chat-cli\mcp.json` (`ankita-chrome.lastError`) and the renderer DevTools console while pressing Start connection.
