# Composio Direct-MCP — implementation ledger

Date: 2026-09-30, updated 2026-10-01. Source: the Composio Direct-MCP plan (kill
the broker, keep the safety). **P0 + P1 landed**; the P1 live round trip against a
real Composio account is still outstanding (see "Not implemented").

## What landed

### The hole being fixed

`McpManager.needsApproval()` was:

```js
return found ? !found.record.trusted && needsApprovalFor(found.tool) : false;
```

`ensureComposio()` connects with `trusted: true`, so **every** Composio tool —
including a Gmail send — skipped the gate. `tools/connectors/composio.mjs` also
declared a blanket `needsApproval = false` with the description "Connected app
actions run without an approval prompt." Two independent blanket bypasses.

### Approval tiers (`src/integrations/mcp-tiers.mjs`, new)

- `TIER_AUTO` 0 read-only · `TIER_ASK` 1 default · `TIER_ALWAYS` 2 destructive ·
  `TIER_DENY` 3 explicit blocklist only.
- Resolution order: blocklist → explicit per-tool rule → per-app rule → locked app
  defaults → heuristic. Heuristics can never deny; tier 3 requires a blocklist entry.
- Destructive heuristic is a substring match (`/send|delete|publish|pay|transfer|remove|destroy|revoke/i`),
  so `payment` and `resend` classify correctly. A false positive only costs a prompt.
- **Meta-tool parsing (§4a):** `COMPOSIO_MULTI_EXECUTE_TOOL` is classified by the worst
  action it encloses; `COMPOSIO_SEARCH_TOOLS` / `COMPOSIO_GET_TOOL_SCHEMAS` are tier 0;
  `COMPOSIO_MANAGE_CONNECTIONS` is ask-once for `add` and always-ask for `remove`.
- `describeCall()` produces `gmail: send email` — a meta-tool name is never shown to
  the user, and `approvalDetail()` no longer appends the raw tool name either.
- Locked default per the plan: `composio` ships with `app:gmail → tier 2`, so every
  Gmail action (including a read) starts at always-ask. Coarser than per-verb, chosen
  because mail is the highest-regret app.
- `TierPolicy` persists overrides, blocklist and decision counters to
  `MCP_TIERS_FILE` (`CONFIG_DIR/mcp-tiers.json`).

### Enforcement

- `McpManager.tierFor(fullName, args)` returns the decision; `needsApproval(fullName, args)`
  now consults it and **no longer reads `record.trusted`** — that flag vets the server
  connection, not its actions.
- `McpManager.recordTierDecision()` counts allowed/denied. Auto-allowed calls are not
  counted, so a read-heavy loop does not write the policy file per call.
- `agent.mjs` passes arguments to the gate, refuses tier 3 with an explicit message, and
  records the outcome.
- `tools/connectors/composio.mjs`: description corrected; `needsApproval` is now a
  function that is `true` for `allow`/`always`/`deny` and `false` for management
  (`status`, `list`, `accounts`, `search`, `connect`, `disconnect`, `reload`). This is
  the §4 management/execution split: a model must not be able to grant itself tier 0 on
  Gmail. New actions: `tiers`, `allow`, `always`, `deny`.

### Deviation from the plan text

The plan stores tiers in "the MCP store record". They are stored in a separate file
instead: `composio` is a synthetic connection that never appears in `mcp.json`, and
adding a command-less record there would make `reconcile()` try to spawn a process that
does not exist. A separate file keeps the policy generic across every MCP server.

## Evidence

Reproduce-then-fix, using the real manager and a real HTTP MCP transport:

- **RED** (old `needsApproval` restored):
  `✖ a trusted server no longer skips the approval gate — AssertionError: sending mail
  through a trusted server must still ask. actual: false, expected: true`
  `✖ a destructive app action over a live MCP transport is gated; discovery is not —
  AssertionError: sending mail is gated even though the server is trusted. actual: false`
  → `pass 17, fail 2`.
- **GREEN** (fix restored): `tests 19, pass 19, fail 0`.
- New `test/integrations/mcp-tiers.test.mjs`: 14 tests — heuristic matrix, meta-tool
  worst-action, meta-tool name never surfaced, rule precedence, blocklist-only denial,
  locked Gmail default, persistence/counters, malformed-file fallback, protection-lowering
  detection.
- New assertion in `test/integrations/composio-http.test.mjs` exercises a live JSON-RPC/HTTP
  MCP server: discovery ungated, send gated, card reads `gmail: send email`, transport call
  still returns `done`.
- §9 guard: RED `actual: 'app:gmail is now tier 0 (auto-allow).'` → GREEN (see §9 above).
- Deprecation: `test/integrations/composio-deprecation.test.mjs` (4 tests) and
  `neverAutoApprove` assertions in `test/core/background-worker-policy.test.mjs` (3 tests).
- Final full suite (P0): `tests 873, pass 872, fail 0, skipped 1`. The skip is the existing
  POSIX-executable check on Windows. An earlier run showed one failure in
  `test/tools/git-process.test.mjs` ("kill refuses a new owner on an approved port",
  `Error: Cannot verify process PID 12260`); it passes 10/10 in isolation and passed in
  the final run, so it is an environment/timing flake in the process-ownership harness,
  unrelated to MCP.
- Updated, not deleted: `composio-http.test.mjs` asserted `composioTool.needsApproval === false`,
  which is now a function. Replaced with the management/execution split assertions.

Live Composio traffic was **not** used — the OAuth endpoint needs real credentials. Every
transport check above runs against a local stub over the real MCP HTTP/SSE client.

After P1, the full suite is `tests 886, pass 885, fail 0, skipped 1`.

### §9 background jobs — corrected assessment

An earlier version of this document claimed "a scheduled job can still send mail
unattended". **That was wrong.** `DesktopScheduler.execute()` builds the worker with
`allowedTools: JOB_TOOLS`, and `JOB_TOOLS` contains no `mcp__*` entry, so
`Agent.runToolCall()` rejects every MCP execution tool before approval or execution:
`test/core/background-worker-policy.test.mjs` asserts exactly this
(`"background tool policy rejects shell and external MCP before approval or execution"`,
`mcp__external__browser_click` → `/not available.*background/i`, `called === 0`).
A scheduled job could not reach `mcp__composio__…` in the first place.

The residual hole was narrower and real: the `composio` **management** tool *is* in
`JOB_TOOLS`, and `agent.autoApprove === true` skips the approval gate, so a job could
call `allow`/`always` to persist a lower tier that then applied to every later
interactive session. Closed with `neverAutoApprove` on the tool plus a guard in the
non-MCP approval path.

Reproduce-then-fix:

- **RED** (guard removed): `✖ auto-approve cannot loosen approval settings from an
  unattended job — actual: 'app:gmail is now tier 0 (auto-allow).'` — the job granted
  itself tier 0 and the change persisted.
- **GREEN** (guard restored): the call returns
  `Error: composio can change approval settings, which auto-approve is not allowed to do.`
  and `policy.appTierFor('composio','gmail')` stays `null`.
- Positive controls: an interactive chat with `confirm: () => true` still sets the tier
  (`tier 2 (always ask)`), and a denial leaves it untouched.

### P2 deprecation banner

`src/integrations/composio-deprecation.mjs` derives the removal version from
`package.json` (`nextMinor('2.4.4') → '2.5.0'`) rather than hardcoding it, and the
`composio status` action appends a notice naming the exact variable to replace
(`COMPOSIO_API_KEY` / `COMPOSIO_BROKER_URL`). Nothing is announced for a mode that
is not deprecated.

The notice deliberately does **not** say "run action=connect to switch" - an early
draft did, which was wrong. `connect` still goes through the REST `authorize()`
path and `projectHeaders()` throws unless the key starts with `ak_`, so there is no
keyless route to send the user to until P1 lands. The wording tells them to keep
their key, and a test asserts the notice never mentions a switch that does not
exist.

### P1 OAuth connect flow (`src/integrations/composio-oauth.mjs`, new)

**Nothing needs to be hosted.** The flow is OAuth 2.1 + PKCE (RFC 8252) with a
single-use **loopback** redirect: the app binds `http://127.0.0.1:<port>/callback`,
opens the system browser to Composio, and reads the one redirect. There is no public
callback, domain, certificate, tunnel or broker.

- `createPkce()` — S256, verifier 43–128 chars, `base64url`.
- `discover()` / `registerClient()` — RFC 8414 + RFC 7591 dynamic client
  registration as a **public client** (`token_endpoint_auth_method: 'none'`, no secret).
- `startLoopbackCallback()` — binds `127.0.0.1` on `PREFERRED_PORT` (5757), falls back
  to an ephemeral port on `EADDRINUSE`, validates `state`, serves a single-use result page.
- `assertTrustedEndpoint()` — https only, on `composio.dev` / `*.composio.dev`; loopback
  is opt-in only. Rejects embedded credentials and the `composio.dev.evil.example` spoof.
- `ComposioGrantStore` — the grant **metadata** file holds no secret: no token, no
  verifier, no refresh token. The access token lives only in `SecureStore` under
  `composio-grant-<id>`, reachable only inside `withSecret()`. `revoke()` deletes both.
- `src/integrations/composio.mjs#oauthEndpoint({ grants, secrets })` returns the live
  endpoint + `Authorization: Bearer` header, or `null` with no grant.
- `McpManager.ensureComposio(config, store, fetchImpl, oauth)` prefers a signed-in
  grant over leftover REST config, and `useComposioOauth(oauth)` lets the host inject
  the vault + browser.
- Real-composio signature correction: the MCP endpoint rejects `ak_`/`uak_`/
  `x-consumer-api-key` with 401; only an OAuth-minted Bearer works, which is why the
  keyless path had to exist before this could be verified.

**Live discovery check (2026-10-01).** The public metadata was fetched from the real
server, no account needed:

- `https://connect.composio.dev/.well-known/oauth-protected-resource` →
  `authorization_servers: ["https://connect.composio.dev"]`, `bearer_methods_supported: ["header"]`.
- `https://connect.composio.dev/.well-known/oauth-authorization-server` →
  `authorization_endpoint: https://connect.composio.dev/oauth/authorize`,
  `token_endpoint: https://login.composio.dev/oauth2/token`,
  `registration_endpoint: https://login.composio.dev/oauth2/register`,
  `code_challenge_methods_supported: ["S256"]`,
  `token_endpoint_auth_methods_supported: ["none"]`,
  `grant_types_supported: ["authorization_code", "refresh_token"]`.

This confirms every assumption the flow makes: **dynamic client registration is
supported**, public clients (`none`) are accepted and S256 is the only challenge
method. It also surfaces a host detail the allowlist must tolerate — the token and
registration endpoints live on the **sibling host `login.composio.dev`**, not on
`connect.composio.dev`. `assertTrustedEndpoint` already accepts `*.composio.dev`, so
this passes; a regression test pins the real shape so a future tightening of the
allowlist cannot silently break sign-in.

**RFC 8707 fix found by this check.** Reviewing the flow against the MCP authorization
spec surfaced a real bug: the spec **requires** clients to send the `resource`
indicator (the MCP server URL) in *both* the authorization and the token request, and
servers reject tokens whose audience was not bound this way. The first implementation
sent neither, so a live sign-in would likely have 400'd at the token endpoint.
`buildAuthorizeUrl` and `exchangeCode` now take `resource`, and `connectComposio`
sets it to the asserted MCP endpoint. The stub authorization server now rejects a
token request whose `resource` is missing or does not match the authorize request,
so the parameter cannot regress.

Reproduce-then-fix (resource param):

- **RED** (`resource` removed from both requests): `✖ a keyless user signs in through
  the browser and the token stays in the vault`, `✖ the authorize and token requests
  both carry the RFC 8707 resource indicator` → `pass 10, fail 2`.
- **GREEN** (restored): `tests 12, pass 12, fail 0`.

Evidence (`test/integrations/composio-oauth.test.mjs`, 12 tests, all green): a stub
authorization server **over real HTTP** that recomputes PKCE S256 from the verifier,
so a wrong verifier cannot mint a token; the browser step is scripted. Covers keyless
sign-in, token-only-in-vault (the grant file is asserted to contain neither the token
nor `code_verifier` nor `refresh`), a grant mounting MCP over Bearer with no key
anywhere, revoke, wrong-state refusal (400, nothing written), denied authorization,
the endpoint allowlist, PKCE well-formedness, the RFC 8707 resource indicator in both
requests, a PKCE-mismatch error, the real Composio metadata accepted by `discover()`,
and the `composio` tool's own keyless
`action=connect` end to end (browser step driven through the real tool; token lands
in the vault, not the grant file). The connector test is a regression test: with the
keyless branch disabled it fails (`✖ the connect tool signs in ... with no API key`),
and passes with it restored.

`test/desktop/desktop.test.mjs` adds an **engine-wiring integration test**: a real
`DesktopEngine` (not a stubbed manager) is built with an injected vault, then a token
is saved through `engine.secureStore`, a grant recorded, and
`engine.mcp.ensureComposio(...)` mounts a live local MCP server over
`Authorization: Bearer`. It asserts the actual wiring (`engine.mcp.composioOauth`
*is* `engine.composioOauth`, same grants/secrets objects, injected `openUrl`) and that
the grant file holds no token. `init()` is deliberately not called because its
fire-and-forget `connectTools()` reconciles the developer's real `mcp.json`.

The "sending still asks" assertion initially failed (`false !== true`). Root cause was
a **test-fixture gap**: the stub advertised only `COMPOSIO_SEARCH_TOOLS`, and
`needsApproval()` returns `false` for a tool the manager does not know about
(`findTool` → null, "not connected"). Advertising `COMPOSIO_MULTI_EXECUTE_TOOL` in the
stub's `tools/list` made it pass — no product change, and the Gmail→`TIER_ALWAYS`
resolution it exercises is unchanged.

### Live verification — outstanding

The §11 live round trip needs a real Composio account, which is not available here.
Every P1 transport check above runs against a stub authorization server over real
HTTP. **The real network handshake to `connect.composio.dev` is unverified.**

## Not implemented

- **P1 live sign-in.** Discovery, DCR support, PKCE method, auth-method shape and the
  RFC 8707 resource requirement are now verified against the real metadata/spec.
  **Not yet exercised with a real account:** the dynamic registration POST, the browser
  authorize redirect, the token exchange, and the system-browser open (`openExternal`)
  in a packaged build. These need a human login, so they are the gate — the code path
  up to `openUrl` is fully tested.
- **P2 removal step — migration that deletes stored REST secrets, plus the audit view.**
  Deliberately not done now: §7 says removal lands one minor version after deprecation,
  "not in the same release", so the banner ships first and the deletion is a follow-up.
  The banner wording still tells users to keep their key; it no longer promises a
  switch that does not exist.
- **P3 — deleting the REST layer.** Same deprecation window.
- **§6 scoped credential grants** (per-grant vault scoping beyond the single token).

## Follow-up

1. **P1 live check.** Run `action=connect` on a real Composio account from the packaged
   desktop app: confirm the browser opens, the loopback callback lands, the token is
   vaulted, and a Gmail send still prompts. This is the gate before the banner can stop
   telling users to keep their key.
2. P2 removal + audit view, one minor version after the banner.
3. P3 only after that.
