# Model-selected vault controls and Telegram upgrade — implementation ledger

Date: 2026-09-27. Status: implemented; local verification complete with limits below.

## Requirements and rulings

- The user explicitly replaces detector-gated login with model-directed secure
  credential requests and requires continuation of the original task.
- Ruling: `browser login` without `credential_fields` requests credentials and
  returns a fresh snapshot, without finding a form. With fields, the model maps
  observed refs to private username/password slots and optionally selects a
  submit ref. The model judges the resulting page. This supports username-first
  flows and arbitrary button names; an incorrect model selection returns an
  attention receipt instead of automatically retrying. Cost: model decisions
  still need accurate page evidence; controls must satisfy exact-origin/type
  checks before receiving private values.
- Ruling: one-time credentials live only in the main process, scoped to the
  thread/origin/tab/page, until password use, Stop, turn end or expiry. They are
  not automatically persisted when saving is disabled. Cost: a later password
  retry may request the dialog again unless the user saved the account.
- Ruling: the Telegram plan's hourglass/check/cross emoji cannot be used as
  standard reactions. Use supported 👀/👍/👎 for received/completed/failed.
  [Official reaction list](https://core.telegram.org/bots/api#reactiontypeemoji).
  Cost: reaction appearance differs from the original plan.
- Continue in the existing working tree, retaining the earlier browser/vault
  work and unrelated user files. No release, push or installed update is part
  of this task.

## Executed evidence

- Cirro live repro: the old detector rejected `An unambiguous username and
  sign-in button are required`. Its honeypot and input-based submit make the
  heuristic unsuitable. The initial diagnostic output was truncated; the
  full snapshot confirms email/password/Sign In refs exist. No missing-control
  snapshot bug is claimed. Afterward: preparation accepted with form detection
  disabled, and snapshot reports control types. No Cirro credentials were used.
- New vault selection tests RED 0/3 -> GREEN 3/3; real Chromium selected-ref
  username-first/safety tests RED 0/2 -> GREEN 2/2. Combined vault gate 21/21.
- Telegram upgrade tests initially failed (missing reaction API, missing
  callback/desktop progress). Desktop cancellation did not finish without the
  change; the failing run was interrupted. After implementation: desktop/CLI/
  voice/reliability gate 23/23; heartbeat/containment/fallback gate 4/4.
- Approved test chat received real API requests using the existing configured
  bot. No incoming cursor or saved bot settings changed. Scripted engine/CLI
  agent, real transport: `TELEGRAM_UPGRADE_LIVE_OK` with 4 chat actions, 2 step
  messages, 4 successful reactions and 1 image upload. Cancellation suppressed
  the partial reply. Command: `node scripts/verify-telegram-upgrade.mjs <chat>`.
- Desktop build exited 0, 322 modules, 5.77 s; existing bundle-size advisory.
- First new packaged run caught a verifier parser bug: Agent appends a read-back
  advisory after tool JSON, so parsing the entire tool string produced undefined
  refs. The verifier now parses the JSON receipt line. No production selector
  fallback or website-specific route was introduced.
- A second verifier attempt exposed the repeated-call advisory before the JSON;
  receipt-line parsing now handles both prefix/suffix notices. The affected
  screenshot test also caught schema growth dropping attached pixels from the
  default context. Compact descriptions fixed it; the same test returned green.
- Fresh-context review found four Important issues: cross-chat artifact capture,
  CLI cancel during startup, malformed selection display, and password retention
  after a partial fill. All four received observed failing regressions followed
  by green execution. Desktop captures tool receipts from owned events; CLI
  guards cancellation after preparation awaits; display is defensive; password
  consumption clears the record immediately. No Critical/Minor findings were
  reported. The reviewer did not independently judge live/package/platform
  execution; those limits are stated below. No second review was substituted for
  regression tests.
- Final affected gate: 74/74 pass, 0 fail, 0 skip, 30440.6514 ms. Build: exit 0,
  322 modules, 9.61 s, existing bundle-size advisory.
- Fresh packaged Windows app passed request -> secure dialog -> model-selected
  refs -> fill/submit -> read-back -> original task completion, including the
  actual public practice website and visible Log out. Cold/warm, cancel/Stop,
  model-requested retry, takeover/hand-back, corrupt vault and managed routing
  passed; model/events/config contain no fixture password; zero renderer errors.
  `BROWSER_VAULT_PACKAGED_OK`: artifacts/package at
  `C:\Users\anime\AppData\Local\Temp\ankita-packaged-vault-k2IhF1`.
- Real Telegram check rerun after ownership/cancel fixes: unchanged success
  counts (4 actions, 2 beats, 4 reactions, 1 image), zero cursor/settings changes.
- Final both-backend live run: `BROWSER_AUTOMATION_LIVE_OK`; isolated preview
  9.2 FPS / 15 distinct frames, Stop 3 ms and queue release 123 ms; Chrome local
  preview 4.8 FPS / 15 distinct frames, Stop 20 ms and queue release 2251 ms.
  Reconnect on demand, disabled-Chrome fallback and real control actions passed.
- Literal review inspected added production lines and the new broker/progress
  modules: timing, file/count limits and endpoint defaults are named constants;
  slot names, input types and API keys are protocol invariants. Website/account
  fixtures stay in verification scripts/tests; no production website matching
  or machine-specific launch assumptions were introduced by this follow-up.
- Final isolated `rtk npm test`: exit 0; 753 tests, 752 passed, 0 failed,
  0 cancelled, 1 skipped, 293065.7794 ms. The focused gate remains 74/74.

## Final gates

- Affected tests, both real browser backends, real Telegram transport, fresh
  packaged Windows public login and full suite executed successfully.
- Literal review and `git diff --check` passed; detailed residual limits follow.

## Limits

Public practice credentials are published dummy credentials, not a personal
account. Cirro discovery is read-only. X refusal/CAPTCHA and personal accounts,
macOS/Linux native vaults, installed auto-update and a real model's decisions
remain outside this local scripted verification. Incoming Telegram files and
reactions are deferred as the plan specifies.
Real inbound Telegram polling and group topics were not exercised against the
configured bot. Voice regression tests passed, but real voice transcription/TTS
and desktop cancellation during pre-turn transcription were not live-tested.
