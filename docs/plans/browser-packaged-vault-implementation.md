# Packaged Chrome and browser credential vault — implementation ledger

Date: 2026-09-27. Source plans: `chrome-local-packaged-spawn-issue.md` and
`browser-credential-vault-plan.md`. User authorized implementation and tests.

## Tasks

1. Complete: reproduce packaged MCP launch; bundle the pinned bridge; use the Electron
   Node runtime without npm, npx, system Node, or a cache dependency.
2. Complete: async OS-encrypted vault, exact-origin records, atomic persistence, prompt
   registry with cancellation and desktop-only access; regression tests.
3. Complete: explicit Playwright login: one fill/submit/verify; no secret receipts,
   snapshots or errors; retry/takeover and task continuation.
4. Complete: native themed chat card, secure input dialog, IPC contract bump, metadata
   management and event wiring; UI and packaged verification.
5. Complete: full tests, dependency audit, packaged Chrome and credential round trips,
   documentation/changelog, and fresh final review.

## Rulings and shared interfaces

- Ruling: work in the user's active checkout, preserving untracked plans and
  unrelated Telegram work. No push/release is part of this implementation.
- Ruling: the supplied plans are the approved design; no additional design
  permission is required. Track tasks here using native tools rather than the
  skill's Bash brief parser, because these plans have narrative build order.
- Ruling: passwords necessarily exist in the dialog DOM while entered; clear
  them after submit/close and never retain them in renderer application state.
  JavaScript strings cannot be reliably zeroed; clear references and zero any
  owned buffers without claiming guaranteed memory erasure.
- Ruling: preserve the explicit Playwright-only scope. Login uses the actual
  supplied/current login page and exact origin; do not invent site login URLs.
  Ambiguous forms and unverified sign-in require user review/takeover, not
  repeated automatic submission. Username metadata remains public as planned.
- Dependency check: Sonatype tools unavailable; user explicitly approved
  official npm metadata plus npm audit. Official chrome-devtools-mcp 1.10.1:
  Apache-2.0, ChromeDevTools upstream repository; pin/integrity from registry.
- Shared interface: prompt resolution supplies credentials to a main-process
  callback only. UI/agent events contain public metadata and operation status.
- Shared interface: login operation status is keyed by tool call, thread and
  request. Abort/Stop/teammate removal must resolve every pending request.

## Evidence

- Baseline: `npm test` -> 714 total, 713 pass, 0 fail, 1 skip;
  duration_ms 171714.3098. New Chrome runtime tests RED 0/2 (missing helper,
  old npx command), then Chrome-focused suite GREEN 7/7.
- Dependency fallback: `npm view chrome-devtools-mcp@1.10.1` official metadata
  and integrity pinned in lockfile; install audited 410 packages, 0 vulnerabilities.
- Vault RED 0/3 missing module, then GREEN 3/3: encrypted disk, metadata-only
  API, exact-origin lookup, clearing transient references, Linux basic_text
  refusal, sanitized crypto errors and corruption preservation.
- Login service RED 1/3 (registry pass, missing login service), then GREEN 3/3.
  Additional Stop/batch-card guards RED 3/5: old session returned ready after
  cancellation; login inside a batch could wait without a usable secure card.
- `verify-browser-automation.mjs`: bundled bridge 1.10.1; actual Playwright and
  Chrome open/fill/click/read, form fields, refs, screenshots, native interactions,
  Stop, reconnect and disabled fallback -> BROWSER_AUTOMATION_LIVE_OK.
  Preview 9.1 / 6.5 FPS, 15 distinct frames each; Stop returned 3 / 13 ms.
- Packaged round trip (pre-final build): actual Ankita.exe/app.asar, old launch
  exit 0/no initialize; fixed bridge 30 tools plus CDP page/snapshot with empty
  PATH and npm cache. Real async Windows safeStorage cold/warm login, secure
  dialog/theme/focus/password eye, original-task continuation, Escape and Stop
  checks passed. Final full-build traces will follow.
- First full post-change gate: 722 total / 719 pass / 2 fail / 1 skip.
  New prompt/schema bytes caused default-window tests to shed browser/web;
  compacted duplicate guidance without changing context limits. Browser workflow
  then passed 4/4 and tool loading 17/17. Final full gate still pending.

### Implementation rulings

- The card stays a `browser` tool call with `action:login`; secure UI state is
  held in a dedicated React provider parallel to approval state. Secrets use
  uncontrolled DOM inputs, never reducer/context state.
- The adapter uses its existing snapshot/ref resolver and fill primitive with
  bound element handles. Unlike ordinary fill_form, no secret-bearing snapshot
  or Playwright error escapes the login boundary. A positive logout control is
  required; avatar-only/ambiguous sites need manual takeover.
- Login is a separate call, not a batch step, so the secure card is actionable.
- Enabling Chrome records consent as before; launch remains on-demand or via
  Start connection, with exact-command approval. Bundling removes the cold
  install entirely; no unapproved hidden prewarming is needed.

### Final review and hardening

- One fresh whole-change review found five issues. Fixed with regressions:
  submitter formmethod/formaction overrides, policy refresh on existing pages
  and after a prompt, disabled Playwright falling back to Chrome, dropped plain
  card error text, and silent save-failure retries. Root focused gates 46/46;
  reviewer follow-up 8/8 with no remaining findings in the bounded resolution check.
- Independent live RED -> GREEN security traces:
  `passwordInServerQuery:true,passwordInTabUrl:true` -> both false;
  blocked login success/submits=1 -> blockedAtPrepare and blockedBeforeFill=true,
  submits=0,passwordFilled=false. Guarding uses the effective submitter method
  and action, not only form defaults. Live policy callbacks reload plugin rules
  before prepare/fill; route-policy cache is invalidated with the same helper
  used by normal browser calls.
- Native GET form RED: one password query; GREEN zero. SPA sign-in still works.
  Corrupt/encryption/write save failures preserve the file and offer an explicit
  non-saving retry with a generic reason; arbitrary crypto errors never escape.
- Compact prompt needed the original recovery-guidance phrase retained for its
  semantic regression; restored without increasing the default context limit.
- A packaged takeover fixture used a default browser layout coordinate; made
  its test-only button position explicit so native input verification is stable.
- New secure state is a provider rather than prop plumbing through every chat
  component. Terminal plain-text guard errors remain visible in the same card.

### Final evidence

The subsequent public-form, blank-navigation and external-MCP failures are
reproduced and corrected in [Part J of the browser findings](../browser-screenshot-findings.md#part-j--public-login-controls-blank-navigation-and-managed-routing-2026-09-27).
That section is the latest evidence; the initial controlled-form run below is
retained as the implementation history.

- `npm test`: 729 total, 728 pass, 0 fail, 1 platform skip (POSIX executable
  permission on Windows), duration_ms 232917.7214. `desktop:build` exit 0:
  322 modules, 6.37s; existing Vite bundle-size warning remains informational.
- Fresh actual executable/ASAR:
  `C:\Users\anime\AppData\Local\Temp\ankita-packaged-vault-rlJWyX\package\win-unpacked`.
  `verify-browser-vault-packaged.mjs` -> BROWSER_VAULT_PACKAGED_OK, including
  metadata UI Remove, visible local-denial reason and corrupt-file one-time retry.
- `verify-browser-desktop.mjs --package-dir <that build> --keep-artifacts` ->
  PACKAGED_DESKTOP_VERIFICATION_OK: actual 8 HTTP/SSE model rounds, screenshot
  pixels, stale-ref sidebar recovery, theme switching, collapse, takeover, Stop,
  stdin/EOF/exit code 7, worker crash ownership cleanup, installer dry-run.
- Public model requests/events/config are password-free; renderer errors zero.
  Real async Windows OS encryption passed; stub Linux/plaintext failures passed.
- `npm audit --omit=dev` 0 vulnerabilities; literal diff review complete: new
  runtime durations, schema version, permission mode, package pin, ASAR location,
  vault filename and submission ownership are named constants/config. Protocol
  keys/selectors and user-facing copy are interface/UI literals. `git diff --check`
  exit 0. Unrelated .commandcode and Telegram plan preserved, no release/push.
- Residual coverage: native macOS/Linux encryption/signing, NSIS install/update,
  personal Chrome My-session permission and real LLM/account workflows are not
  exercised. Unsupported sign-in widgets use takeover as documented.

## Sources

- [Electron environment variables](https://www.electronjs.org/docs/latest/api/environment-variables)
- [Electron safeStorage](https://www.electronjs.org/docs/latest/api/safe-storage)
- [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp)
