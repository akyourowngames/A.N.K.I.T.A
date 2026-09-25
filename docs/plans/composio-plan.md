# Composio connected apps for ankita — implementation plan

Status: implemented locally (direct project-key path, broker client, HTTP MCP, management surfaces). Live Composio verification awaits a project key; broker Worker hosting remains deferred.
Reference implementation: OpenMausBot (`C:\Users\anime\3D Objects\OpenMausBot`).

---

## 1. Goal

Give ankita the same thing OpenMausBot advertises as **Connected apps**: the user
authorizes Gmail, Slack, Notion, GitHub and hundreds more once, and the agent gets
real tools for them. Composio owns the OAuth tokens and executes the calls; ankita
only needs credentials to a Composio project and a way to surface the tools.

### Locked decisions

| Decision | Choice |
| --- | --- |
| Auth path | **Direct project key first** (`COMPOSIO_API_KEY`), **broker client ready** (`COMPOSIO_BROKER_URL` + token + auto-register). If both configured, the project key wins (same as OpenMausBot). |
| Tool exposure | **Always-on, auto-approved.** Composio's meta-tools are mounted as an always-on MCP server; its calls do not prompt. |
| Management surfaces | **`/composio` slash command AND a `composio` agent tool.** |
| Broker hosting | **Cloudflare permanent.** The broker is a Cloudflare Worker + D1, now and permanently. Client only for now; port the Worker in a later phase. |
| Transport | **Native streamable-HTTP MCP** from ankita to Composio. No stdio proxy process. |
| Dependencies | Keep **zero runtime dependencies** (hand-rolled, like the existing MCP client). |

---

## 2. Why this shape

OpenMausBot's Composio integration has two moving parts:

1. **Account/session management** against Composio's REST API (`tool_router`
   sessions, connected accounts, auth links).
2. **Tool execution** over MCP. Crucially, OpenMausBot never hands the Composio
   MCP URL to a model. It spawns a local **stdio proxy**
   (`server/connector-proxy.ts`) that relays JSON-RPC upstream with the key, then
   mounts that proxy as an MCP server named `composio`
   (`server/composio.ts:536` `mcpIntegration`, `server/drivers/chat-mcp-tools.ts:234`).

The proxy exists **only because OpenMausBot's agent drivers (Claude/Codex/ACP/Pi)
require stdio MCP servers.** ankita's `McpClient` is ankita's own code
(`src/mcp-client.mjs`), so it can speak HTTP directly. That removes the proxy, a
child process, and a whole failure surface. Everything else — the Composio
endpoints, session reuse, account inventory, connect links, revocation — is the
same.

Because Composio is mounted through ankita's existing MCP plumbing, tool naming
(`mcp__composio__COMPOSIO_*`), `find_tools` discovery, the approval gate, and the
system-prompt summaries all keep working with almost no changes.

### Data flow

```
ankita turn
  └─ Agent.currentSpecs()                     src/agent.mjs:241
       └─ McpManager.specs()                   src/mcp-manager.mjs:229
            └─ McpClient (transport: http)     src/mcp-client.mjs
                 └─ POST https://app.composio.dev/tool_router/v3/<sid>/mcp
                      headers: x-api-key: ak_…, accept: application/json, text/event-stream

/composio connect gmail
  └─ src/composio.mjs  authorize()
       └─ POST https://backend.composio.dev/api/v3.1/tool_router/session/<id>/link
            → { redirect_url }  (open in browser)
```

---

## 3. Reference: Composio REST API (direct path)

Base URLs (`server/composio.ts:9-17`):

- API: `https://backend.composio.dev/api/v3.1` (override `OMB_COMPOSIO_API`)
- Toolkits: `https://backend.composio.dev/api/v3` (override `OMB_COMPOSIO_TOOLKITS_API`)
- Auth header: `x-api-key: <project key>` (must start `ak_`)

| Purpose | Method + path | Notes |
| --- | --- | --- |
| Read session | `GET /tool_router/session/{id}` | 404 → recreate |
| Create session | `POST /tool_router/session` | body below |
| Auth configs | `GET /auth_configs?is_composio_managed=false&limit=100` | cursor paginated |
| Connected accounts | `GET /connected_accounts?limit=50&user_ids={uid}&order_by=updated_at&order_direction=desc` | cursor paginated |
| Session toolkits | `GET /tool_router/session/{id}/toolkits?limit=50&is_connected=true` | inventory |
| Connection status | `GET /tool_router/session/{id}/toolkits?limit=50&toolkits=a,b` | scoped poll |
| Connect link | `POST /tool_router/session/{id}/link` | body `{ toolkit, alias? }` → `{ redirect_url }` |
| Disconnect | `DELETE /connected_accounts/{id}?revoke_on_delete=true` | revokes upstream grant |
| Toolkit catalog | `GET /api/v3/toolkits?limit=500&sort_by=usage` | card list |
| MCP relay | `POST <session.mcp.url>` | raw JSON-RPC, `x-api-key` |

Session create body (`server/composio.ts:114-122`, `:424-483`):

```json
{
  "user_id": "ankita_<uuid>",
  "manage_connections": {
    "enable": true,
    "enable_wait_for_connections": true,
    "enable_connection_removal": true
  },
  "multi_account": {
    "enable": true,
    "max_accounts_per_toolkit": 5,
    "require_explicit_selection": true
  }
}
```

Response session shape (`server/composio.ts:19-33`):

```json
{ "session_id": "…", "mcp": { "type": "http", "url": "https://…composio.dev/tool_router/v3/…/mcp" }, "config": { … } }
```

Session reuse rules (copy these exactly):

- Reuse the stored session only if it echoes multi-account config and covers the
  project's auth configs; otherwise recreate **with the same `user_id`** so
  existing OAuth grants survive (`server/composio.ts:424-483`, `:510-530`).
- Validate every returned MCP/redirect URL is `https://*.composio.dev`
  (`server/composio.ts:140-145`, `:312-327`, `:508`).

---

## 4. Reference: broker API (managed path, client-only for now)

The broker is an HTTPS service holding one shared Composio key and a table of
installation tokens. ankita's client speaks this shape regardless of who hosts it.

| Method + path | Request | Response |
| --- | --- | --- |
| `POST /v1/installations` | `{}` (rate-limited) | `201 { installationId, token }` |
| `GET /v1/me` | Bearer | `{ installationId }` |
| `POST /v1/mcp` | raw MCP JSON-RPC | upstream MCP response + `mcp-session-id` |
| `GET /v1/catalog?cursor=` | Bearer | proxied toolkits |
| `GET /v1/connectors/connected` | Bearer | `{ configured, services }` |
| `GET /v1/connectors?services=a,b` | Bearer | `{ services }` |
| `POST /v1/connectors/{slug}/authorize` | `{ alias? }` | `{ url }` |
| `DELETE /v1/connectors/{slug}` | — | `{ removed }` |
| `DELETE /v1/connectors/{slug}/accounts/{id}` | — | `{ removed }` |

Broker auth is `authorization: Bearer <64-hex token>`; the broker stores only the
SHA-256 of the token (`cloudflare/composio-broker/src/index.ts:244-251`). On first
run, ankita registers, stores the token, and thereafter uses it.

**Hosting.** The broker is, permanently, a **Cloudflare Worker + D1** — the same
stack as the reference implementation. Cloudflare is the single supported target:
Workers for the routes, D1 for the installation table, Workers Secrets for
`COMPOSIO_API_KEY`, and Workers rate-limit bindings for registration/session
throttling. No other hosting is planned or supported. Port the Worker in a later
phase, once ankita is distributed to users who lack their own Composio key.

---

## 5. Implementation by file

### New: `src/composio.mjs`

Pure, testable backend client. Accepts an injected `fetchImpl` (repo pattern, see
`tools/mcp-manage.mjs` uses `ctx.fetchImpl`) and a config object. No I/O to disk
here — persistence lives in the store.

```js
export function connectionMode(config) // "direct" | "broker" | "unavailable"
export function projectHeaders(apiKey, json)          // x-api-key
async function ensureSession(cfg, fetchImpl)          // create/reuse, persists ids
async function mcpEndpoint(cfg, fetchImpl)            // -> { url, headers }
async function listToolkits(cfg, { query, cursor })   // catalog cards
async function connectedServices(cfg)                 // Record<slug, ServiceState>
async function authorize(cfg, slug, alias)            // -> { url }
async function removeAccount(cfg, slug, accountId)    // -> { removed }
async function removeService(cfg, slug)               // -> { removed }
export function canonicalSlug(s)                      // x -> twitter alias
```

Shapes (match OpenMausBot so the surfaces are identical):

```ts
ServiceState = { connected: boolean; pending: boolean; status: string;
                 accounts: { id: string; alias?: string; status: string }[] }
ToolkitCard  = { slug, label, blurb, logo, noAuth?, domain }
```

Rules:

- `connectionMode`: project key → `direct`; else broker URL/token → `broker`;
  else `unavailable`.
- Session create/read only for `direct`; broker keeps session server-side.
- `authorize` for broker: `POST {broker}/v1/connectors/{slug}/authorize`.
- `removeAccount`/`removeService`: prove ownership before delete; always
  `revoke_on_delete=true` on direct.
- Never log the key or token; accept-validate all Composio URLs.

### New: `src/composio-store.mjs`

Atomic JSON store mirroring `McpStore` (`src/mcp-store.mjs`): re-read before every
mutation, `writeTextFile`, tolerant load. Lives at `COMPOSIO_FILE`
(`~/.copilot-chat-cli/composio.json`).

```json
{
  "version": 1,
  "userId": "ankita_…",
  "sessionId": "…",
  "broker": { "installationId": "…", "token": "…" },
  "aliases": { "gmail": ["work", "personal"] }
}
```

The `ak_…` project key is **never** stored here — it stays in `config.env`/`.env`.

### New: `tools/composio.mjs` (agent tool)

Action-based like `tools/mcp-manage.mjs`.

- Actions: `status`, `list`, `accounts`, `search`, `connect`, `disconnect`, `reload`.
- `connect` returns the URL as text and tells the user to finish OAuth in the browser.
- `needsApproval = false` (per chosen auto-approve policy).
- `reload` asks `ctx.mcp` to reconnect the `composio` HTTP server.

### Modified: `src/mcp-client.mjs` (add HTTP transport)

Keep stdio exactly as-is; add:

- Constructor: `transport: "stdio" | "http"` (default `stdio`), plus `url`, `headers`.
- `connect()` on HTTP: no `spawn`; POST `initialize`, capture `mcp-session-id`
  response header, send `notifications/initialized`, then `refreshTools()`.
- `request()` on HTTP: POST one JSON-RPC message with
  `content-type: application/json`, `accept: application/json, text/event-stream`,
  custom headers, and `mcp-session-id` when known. Parse either a single JSON body
  **or** SSE `data:` frames, resolving the matching `id`.
- `notify()` on HTTP: POST without an `id`; do not await a reply.
- `close()` on HTTP: clear state only (no child/tree-kill).
- Timeout: keep per-request timeouts; Composio calls can be slow, so allow a
  generous `requestTimeoutMs`.

### Modified: `src/mcp-manager.mjs`

- `connect()` accepts `{ transport: "http", url, headers }`; store `url`/`headers`
  on the record instead of `command`/`args`.
- `approvalDetail()` handles HTTP records (prints the URL).
- Add `record.trusted` → `needsApproval(fullName)` returns `false` for trusted
  servers (used for the Composio server only).
- Optional `record.alwaysOn` to force inclusion regardless of token estimate.
- `reconcile()` should not try to manage the Composio server via `McpStore`
  (it is synthetic, not user-added). Add a separate `ensureComposio()` path.

### Modified: `src/config.mjs`

Add reads and defaults, plus `COMPOSIO_FILE`:

```js
export const COMPOSIO_FILE = path.join(CONFIG_DIR, "composio.json");
// ...
composioApiKey: pick("COMPOSIO_API_KEY") || "",
composioBrokerUrl: pick("COMPOSIO_BROKER_URL") || "",
composioBrokerToken: pick("COMPOSIO_BROKER_TOKEN") || "",
composioApi: pick("COMPOSIO_API") || "",              // test/override
composioToolkitsApi: pick("COMPOSIO_TOOLKITS_API") || "",
```

### Modified: `src/agent.mjs`

- One system-prompt line, **only when `composio` is connected**:
  "Connected apps (Gmail, Slack, …) are reachable through the `composio` tools:
  find one with `COMPOSIO_SEARCH_TOOLS`, read its arguments with
  `COMPOSIO_GET_TOOL_SCHEMAS`, run it with `COMPOSIO_MULTI_EXECUTE_TOOL`, and
  manage accounts with `COMPOSIO_MANAGE_CONNECTIONS`."
- No other changes needed: specs, execution, and approval all flow through the
  existing MCP path (`src/agent.mjs:241`, `:461`, `:486`).

### Modified: `src/cli.mjs`

- `/composio [status|list|accounts|search|connect|disconnect|reload]`, following the
  `/mcp` command style (`src/cli.mjs:1631`).
- Auto-connect the `composio` HTTP MCP server at startup when configured, right
  after the existing MCP reconcile (`src/cli.mjs:588-596`), then
  `agent.refreshPrompt()`.
- Teardown: `mcp.closeAll()` already covers the HTTP client.

### Modified: `src/daemon.mjs`

Reconcile/ensure the Composio connection each tick beside the MCP reconcile
(`src/daemon.mjs:634`), so daemon workers and routines see the same tools.

### Modified: `tools/catalog.mjs`

New deferred category:

```js
{
  id: "connectors",
  summary: "connected apps: Gmail, Slack, Notion, Calendar, Drive, GitHub and more",
  keywords: ["gmail","email","slack","notion","calendar","drive","sheets","docs",
             "jira","linear","asana","github","twitter","x","connected apps",
             "my email","send an email","post to slack"],
  tools: [composio],
}
```

Note: the management tool is deferred (loaded via `find_tools`, like `mcp_manage`),
while the actual Composio meta-tools are always-on through the manager. This is the
intended split.

### Modified: `tools/find-tools.mjs`

Extend the capability-gap hint to mention connected apps / `/composio connect`
alongside the MCP registry.

### Modified: `.env.example`, `README.md`

Document vars and the security note (auto-approved tools run without prompting).

---

## 6. Security

- `ak_…` key lives only in `config.env`/`.env` (the existing secret store). Broker
  token lives in `composio.json` written `0600`.
- Never log keys/tokens. Redact in errors.
- Direct: only accept `https://*.composio.dev` MCP and redirect URLs.
- Broker: only accept the configured broker origin; require `^[0-9a-f]{64}$` token.
- Auto-approve is deliberate but dangerous: Composio tools can send email, mutate
  repos, post to chat. Document this loudly; consider a future per-toolkit gate.
- Disconnect must revoke upstream (`revoke_on_delete=true`), not just hide locally.

---

## 7. Testing

`node --test` (repo script: `npm test`). Use fake `fetchImpl`; no live key needed.

- `test/composio.test.mjs`
  - `connectionMode` matrix (key / broker / none; key wins over broker).
  - Session create, reuse, and 404-recreate keeping the same `user_id`.
  - URL validation rejects non-`composio.dev`.
  - `authorize` returns/validates the redirect URL.
  - `removeAccount` proves ownership then deletes with `revoke_on_delete=true`.
  - Broker auto-registration stores `installationId`/`token` once.
- `test/composio-http.test.mjs`
  - `McpClient` HTTP transport against a stub server: JSON body framing.
  - SSE framing (`text/event-stream`) resolves the matching `id`.
  - `mcp-session-id` captured on initialize and echoed on later calls.
  - `McpManager` namespacing `mcp__composio__*`, trusted → no approval.

Manual live check (needs `COMPOSIO_API_KEY`): `/composio status` → `connect gmail`
→ finish OAuth → `COMPOSIO_MULTI_EXECUTE_TOOL` performs one benign action.

---

## 8. Phases

1. **Config + store** — `config.mjs`, `composio-store.mjs`, tests.
2. **Backend client** — `composio.mjs`, direct path, tests.
3. **HTTP MCP transport** — `mcp-client.mjs`, `mcp-manager.mjs`, tests.
4. **Mount + management** — `tools/composio.mjs`, catalog, `cli.mjs`, `daemon.mjs`.
5. **Prompt + docs** — `agent.mjs`, `.env.example`, `README.md`.
6. **Broker client** — registration + `/v1/*` in `composio.mjs` behind the same interface.
7. **Live verification** against a real Composio project key.

---

## 9. Cloudflare free-tier capacity (for the future broker)

These are Cloudflare's own published limits for the permanent broker stack
(Workers + D1).

### Published limits

| Resource | Workers Free | Workers Paid ($5/mo) |
| --- | --- | --- |
| Worker requests | **100,000 / day** | 10M/month included, then $0.30/M |
| CPU time | 10 ms / invocation | 30M CPU-ms/month, max 5 min |
| Subrequests | 50 / request | 10,000 / request |
| D1 rows read | 5,000,000 / day | 25B/month included |
| D1 rows written | **100,000 / day** | 50M/month included |
| D1 storage | 5 GB (500 MB/db, 10 db) | 5 GB + $0.75/GB-mo |
| Registration/rate limiters | 30/60s register, 120/60s per install | same shape |

Free limits reset at 00:00 UTC. Exceeding requests returns **Error 1027**;
exceeding D1 returns row-limit errors until reset.

### What one broker request costs

Per broker request (from `cloudflare/composio-broker/src/index.ts`):

- 1 Worker request.
- 1 D1 row **read** (`SELECT … WHERE token_hash = ?`, `index.ts:247`).
- 1 D1 row **write** (`UPDATE installations SET last_seen_at …`, `index.ts:234-239`,
  one per request, deferred via `waitUntil`).
- A few subrequests to Composio (not billed as requests; CPU is I/O wait).

So on the free plan the two co-binding ceilings are **100,000 Worker requests/day**
and **100,000 D1 writes/day** — both hit at ~100k broker requests/day. D1 reads (5M)
and storage are not near-binding.

### Requests per user per day (estimate)

| Usage | Broker requests/day |
| --- | --- |
| Casual (1 session, ~20 tool calls) | ~25–40 |
| Regular (a few sessions, ~100 calls) | ~150–300 |
| Heavy (many sessions, ~700 calls) | ~800–1,200 |

An MCP session handshake is ~3 requests (initialize, initialized, tools/list); each
tool call is 1; inventory/catalog refreshes add a handful.

### Resulting free-tier capacity

| User profile | Free-plan users/day (100k ceiling) |
| --- | --- |
| Light (~30 req/user/day) | **~2,500–3,300** |
| Regular (~200 req/user/day) | **~400–500** |
| Heavy (~1,000 req/user/day) | **~80–120** |
| Registered-but-idle | registration is a one-time write; storing millions of rows fits in 5 GB (rows are tiny). The cap is **daily traffic**, not registered count. |

Practical summary:

- **1–50 users:** free tier is comfortable with wide headroom.
- **~100–500 users:** viable on free if usage is light-to-regular; heavy-user
  pockets will approach the 100k/day ceiling.
- **> ~2,000 daily-active users:** move to Workers **Paid ($5/mo)**, which lifts
  requests to 10M/month (~333k/day average) and D1 to 50M writes/month.

Two optimizations that matter at scale:

1. **Stop writing `last_seen_at` on every request** (batch it, e.g. once per few
   minutes). Today the 100k D1 write cap ties the 100k request cap; removing the
   per-request write leaves requests as the sole ceiling and protects the DB.
2. **Cache `GET /v1/catalog`** (the reference sets `cache-control: max-age=600`),
   so catalog browsing doesn't burn request quota.

Note: `10 ms` CPU per invocation is tight for very large MCP payloads (parsing a
multi-hundred-KB JSON response can approach it). Most Composio calls are small, but
this is the likeliest free-tier failure mode under load.

---

## 10. Open risks

- **Composio streamable-HTTP MCP quirks.** SSE vs single-JSON framing, whether
  `tools/list` requires the initialized notification first, and session-id
  handling are designed for both framings but must be confirmed against a live key
  (phase 3/7). This is the main unknown.
- **CPU on large MCP responses** (see §9) — verify with real payloads.
- **Auto-approve blast radius** — accepted by decision, documented loudly.
- **Session drift** — always recompute `mcpEndpoint()` from the stored session and
  recreate with the same `user_id` on 404.

---

## 11. Deferred

- Porting the broker as a self-contained **Cloudflare Worker + D1** service, with
  its own tests, migrations, and `wrangler` deploy docs.
- Optional per-toolkit approval policy instead of blanket auto-approve.
- Multiple-account alias UX (Composio supports it; ankita surfaces it but doesn't
  yet enforce `require_explicit_selection`).
