# Browser credential vault ("Secure store") — deep plan

Date: 2026-09-26. Status: implemented 2026-09-27; original design preserved below.
Locked scope: OS keychain, explicit login action, Playwright (isolated) only.

The user superseded the detector-gated login design on 2026-09-27. The current
flow requests credentials independently of form detection, lets the model choose
private credential-slot refs, supports username-first steps and returns control
to the model for page verification/task continuation. See
[the latest ledger](vault-model-selection-telegram-implementation.md) and
[findings Part K](../browser-screenshot-findings.md#part-k--model-selected-credentials-and-telegram-upgrade-2026-09-27).
The original proposal below is historical, not the current selection contract.

Implementation rulings and executed verification are recorded in
[the ledger](browser-packaged-vault-implementation.md) and
[browser findings](../browser-screenshot-findings.md). Actual login pages are
used rather than invented routes; positive logout evidence is required, with
manual takeover for unsupported widgets. Secrets use transient DOM inputs and
main-process callbacks; JavaScript strings cannot guarantee memory zeroing.

## 1. Goal

A "Secure store" chat card with an Add button opens a "Secure credentials store"
modal (Website / Username / Password + "Save to secure credentials store"
checkbox + Cancel / Enter). The agent fills saved logins into the Playwright
browser via an explicit login step, without the password ever appearing in
chat, approvals, logs, or tool history.

## 2. Key decision: safeStorage, not keytar

`keytar` is unmaintained since Dec 2022 (atom/node-keytar#482); VS Code
migrated to Electron's built-in `safeStorage`. This plan uses
`safeStorage.encryptStringAsync` / `decryptStringAsync` (async API; the sync
API is on a deprecation path). No new npm dependency.

Platform semantics: Windows DPAPI (per-user, not per-app), macOS Keychain
(requires consistent code signing or updates re-prompt), Linux
libsecret/kwallet — with a `basic_text` fallback that is effectively
plaintext and must be refused (see §5).

## 3. Architecture

### 3.1 Vault — new `desktop/electron/secure-store.mjs` (main process only)

- Index file in `CONFIG_DIR` (e.g. `browser-credentials.json`):
  `{ id, website, username, updatedAt }` + `safeStorage`-encrypted password
  blobs. Shape mirrors `DesktopSettingsStore` / `ChannelStore`
  (`load` / `save` with tmp+rename `0600` / `validatePatch`).
- Public surface returns `hasPassword` booleans only — same pattern as
  `publicTelegram()` and `publicView()`. Renderer, agent context, channels,
  and logs never receive plaintext.
- Decrypt strictly at fill time; hold plaintext in memory for milliseconds
  and zero it after `fill_form` completes.
- `isEncryptionAvailable()` gate at startup; Linux `basic_text` refusal with
  a user-facing error ("install libsecret/kwallet").

### 3.2 IPC + request registry

- `desktop/shared/wire.ts`: new `EngineEvent`
  (`secure-store-request` / `secure-store-resolved` /
  `secure-store-changed`) + `DesktopApi` actions
  (`secureStoreList` / `save` / `remove` / `respondSecureStore`).
  Bump `IPC_CONTRACT` in `desktop/shared/version.mjs` (mandatory per header).
- `desktop/electron/main.mjs`: new `case 'secureStore*'` handlers.
  No `preload.cjs` change (generic `invoke` passthrough).
- Second `ApprovalRegistry`-style registry for credential prompts:
  agent blocks on `request(threadId, 'secure-store', website)`; modal
  resolves it. Non-desktop surfaces (Telegram/channels) auto-deny — a
  password must never route to chat text.

### 3.3 Renderer UI

- New `SecureStoreDialog.tsx`, cloned from the
  `TeammateDialog` / `ApprovalDialog` form-modal pattern:
  `modal-backdrop > form[role=dialog]` with Website (readonly), Username,
  Password (eye-toggle per `SettingsDialog.secretField`), Save checkbox,
  Cancel (quiet) + Enter (primary), `Escape → Cancel`, autofocus,
  focus-trap. Mounted beside `<ApprovalDialog/>` in `App.tsx`.
- Chat card: `ToolCallCard.tsx` gains a `secure_store` branch (same slot
  style as `browserSetupNeeded`): "Secure store / Sign in to {website}" +
  Add button → opens the dialog. State in `store.ts` parallel to
  `approvals[]`; `ChatPane` / `Message` pass `onOpenSecureStore`.
- Reused tokens only:
  `modal-backdrop, modal-symbol, dialog-actions,
  button-quiet/secondary/primary, settings-field/secret-control`.

### 3.4 Explicit login action (Playwright only)

- `tools/browser/browser.mjs`: new `action: 'login'` with
  `{ website, username? }` — schema, `needsApproval`, redacted
  `approval()` / `display()` (field counts only, never secret text).
  `pending.mjs` normalizer alias.
- `session.mjs#one()`: `login` → vault lookup by website (main-process
  call) → miss emits `secure-store-request` and waits (same abort
  semantics as takeover) → hit fills through the existing
  `PlaywrightBrowserAdapter.fill_form` path (`browserFields` refs +
  snapshot recovery), then a fresh snapshot.
- Chrome-local (`local` mode) explicitly rejects with "Playwright only in
  this tier". CLI fallback (no modal): instruct Take-control manual login.

### 3.5 Prompts + docs

- `BROWSER_HINTS` / `docs/guides/browser-use.md`: "for logins call browser
  login; never ask the user to paste passwords in chat."

## 4. Build order

1. Vault (`secure-store.mjs`) + unit tests.
2. IPC cases + contract bump + registry wiring.
3. Dialog + chat card + store events.
4. `login` action + session hook (Playwright only).
5. Prompt hint, `browser-use.md`, findings-doc update.

## 5. Security boundaries (documented, not promised away)

- Windows DPAPI: stops other users, not same-user processes.
- macOS: needs stable code signing.
- Linux `basic_text`: refuse to store, loudly.
- Renderer never holds secrets; approvals/history carry counts, not values.
- Per-machine vault; no sync. Not a password manager — a login helper.

## 6. Verification

- New `test/desktop/secure-store.test.mjs`: list never leaks password,
  Linux `basic_text` refusal, save/remove round trip (stubbed safeStorage).
- New `test/tools/browser-login.test.mjs`: login fills via stub adapter,
  missing-entry path prompts, approval text contains no secret. Both suites
  must fail without the implementation (reproduce-then-fix).
- Full `node --test` green; live round trip against a local test login
  form: cold (prompt → save → fill), warm (fill, no prompt), cancel.
- Update `docs/browser-screenshot-findings.md` with status + traces.

## 7. Worked example — "log me into github"

Cold path (nothing saved yet):

1. You say: `log me into github`. The agent resolves the `browser` tool
   and calls the explicit step `browser({ action: 'login', website:
   'github.com' })` — no typing, no password in chat.
2. Vault lookup misses. The run pauses (same wait/abort semantics as
   takeover) and a **Secure store** card appears in chat with an **Add**
   button, opening the **Secure credentials store** modal: Website
   `github.com` (readonly), empty Username / Password fields, Save checked.
3. You type once, hit **Enter**. The password goes straight to the OS
   keychain (DPAPI / Keychain / libsecret); chat history, approvals, and
   logs record only `login to github.com (2 fields, values hidden)`.
4. The agent opens `github.com/login` in the Playwright browser, snapshots
   the form, maps the username + password refs, and `fill_form`s both —
   then submits. Your keyboard is never touched; the BrowserStage preview
   shows the login landing on your account, and the agent hands back a
   fresh snapshot (`signed in as …`).

Warm path (saved): step 1 → vault hit → step 4 runs immediately, no modal,
no prompt. Stored record looks like this (password never stored here):

```json
{ "website": "github.com", "username": "you", "hasPassword": true }
```

Cancel path: `Escape` / Cancel aborts the login with `Action cancelled`,
same as denying a tool approval — nothing is stored, nothing is filled.

## 8. Auto-continue loop + card UX (the "fucking cool" part)

The save is not the end — it is the resume signal. One unbroken loop:

```
login requested → card: "Sign in to github.com" + Add
  → modal (type once, Enter, keychain encrypts)
  → card flips to filling state (spinner, "Signing you in…")
  → vault decrypts in main only → fill_form + submit in Playwright
  → fresh snapshot proves login (avatar/username visible)
  → card flips to success (check, "Signed in as you")
  → agent continues its original task with the authenticated session
```

- **Detect + continue:** after submit, the session takes a fresh snapshot
  and checks for a signed-in marker (avatar menu, account name, logout
  control). Hit → `status: ready`, agent resumes the queued work with the
  live session. Miss (wrong password, CAPTCHA, 2FA) → card flips back to
  an error state ("That didn't sign you in — wrong password or extra
  verification needed") with **Retry** (re-opens modal) and **Take control**
  (takeover so the user finishes CAPTCHA/2FA by hand, then hands back and
  the loop re-verifies). The agent never spins on retries — one fill, one
  verify, then it either continues or asks.
- **Cards (three states, one slot in the transcript):** `idle/prompt`
  (shield icon, site name, Add button) → `working` (spinner, "Signing you
  in…", no buttons) → `ready` (green check, "Signed in as {username}") or
  `error` (red, reason + Retry / Take control). Same `tool-card` tokens as
  every other tool card, so it feels native, not bolted on.
- **Keyboard rule:** the user types only in our modal, never in the
  automated page; the model never sees the password — it only sees
  `login to {site} (2 fields, values hidden)` and the post-login snapshot.
