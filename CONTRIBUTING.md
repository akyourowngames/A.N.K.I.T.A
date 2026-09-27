# Contributing to Ankita

Ankita is a free, open-source desktop AI assistant — terminal + Electron app, plugin/skill system, local-first by design. It's built in the open, and every contribution counts, whether it's your first PR or your fiftieth.

## Get running in 5 minutes

**Prereqs:** Node.js 20+ (22.12+ if you're touching the desktop app).

```bash
git clone https://github.com/<your-username>/A.N.K.I.T.A.git
cd A.N.K.I.T.A
npm install
cp .env.example .env        # then fill in the keys you need
npm test                    # should be green before you change anything
npm link                    # `ankita` now works from any folder
ankita                      # talk to it
```

Stuck on setup? Open an issue with the `question` label — setup friction is a bug, and your report helps the next person.

## Picking something to work on

1. Start with the [`good first issue`](https://github.com/akyourowngames/A.N.K.I.T.A/labels/good%20first%20issue) label — small, well-scoped, no deep context needed.
2. Comment "I'd like to work on this" so two people don't duplicate effort.
3. Found something broken with no issue? File one first (bug report template), then fix it.

## Rules that actually matter here

Read [AGENTS.md](./AGENTS.md) before your first PR. The short version:

- **No hardcoding.** No magic strings, paths, ports, model names, or OS assumptions inline — hoist them to config or named constants.
- **Nothing is done until it runs.** After implementing, run the relevant tests (`node --test <file>`) *and* a live round trip of the changed path. A green typecheck alone doesn't count.
- **Small PRs beat big PRs.** One issue per PR — easier to review, faster to merge.

## Sending a PR

1. Fork the repo, create a branch: `git checkout -b fix/short-description`
2. Make the change, add or extend tests for behavior changes
3. `npm test` — green before you push
4. Open the PR against the `ankita` branch and fill in the template
5. Expect review comments — they're about the code, and quick back-and-forth gets things merged fast

## Hacktoberfest

PRs merged in October count toward Hacktoberfest — look for the `hacktoberfest` label. Spam PRs (whitespace-only edits, auto-generated junk) get marked `invalid`. Quality over quantity, always.

## Recognition

Every contributor lands in the release notes, and significant features get a shoutout in release announcements. This project runs on people who show up — thanks for showing up.
