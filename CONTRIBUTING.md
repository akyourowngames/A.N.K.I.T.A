# 🤝 Contributing to Ankita

Thanks for showing up — Ankita is built in the open, and every PR from a real human makes it better. This guide is short and strict. Read it once, then build.

## 🚀 Get running in 5 minutes

**Prereqs:** Node.js 20.19+, 22.12+, or 23+ for CLI work; Node.js 22.12+ for desktop work. The exact supported ranges are in `package.json`.

```bash
git clone https://github.com/<your-username>/A.N.K.I.T.A.git
cd A.N.K.I.T.A
npm ci
cp .env.example .env        # fill in the keys you need
node node_modules/playwright/cli.js install chromium # real browser regression runtime
npm test                    # must be green BEFORE you change anything
npm link                    # `ankita` now works from any folder
ankita                      # talk to it
```

🆘 **Stuck on setup?** Open an issue with the `question` label. Setup friction is a bug — your report helps the next person.

## 🎯 Picking something to work on

1. Start with [`good first issue`](https://github.com/akyourowngames/A.N.K.I.T.A/labels/good%20first%20issue) — small, scoped, no deep context needed.
2. 💬 Comment "I'd like to work on this" so two people don't duplicate effort.
3. Found something broken with no issue? File one first (bug report template), then fix it. No drive-by PRs without an issue.

## 📏 The rules (strict)

### 1. 📖 Read AGENTS.md before your first PR
It defines this repo's operating rules: **no hardcoding** (no magic strings, paths, ports, model names, or OS assumptions inline — hoist to config/constants), and the review gate (grep your own diff for literals you introduced).

### 2. ✅ Nothing is done until it runs
After implementing, you **must**:
- Run the focused test: `node --test <test-file>`
- Run the full suite: `npm test` — green, no exceptions
- Do a **live round trip** of the changed path (not just a typecheck, not just re-reading your code)

A PR with no verification evidence gets closed. Say what you ran and what the result was in the PR body.

### 3. 🧪 Tests are mandatory for behavior changes
- New behavior → new test. Changed behavior → updated test.
- Tests live in `test/`, grouped by subsystem, using Node's built-in runner.
- If you genuinely can't test something, say why in the PR — "couldn't test" without a reason is a rejection.

### 4. 📦 Small PRs only
- **One issue per PR.** No kitchen sinks.
- Keep diffs focused. If your PR touches 15 files, split it.
- `write_file` for new files, `edit_file` for existing, `apply_patch` for multi-file changes.

### 5. 🚫 Keep dependencies deliberate
Prefer Node built-ins. The runtime already declares Playwright, the Chrome bridge
and Electron's updater; adding another dependency needs a clear reason and review.
Keep `package.json` and `package-lock.json` consistent. Do not mix dependency
upgrades into an unrelated fix.

### 6. 🔒 Security is not optional
- Never commit `.env`, tokens, keys, or credentials. Ever.
- Credential **names** in code/config, never values.
- File tools stay in the workspace; web tools never touch private hosts. If your change touches auth, secrets, or network access, call it out explicitly in the PR.

### 7. 🎨 UI changes need proof
- Desktop (Electron/React) changes → include a screenshot or short screen recording.
- Follow the existing component patterns in `desktop/renderer/src/components/`.
- Keep screenshots and recordings in temporary evidence folders or attach them
  to the PR. Do not commit `.commandcode/`, `launch-video/`, generated media,
  crash dumps or release executables. Preserve source fixtures and app assets.

### 8. 💬 Communicate like a maintainer
- Link the issue: `Fixes #123`.
- Describe **what** changed and **why**, not just what.
- Respond to review comments within a few days or the PR may be closed for staleness.
- Review feedback is about the code, never about you.

## Adding a chat skill

Put instructions in `skills/<name>/SKILL.md`. Start the file with YAML
frontmatter containing `name` and `description`, followed by the Markdown body.
The name must match its directory and use 1–64 lowercase letters, digits or
hyphens. Descriptions must contain 10–300 characters. The raw body must contain
1–12,000 characters, including its original line endings, and must not be blank.
Optional `suggested-tools` is a hint, limited to 200 characters; it does not
grant permission to run a tool. Skills apply to chat turns, not daemon workers.

Optional `auto-tools` lists comma-separated native tool names (up to 200
characters). Accepted discovery or use of a named tool loads that enabled skill
for the current turn. Automatic blocks share a 6,000-character whole-body budget;
larger bodies remain manually readable. This field never loads tools or changes
approvals. Use it for tool-specific instructions such as `browser-use`, rather
than matching words in the user's request.

Run `node --test --test-concurrency=1 test/core/skills.test.mjs test/core/browser-skill.test.mjs` after changing skill loading or
metadata validation. See [the skill plan](docs/plans/skills-plan.md) for the discovery
and prompt contract.

## 🔄 The PR process

```bash
git checkout -b fix/short-description   # or feat/...
# ... make the change ...
node --test test/<subsystem>/<file>.test.mjs
npm test                                 # green!
git push origin fix/short-description
```

1. Fork, branch, implement, verify (see above).
2. Open the PR against the **`ankita`** branch (not `main`).
3. Fill in the PR template completely — especially "How I verified it".
4. Wait for review. Address comments, don't argue past them.

## 🎃 Hacktoberfest

- Merged October PRs count. Look for the `hacktoberfest` label.
- 🚫 **Spam PRs get marked `invalid`**: whitespace-only edits, auto-generated junk, trivial README tweaks with no substance. Quality over quantity — always.
- A good Hacktoberfest PR follows every rule above. No exceptions for October.

## 🏷️ Labels you'll see

| Label | Meaning |
|---|---|
| `good first issue` | Small, scoped, newcomer-friendly |
| `help wanted` | We want this but it's meatier — experienced contributors welcome |
| `hacktoberfest` | Good for Hacktoberfest |
| `bug` / `enhancement` / `documentation` / `question` | What it says |

## 🏆 Recognition

Every contributor lands in the release notes. Significant features get shoutouts in release announcements. This project runs on people who show up — thanks for showing up.
