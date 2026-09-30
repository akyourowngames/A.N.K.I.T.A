# Ankita implementation plan: Secret Scrubber + Ctrl+K Command Palette

Date: 2026-09-28. Source: idea drops (secret scrubber, command palette). Ship scrubber first — it's security; palette second — it's polish.

---

## Feature 1 — Secret scrubber

**Problem.** Credentials moved to the OS keychain, but the moment anyone pastes an API key, token, or password into chat, it lands in plaintext in chat history, job run logs, and exports. The keychain protects stored secrets; nothing protects *transient* ones.

**Goal.** No secret ever persists in plaintext. Anywhere Ankita writes text that a human (or a log file) can later read, secrets come out as `[REDACTED:<type>]`.

### Design

**Core module:** `src/security/secretScrubber.ts` (main process; exposed to renderer through preload as a read-only `redact()` — never the raw patterns list, minor obfuscation, not real security).

- `detect(text) → Array<{type, start, end}>` — finds candidate secrets.
- `redact(text) → string` — replaces each with `[REDACTED:<type>]`, e.g. `[REDACTED:github_token]`, `[REDACTED:generic_password]`.
- `containsSecret(text) → boolean` — cheap pre-check for hot paths.

**Detection = patterns + context, not just regex.** Two layers:

1. Shaped patterns (high confidence): AWS keys (`AKIA…`), GitHub `ghp_/gho_`, Slack `xox…`, Stripe `sk_live_…`, generic PEM blocks (`-----BEGIN … PRIVATE KEY-----`), `Bearer <token>`, connection strings.
2. Label-adjacent values (medium confidence): `api_key`, `apikey`, `token`, `secret`, `password`, `passwd`, `pwd` followed by `= : " '` and a value with length ≥ 12 and high entropy (Shannon > 4.2). This catches `OPENAI_API_KEY=sk-…` pasted from a `.env`.

Deliberately **no ML classifier** — deterministic, auditable, fast (<1 ms per message on typical lengths).

**Where redaction is enforced (defense in depth — every write path, not just chat):**

| # | Write path | Hook |
|---|---|---|
| 1 | Chat history persistence | Scrub on write to the history store. The in-memory turn keeps the raw value so the assistant can still *use* it (e.g. call an API); what gets saved is redacted. |
| 2 | Job run logs / transcripts | Scrub each log line before append. Includes scheduled-job output and the background-jobs runner transcripts. |
| 3 | Exports (markdown / JSON) | Scrub at export time too — belt and suspenders, in case an old unscrubbed record exists. |
| 4 | Tool outputs before logging | A tool returning `{"token": "abc…"}` gets its logged copy scrubbed. The live value in the turn is untouched. |
| 5 | Error reports / crash dumps | Scrub stack traces and context blobs before writing. |

**The paste-with-intent case.** If the user pastes a key *meaning* to save it ("save this as my OpenAI key"), redacting it into oblivion is wrong. Handle it:

- When `containsSecret()` fires on a user message, check for save/store intent (keywords: save, store, remember, use this key).
- If intent found: route the raw value to the OS keychain under a derived name (`openai-api-key`), and replace it in history with `[STORED:keychain:openai-api-key]`.
- If no intent: plain `[REDACTED:<type>]`.
- This makes the keychain the *only* place a raw secret rests, which was the original design goal.

**Escape hatches (keep them narrow):**

- Settings toggle: "Secret scrubbing" on/off (default on). Turning it off shows a one-time warning.
- Per-value allowlist is a **no** — allowlists become the hole. If someone needs a fake key in docs, they write it in a code block labeled `example`… which the label-adjacent detector will still catch. Accept that; false positives on *examples* are the safe direction. Document it.

### Edge cases

- **Multiline secrets** (PEM blocks, JSON service-account files): patterns must span lines — operate on the full text, not line-by-line.
- **Secrets split across messages**: out of scope for v1; note as a known limitation. (Mitigation later: short rolling buffer.)
- **False positives in code discussions**: `password = "hunter2"` in example code gets redacted. Safe direction — document it, don't "fix" it.
- **Performance**: single pass, compiled regexes, early exit via `containsSecret`. No per-keystroke work in the renderer; scrub on persist, not on render.
- **Existing history**: one-time migration on upgrade — run `redact()` over stored history, logs, and exports at first launch after update. Log how many redactions were applied.

### Implementation steps

1. `src/security/secretScrubber.ts` — patterns, entropy check, `detect`/`redact`/`containsSecret`.
2. Unit tests — fixture corpus of ~50 real-shaped fake secrets (every supported type + adversarial variants: no spaces around `=`, URL-encoded, base64-wrapped). Assert zero misses on shaped patterns; assert labeled high-entropy values caught; record false-positive rate on a sample of normal chat.
3. Wire into history store write path.
4. Wire into job logger + background-jobs transcript writer.
5. Wire into export routines.
6. Wire into tool-output logging.
7. Paste-with-intent → keychain routing (+ `[STORED:keychain:<name>]` placeholder format).
8. Settings toggle + first-launch migration over existing data.
9. Docs: security section in README/CONTRIBUTING; contributor note that tests must include a redaction case for any new secret-adjacent feature.

**Done when:** pasting a `ghp_` token, an AWS key, a PEM block, and `api_key=<high-entropy>` into chat leaves zero plaintext in history file, job log, or exported markdown; the keychain-routing path stores and references correctly; test suite passes.

---

## Feature 2 — Ctrl+K command palette

**Problem.** The plugin/skill system is powerful but invisible — you have to *remember* what exists to use it. A command palette turns it into something you *discover*.

**Goal.** One search box: type a few letters, see every matching skill, command, and scheduled job, hit Enter to run it.

### Design

**Trigger:** `Ctrl+K` (Linux/Windows) / `Cmd+K` (macOS). Registered at window level (not `globalShortcut` — palette is in-app, not system-wide; avoids conflicts with other apps). Also clickable from the title bar for discoverability.

**Index sources** — everything is an entry `{id, title, hint, source, keywords[], run}`:

1. **Installed skills** — from the plugin registry: name, description, plus each skill's declared actions if the manifest lists them.
2. **Commands** — slash commands and built-in app commands (new chat, open settings, export chat, check for updates…).
3. **Scheduled jobs** — from the job scheduler: name + schedule summary; Enter offers "Run now" (and a submenu for enable/disable — keep v1 to run-now to limit scope).
4. **Recent actions** (v1.5, not v1) — skip initially; note it.

**Plugin contribution API** (this is the part that makes it compound): plugins declare palette entries in their manifest:

```json
"palette": [
  {"id": "remind-in-10", "title": "Remind me in 10 minutes", "hint": "creates a one-shot reminder job", "keywords": ["reminder", "alarm"]}
]
```

Entries without a manifest section fall back to `<skill name> — <description>`. Document this in CONTRIBUTING so every new skill is palette-visible from day one.

**Search & ranking:**

- Fuzzy match (subsequence + word-boundary bonus). No dependency — ~40 lines, or `fuse.js` if already in the tree. Check first; don't add a dep for 40 lines.
- Ranking: exact prefix > word-boundary > fuzzy; title matches outrank keyword matches; skills/commands/jobs grouped with small source badges.
- Debounce input at ~80 ms; index built once at startup, rebuilt on plugin install/uninstall/enable.

**UI:**

- Floating centered modal, dark-blur backdrop, input on top, results list below (max ~9 visible, scrollable).
- Full keyboard flow: type to filter, ↑/↓ to move, Enter to run, Esc to close. Mouse click works too.
- Each row: icon, title, one-line hint/description, source badge (`skill` / `command` / `job`), and for jobs the next-run time.
- Running a job from the palette goes through the normal approval path — palette is a *launcher*, not a bypass. (Important given the background-jobs approval model.)

### Implementation steps

1. `src/palette/index.ts` — index builder reading plugin registry + command registry + job scheduler; `search(query)` with fuzzy matching + ranking.
2. Manifest schema extension: `palette[]` entries; validation at plugin load.
3. Renderer: `PaletteModal` component + window-level `Ctrl+K`/`Cmd+K` listener + IPC (`palette:query`, `palette:run`).
4. Main-process handlers: execute command / trigger skill action / run-now a job (through existing paths, approvals intact).
5. Index refresh hooks on plugin lifecycle events.
6. Tests: index contains every installed skill/command/job (completeness test against registries); keyboard flow test (open → type → enter runs correct entry); manifest validation rejects bad palette entries.
7. CONTRIBUTING: one paragraph — "every skill should declare palette entries."

**Done when:** Ctrl+K opens the palette; typing `rem` surfaces the reminder skill and any reminder jobs; Enter runs the selected entry through the normal path; a newly installed plugin's entries appear without restart.

---

## Rollout order & milestones

1. **Scrubber core + tests** (security first).
2. **Scrubber wired into all five write paths + keychain routing + migration.**
3. **Palette index + modal + shortcut.**
4. **Palette plugin-manifest API + docs.**
5. Both behind no flags — they're additive — but the scrubber's first-launch migration must be idempotent (re-running it changes nothing).

## Open questions for Krish

1. Scrubber: when a secret is pasted *without* save intent, should Ankita warn the user ("I redacted an API key from history") or stay silent? (Suggest: one subtle notice per session, not per message.)
2. Palette: should `Ctrl+K` also work when a modal/dialog is open, or only on the main window? (Suggest: main window only for v1.)
3. Either feature: anything here you want cut for a smaller v1?
