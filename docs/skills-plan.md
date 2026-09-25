# Ankita Skill System — implementation plan

Status: planned, not implemented. Chat-only v1, built-in skills only.
Scope lock: `suggested-tools` is a hint, never enforced. No daemon / Telegram integration in v1.

Reference standard: [agentskills.io](https://agentskills.io/home) (`SKILL.md` open format, progressive disclosure).

---

## 1. Goal

Give Ankita repeatable "how to do X" knowledge without paying prompt cost every turn
and without adding new tool schemas per workflow.

- **Tools = what Ankita *can* do** (`tools/catalog.mjs` families + MCP + Composio).
- **Skills = how Ankita *should* do it** (markdown checklists the model loads on demand).

Progressive disclosure: startup sees `name + description` (~100 tokens each);
full `SKILL.md` body loads only when the model calls `skill({name})`.

### Locked decisions

| Decision | Choice |
| --- | --- |
| Scope | **Chat REPL only.** Daemon / Telegram / routines / watches explicitly out of v1. |
| Sources | **Built-in only** (`skills/<name>/SKILL.md`). No user dir, no project dir, no `.claude/skills/` compat in v1. |
| Format | **Strict subset of open standard**: frontmatter `name`, `description`, optional `suggested-tools` + markdown body. |
| Activation | **Model-autonomous** via read-only `skill` tool. No keyword matcher, no auto-injection. |
| Tool hints | **`suggested-tools` is display-only.** Never validated, never auto-loads, never blocks. Model still uses `find_tools` normally. |
| Scripts | **None in v1.** No `scripts/`, `references/`, or `assets/` loading. Scripts still run through existing `run_command` approval gate if the model chooses. |
| Deps | Keep **zero runtime dependencies** (hand-rolled frontmatter parser). |

---

## 2. Why this shape

Ankita already has capability-gating (`find_tools` + deferred `CATEGORIES` in
`tools/catalog.mjs:32`), external tools (MCP servers), connected-app actions
(Composio), persistent facts (`remember`/`recall`, `project_memory`), and static
personas (`systemExtra` / teammate prompts). None of these solve "do this
multi-step workflow the same way every time" cheaply:

- `systemExtra` + project brief bloat every turn.
- A new `CATEGORIES` entry per workflow costs schema tokens forever.
- MCP is overkill for pure knowledge (process spawn + approval + ~k tokens).
- Memory stores facts, not procedures.

Skills fill exactly that gap: ~1 catalogue line per skill until used, portable
folders, version-controlled, composable (`commit-review` + `ankita-dev` stack).

---

## 3. File layout

```
skills/
  ankita-dev/SKILL.md       # NEW — repo conventions
  commit-review/SKILL.md    # NEW — diff review checklist
src/
  skills.mjs                # NEW — loader + prompt lines + cache
  agent.mjs                 # EDIT — thread skill lines into system prompt
  cli.mjs                   # EDIT — /skills list + /reload refresh
  ui.mjs                    # EDIT — /skills in /help text
tools/
  skill.mjs                 # NEW — always-on read-only reader
  catalog.mjs               # EDIT — add alwaysOn 'skills' category
  index.mjs                 # EDIT — import skill, add to CORE
test/
  skills.test.mjs           # NEW
```

No new config keys in v1. `SKILLS_DIR` resolves from module URL
(`<repoRoot>/skills`), not `process.cwd()`, so `ankita` works from any folder.

---

## 4. SKILL.md contract

```md
---
name: commit-review
description: Review git diffs and staged changes for this repo. Use when user asks to review, check, or summarize changes.
suggested-tools: git, read_file, search_files
---
# Commit Review
1. Load `git` via find_tools if needed...
```

Rules:

- Frontmatter = lines between first two `---` lines. Dumb `key: value` parser, no YAML dep.
- `name`: required, `^[a-z0-9-]{1,64}$`, must equal directory name. Mismatch → skip + one `console.error` line.
- `description`: required, 10–300 chars, newlines folded to spaces. Verb-first, ends with "Use when …" so the model can match.
- `suggested-tools`: optional, free-form string ≤200 chars, passed through verbatim. Never validated against real tool names.
- Body: everything after second `---`, trimmed. Must be non-empty, ≤12000 chars on disk; served capped to 8000 via existing `capOutput`.
- Invalid / missing `SKILL.md` → skill skipped, boot never throws. Empty `skills/` → zero skills, prompt section omitted.

---

## 5. `src/skills.mjs` spec (new)

```js
export const SKILL_NAME_RE = /^[a-z0-9-]{1,64}$/;
export function parseSkillFile(text, dirName) // -> { name, description, suggestedTools, body } | { error }
export function loadSkills(dir?)              // -> [{ name, description, suggestedTools, body, path }]
export function skillPromptLines(skills)      // -> string[]
export function reloadSkills()                // -> clears cache
export function skillsDir()                   // -> absolute <repoRoot>/skills
```

Details:

- `loadSkills` does `readdirSync` + per-dir `SKILL.md` read, `try/catch` per skill, sorts by name for a deterministic prompt.
- Cache: `{ key, skills }` where key = dir mtime + file mtimes + sizes. `reloadSkills()` clears; `/reload` calls it. Mtime check on each `loadSkills()` call keeps it cheap.
- `skillPromptLines(skills)` returns e.g.:
  ```
  Available skills (chat only, progressive disclosure):
    - ankita-dev: Develop in this repo … Suggested tools: read_file, edit_file. To use, call skill({"name":"ankita-dev"}).
    - commit-review: Review git diffs … Suggested tools: git. To use, call skill({"name":"commit-review"}).
  Skills are instructions only. Suggested tools are hints, not requirements. Use find_tools to load tools if needed.
  ```
- Returns `[]` when no skills, so `buildSystemPrompt` omits the section entirely.

---

## 6. `tools/skill.mjs` spec (new, always-on)

```js
export const name = 'skill';
export const description = 'Load a built-in skill: repeatable workflow instructions (e.g. commit-review). Call when the task matches a skill description. Returns markdown to follow; suggested tools are hints only.';
export const needsApproval = false;
export const readOnly = true;
export const parameters = {
  type: 'object',
  properties: { name: { type: 'string', description: 'Skill name, e.g. commit-review' } },
  required: ['name'],
};
export function run(args, ctx) // -> string
```

Behavior:

- Normalise `name`: `String(...).trim().toLowerCase()`. Lookup in `loadSkills()`.
- Hit:
  ```
  # Skill: commit-review
  Suggested tools (hints only): git, read_file
  ---
  <body, capped to 8000 chars>
  ```
- Miss: `Unknown skill "x". Available: ankita-dev, commit-review.` — never throws.
- No `ctx.state` mutation, no `activatedTools` change, no internal `find_tools` call. Pure reader, same shape as `tools/recall.mjs:60 run()`.
- Registration: new `{ id: 'skills', alwaysOn: true, … }` entry in `tools/catalog.mjs`, import + `CORE` push in `tools/index.mjs`. Flows into `coreSpecs` / `currentSpecs()` / context budget automatically.

---

## 7. `src/agent.mjs` wiring

- `buildSystemPrompt(config, cwd, project, mcpServers, personal, skillLines = [])` gains trailing param; spread after `...mcpPromptLines(mcpServers)`:
  ```js
  ...(skillLines.length ? ['', ...skillLines] : []),
  ```
- `Agent` constructor builds `this.skillLines = skillPromptLines(loadSkills())` and passes into initial `messages[0]`.
- `clear()`, `rebase()`, `refreshPrompt()` recompute via the same helper so project switches and `/reload` preserve skills.
- No changes to `currentSpecs()`, `specParts()`, `toolBudgetBytes()`, `trimHistory()`, `MAX_TOOL_STEPS`, repeat guard, or two-model turn logic.

---

## 8. `src/cli.mjs` / `src/ui.mjs` wiring

- `/skills` — prints `name — description` lines from `loadSkills()`. Empty → `No built-in skills installed.`
- `/reload` — calls `reloadSkills()` alongside existing config reload.
- `/help` (cli.mjs command list + `ui.mjs:187` help text) gains `/skills`.
- No `/skill <name>` executor in v1 — model path only, keeps slash surface minimal.

---

## 9. Built-in skills content

### `skills/ankita-dev/SKILL.md`

- `suggested-tools: read_file, edit_file, search_files, run_command`
- Body (~30–50 lines): repo map (`chat.mjs` entry, `src/agent.mjs` loop, `tools/` one-module-per-tool), test cmd `node --test "test/*.test.mjs"`, prefer `edit_file` over `write_file`, PowerShell `;` not `&&`, zero-runtime-deps constraint.

### `skills/commit-review/SKILL.md`

- `suggested-tools: git`
- Body checklist: 1. `find_tools("git")` if needed 2. `status` + `diff` 3. summarise files / behaviour / risks 4. suggest test command 5. stop — never commit unless asked.

Both double as loader fixtures for tests.

---

## 10. Tests — `test/skills.test.mjs`

1. `parseSkillFile`: valid file; missing name; bad chars; description too short/long; `suggested-tools` passthrough; body empty rejected.
2. `loadSkills(tmpdir)`: temp dir with good + bad-name + missing-`SKILL.md` entries; asserts good loads, bad skipped, output sorted by name.
3. `skillPromptLines`: contains name + description + "hints, not requirements" disclaimer; `[]` input → `[]`.
4. `skill.run({ name })`: hit returns `# Skill:` header + hint line + body; miss returns `Available:` list; long body capped.
5. Prompt wiring: `buildSystemPrompt(..., ['- x: y'])` contains the line; `coreNames()` includes `skill`.
6. Fixtures: both built-in `skills/*/SKILL.md` parse clean.

Style: `node:test` + `node:assert/strict`, temp dirs under `os.tmpdir()`, no network, no model calls — same pattern as `test/projects.test.mjs`.

---

## 11. Verification

```bash
node --test "test/skills.test.mjs"
node --test "test/*.test.mjs"
node chat.mjs -p "/skills"            # lists ankita-dev, commit-review
node chat.mjs -p "review my changes"  # expect skill({name:"commit-review"}) then find_tools git
node chat.mjs --config                # skill present in core tools
```

Token check via `/usage`: catalogue adds ~200 tokens for 2 skills; full body tokens appear only after a `skill` call.

---

## 12. Risks / mitigations

| Risk | Mitigation |
| --- | --- |
| Prompt bloat | 1 line per skill in system prompt; body on demand only. |
| Model never calls skill | Verb-first descriptions with "Use when …"; `skill` tool description cross-references catalogue; `/skills` for manual discovery. |
| Stale cache after edit | Mtime-keyed cache + explicit clear on `/reload`. |
| Windows paths | `path.join`, module-URL-resolved dir, `os.tmpdir()` in tests. |
| Fragile frontmatter | Dumb parser, skip-on-error per skill, boot never throws. |
| Hint mistaken for enforcement | Header says "(hints only)" in both catalogue and tool result; no code path enforces it. |

---

## 13. Future (out of v1, noted only)

- User dir (`~/.copilot-chat-cli/skills/`) + project dir, precedence project > user > built-in.
- Multi-file skills (`references/`, `scripts/`, `assets/`) under existing `capOutput` caps.
- Optional `allowed-tools` enforcement mode (v1 stays hint-only per decision).
- Daemon opt-in (routines/watches able to name a skill).
- `/skill-name` slash shortcuts.
- Skill-creator skill (generate folder + frontmatter interactively).

---

## 14. Build order

1. `src/skills.mjs` (parser + loader + prompt lines + cache).
2. `tools/skill.mjs` + `catalog.mjs` + `index.mjs` registration.
3. `src/agent.mjs` prompt threading (`constructor`, `clear`, `rebase`, `refreshPrompt`).
4. `src/cli.mjs` `/skills` + `/reload` + help text.
5. `skills/ankita-dev/SKILL.md` + `skills/commit-review/SKILL.md`.
6. `test/skills.test.mjs` + full suite + manual `/skills` check.
