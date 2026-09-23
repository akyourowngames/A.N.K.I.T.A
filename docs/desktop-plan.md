# ankita desktop — Electron + React implementation plan

Status: v1 chat core implemented. Installer packaging and the later features in §12 remain planned.
Engine: shared with the CLI (`src/`, `tools/`), driven headlessly from the Electron main process.

Run locally from the repository root:

```bash
npm install
npm run desktop:dev
# or: npm run desktop:build && npm run desktop:start
```

---

## 1. Goals and locked decisions

| Decision | Choice |
| --- | --- |
| Sidebar contents | **Teammates** — named personas, each with its own persona/system prompt and its own persisted thread. |
| Renderer stack | **React + Vite + TypeScript.** |
| Engine hosting | Runs **in the Electron main process**, behind one `engine` facade; renderer talks over IPC. |
| v1 scope | **Chat core:** teammates, streaming replies, tool-call cards, approval prompts, persisted threads, model picker, markdown. |
| Window look | "Classic" frameless, macOS-style traffic lights (matches the reference), native-frame fallback. |

Deferred: settings GUI, MCP/Composio management UI, projects UI, proactive daemon + tray,
voice, multi-window, packaging/auto-update.

---

## 2. Current state: the engine is already a headless library

The GUI is just another front-end. Evidence:

- `Agent` takes injected `confirm`, `print`, `write`, and `send(text, opts)` emits
  `onDelta / onReasoning / onToolCall / onToolResult / onUsage / onMessageStart / onMessageEnd`
  (`src/agent.mjs:147`, `:548`).
- The daemon already drives it exactly like a GUI would: a custom `confirm`, silent
  `print`, a per-chat `Agent` cache, and session restore (`src/daemon.mjs:142-173`).
- Telegram already maps approval replies into `confirm` resolutions
  (`src/daemon.mjs:194-248`).

Reusable as-is:

- Config: `loadConfig` (`src/config.mjs`)
- Provider/model: `CopilotClient`, `CompatibleClient`, `resolveProvider`, `pickModel` (`src/provider.mjs`)
- Sessions/journal: `saveSession`, `recordTurn` (`src/sessions.mjs`), `sanitizeMessages` (`src/history.mjs`)
- Tools/MCP/Composio: `McpManager` + `ensureComposio` (`src/mcp-manager.mjs`), `displayArgs` (`tools/index.mjs`)
- Auth: `resolveGithubToken`, `deviceLogin` (`src/auth.mjs`)

No engine rewrite is required. Only small extractions (§9) to avoid duplicating CLI bootstrap logic.

---

## 3. Repo layout

Single root `package.json`; desktop code under `desktop/`.

```
copilot-chat/
  src/ tools/                      # engine — unchanged, shared with the CLI
  desktop/
    electron/
      main.mjs                     # window, lifecycle, IPC router
      preload.cjs                  # contextBridge: window.ankita
      engine.mjs                   # facade over Agent + McpManager + stores
      teammates.mjs                # teammate store (+ pure, unit-tested)
      approvals.mjs                # pending-approval registry
      window-chrome.mjs            # frameless/titlebar per platform
    shared/
      wire.ts                      # engine event + IPC payload types (main ↔ renderer)
    renderer/
      index.html
      src/
        main.tsx  App.tsx
        state/store.tsx            # reducer + window.ankita wiring
        components/
          Sidebar.tsx  TeammateRow.tsx  NewTeammateDialog.tsx
          ChatPane.tsx  MessageList.tsx  Message.tsx
          ToolCallCard.tsx  ApprovalDialog.tsx  Thinking.tsx
          Composer.tsx  ModelPicker.tsx
        lib/markdown.tsx  lib/relative-time.ts
    vite.config.ts  tsconfig.json
  package.json                      # gains electron devDeps + scripts
  electron-builder.yml              # later phase
```

- Root `package.json` keeps zero **runtime** deps (`dependencies` stays empty) so the
  published CLI (`bin: ankita`) stays lean. Electron/React/Vite land in `devDependencies`.
- Root `main` points at `desktop/electron/main.mjs` (Electron's entry); `bin` still points at `chat.mjs`.
- Alternative: a self-contained `desktop/package.json` plus a staging copy of `src/`+`tools/`
  before packaging. Single-root is recommended for now.

---

## 4. Process model

```
Electron main (Node, ESM)                     Renderer (React, sandboxed)
  engine.mjs                                    window.ankita (contextBridge)
   ├─ loadConfig()                                ├─ invoke: listTeammates/create/.../send/cancel
   ├─ client + tool client + models               ├─ invoke: respondApproval / listModels / setModel
   ├─ one McpManager (+ ensureComposio)            └─ on: "engine:event" (typed payloads)
   ├─ TeammateStore (JSON, atomic)
   ├─ Approvals registry
   └─ per-teammate Agent (lazy)
```

- One window. `loadFile(desktop/renderer/dist/index.html)` (`file://`). No remote content,
  no local server in v1.
- `contextIsolation: true`, `sandbox: true`, `nodeIntegration: false`;
  `setWindowOpenHandler` denies popups; block `will-navigate`; CSP meta in `index.html`.
- The facade boundary means the engine can later move to `utilityProcess.fork` + loopback SSE
  without touching the UI.

---

## 5. Engine facade (`desktop/electron/engine.mjs`)

All methods async and IPC-invokable.

```
init()                      // loadConfig, ensureDirs, clients, models, start McpManager,
                            // connect approved MCP + Composio
listModels() -> Model[]
getSettingsSummary() -> {...}                 // non-secret config for UI
setModel(teammateId, modelId)

listTeammates() -> Teammate[]
createTeammate({name, color, persona, projectId?, model?}) -> Teammate
updateTeammate(id, patch) -> Teammate
deleteTeammate(id)

loadThread(id) -> Message[]                   // sanitized, system messages stripped
send(id, text) -> {turnId}
cancel(id)
respondApproval(requestId, "yes"|"no"|"always")
```

Per-teammate `Agent` construction mirrors the daemon (`src/daemon.mjs:146`):

```js
const agent = new Agent({
  client, tool, mcp,
  config: { ...baseConfig, agentName: t.name, systemExtra: t.persona },
  journal: turn => recordTurn(turn, { timeZone: baseConfig.timeZone }),
  confirm: (toolName, detail) => approvals.request(t.threadId, toolName, detail), // -> Promise<boolean>
  print: () => {}, write: () => {},
});
agent.model = t.model || baseModel;
// restore messages from the thread file: sanitizeMessages(..., drop role:"system")
```

### Events → renderer (single channel `engine:event`, typed in `desktop/shared/wire.ts`)

| event | payload |
| --- | --- |
| `turn-start` / `turn-end` | `{ threadId, turnId, model }` |
| `message-start` / `message-end` | `{ threadId, messageId }` |
| `assistant-delta` | `{ threadId, text }` |
| `reasoning-delta` | `{ threadId, text }` |
| `tool-call` | `{ threadId, callId, name, args, display }` (`display` from `displayArgs`) |
| `tool-result` | `{ threadId, callId, text, isError }` |
| `usage` | `{ threadId, prompt_tokens, completion_tokens, estimated_cost }` |
| `approval-request` | `{ requestId, threadId, toolName, detail }` |
| `error` | `{ threadId, message }` |

Behavior notes:

- Cancel maps to `Agent.cancel()` (abort controller) — already supported.
- `turn-end` saves the thread via `saveSession` and updates the sidebar preview/timestamp.
- Multiple teammates may run at once; `McpManager` is shared and safe. Per teammate, one turn
  at a time (composer disabled while running).

---

## 6. Teammate model (`desktop/electron/teammates.mjs`)

Atomic JSON store mirroring `McpStore` (re-read before write, `writeTextFile`).
File: `CONFIG_DIR/desktop-teammates.json`.

```json
{ "version": 1, "teammates": [
  { "id": "chief", "name": "Chief", "color": "#22d3ee", "emoji": "🧭",
    "persona": "You coordinate the other teammates…", "projectId": null,
    "model": null, "createdAt": "…", "updatedAt": "…",
    "lastMessage": "…", "lastMessageAt": "…" }
]}
```

- Threads live at `SESSIONS_DIR/teammate-<id>.json`, reusing the session shape (`src/sessions.mjs:8`).
- First run seeds a `Chief` teammate plus a `New agent` placeholder, matching the reference UI.
- Persona → `config.systemExtra`; name → `config.agentName`.
- Cross-teammate delegation is **out of v1**.

---

## 7. Renderer (React)

- **Layout:** fixed 260px `Sidebar` + fluid `ChatPane`.
- **Sidebar:** title strip; search field; `+` new teammate; `TeammateRow` list = colored avatar
  tile + name + one-line last-message preview + relative timestamp + unread dot; footer with
  model pill (settings in phase 2).
- **ChatPane header:** teammate avatar + name, `ModelPicker`, `…` menu (rename/clear/delete).
- **Transcript:** `Message` (user simple/right, assistant left with avatar), streaming assistant
  text with caret; `Thinking` animated-dots row; `ToolCallCard` (collapsible args + result,
  error styling); `ApprovalDialog` modal (Allow once / Always / Deny, showing `detail`).
- **Composer:** auto-grow textarea, Enter=send / Shift+Enter=newline, Stop button while running.
- **Markdown:** `src/markdown.mjs` renders ANSI, not HTML, so the renderer adds `marked` +
  `dompurify` (or `react-markdown` + `remark-gfm`); sanitize before injecting. Desktop-only deps.
- Dark "classic" theme via CSS variables.

---

## 8. Window / chrome (`window-chrome.mjs`)

- Frameless: `titleBarStyle: "hiddenInset"` on macOS; `frame: false` with renderer-drawn
  traffic lights on Windows; native frame on Linux. Keep a native-frame fallback toggle.

---

## 9. Small engine refactors (keep CLI + desktop DRY)

1. **`src/bootstrap.mjs`** — extract client/tool-client/model bootstrap from `cli.mjs`
   (~`cli.mjs:436-530`) into `createSession({ config, opts })` returning
   `{ client, tool, models, model, provider }`. Both `cli.mjs` and `engine.mjs` call it.
2. **`deviceLogin()` callback variant** — `src/auth.mjs` currently prints the device code to
   the console. Add `onDeviceCode({ user_code, verification_uri })` so the desktop can render it.
3. **`loadConfig` cwd independence** — desktop passes an explicit `envPath`, so a packaged app
   does not depend on `process.cwd()` (`src/config.mjs:161`).
4. No changes to `Agent`, tools, MCP, or Composio.

---

## 10. Build / tooling

- Scripts (root `package.json`): `desktop:dev` (Vite dev server + Electron), `desktop:build`
  (Vite build), `desktop:start` (Electron on built assets).
- TypeScript for the renderer + `desktop/shared/wire.ts`. Electron main stays plain `.mjs`.
- Electron ≥ 28 for ESM main support.
- Vite builds to `desktop/renderer/dist`; Electron loads it via `loadFile`.

---

## 11. Testing

- `node --test` for pure engine modules: `teammates.mjs` (CRUD, atomic writes),
  `approvals.mjs` (request→settle, always→autoApprove), event mapping in `engine.mjs` with a
  stub Agent, and `bootstrap.mjs` with a stub client.
- Renderer: optional Vitest + Testing Library (Sidebar rendering, streaming reducer,
  approval dialog).
- Manual: `desktop:dev`; run a tool turn, approve/deny, switch teammates, restart and confirm
  thread persistence.

---

## 12. Phases

1. **Scaffold** — root devDeps, `desktop/` layout, Vite+React+TS build, blank frameless window,
   CSP, preload bridge.
2. **Engine** — `bootstrap.mjs` extraction, `engine.mjs`, `teammates.mjs`, `approvals.mjs` +
   tests; IPC router.
3. **Chat UI** — sidebar, teammate CRUD, transcript, streaming, composer, markdown, model picker.
4. **Tools + approvals** — tool cards, approval dialog, cancel; connect MCP/Composio at startup.
5. **Polish** — chrome/theming, empty states, keyboard shortcuts, error surfaces.
6. *(later)* Settings + MCP/Composio UI; daemon/tray + notifications; electron-builder NSIS + updater.

---

## 13. Risks / open items

- **Packaging the engine:** include `src/` and `tools/` in the electron-builder `files`; they live
  outside `desktop/`. Engine is zero-dep, so no runtime `node_modules` needed.
- **Streaming markdown performance:** batch deltas per animation frame.
- **Device-login UX** is required before the first run on a fresh machine (§9.2).
- **Approval bridge races:** settle/cancel cleanly if a turn is cancelled while a prompt is open,
  mirroring `daemon.pending` (`src/daemon.mjs:194-227`).
- **Tool startup latency** (npx pulls): show "connecting tools…", never block the window.
- **Root `main` field change** for Electron — confirm acceptable (alt: `desktop/` sub-package).
