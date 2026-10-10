# Your first ANKITA skill

A skill is a small set of instructions for a repeatable task. It does not run
code by itself. Start with a task you can explain in a few clear steps.

## 1. Create a folder

Inside the ANKITA checkout, create `skills/hello-skill/`. Names use lowercase
letters, digits and hyphens, up to 64 characters, and must match the folder.
Copy these five files into it. This entire example is exercised by the test suite.

<!-- example: SKILL.md -->
```markdown
---
name: hello-skill
description: Explain an example clearly when someone asks for a short introduction.
suggested-tools: read_file
---
# Hello skill

1. Read the user's example.
2. Explain what it does in two short sentences.
3. Ask before changing any files.
```

Frontmatter supports `name`, `description` (10–300 characters), `suggested-tools`
(up to 200 characters), and `auto-tools` (comma-separated tool identifiers, up to
200 characters). The body must be present and at most 12,000 characters on disk.
Suggested tools are hints. `auto-tools` loads instructions when those tools become
available; omit it unless the skill should accompany every use of that tool.

<!-- example: plugin.json -->
```json
{
  "version": 1,
  "permissions": ["files"],
  "palette": []
}
```

Permissions describe intended access: `files`, `network`, `shell`, `browser`.
This is advisory author metadata, not a runtime sandbox or an access grant.
Existing tool approvals still apply. Optional palette entries have `id`, `title`,
`hint`, and `keywords`; they open this skill in the existing command palette.

## 2. Pin the expected instructions

<!-- example: fixtures/skill.json -->
```json
{
  "input": { "name": "hello-skill" },
  "expectedFile": "expected.md"
}
```

<!-- example: fixtures/expected.md -->
```markdown
# Skill: hello-skill
Suggested tools (hints only): read_file
---
# Hello skill

1. Read the user's example.
2. Explain what it does in two short sentences.
3. Ask before changing any files.
```

This golden fixture is the exact Markdown the real skill tool returns. It catches
changed instructions and rendering changes offline. It does not test a model's
answer. Edit the expected file deliberately when changing the intended workflow;
review the difference instead of blindly accepting a new snapshot.

<!-- example: README.md -->
```markdown
# hello-skill

Use when: someone asks for a short introduction to an example.

Example input: Explain what this example does.

Intended access: files (read only). Ask before edits.
```

## 3. Install and check

The folder inside `skills/` is the installation; nothing needs downloading.
From the checkout root run:

```sh
node scripts/check-skill-fixtures.mjs
node --test test/core/skill-handbook.test.mjs test/core/skill-fixtures.test.mjs
node chat.mjs -p /skills
```

The check must report zero failures and `/skills` must list `hello-skill`. In a
running chat use `/reload`, then ask ANKITA to use the skill. In the desktop app,
open Plugins → Skills and enable it. The normal tool approval rules still apply.

Before submitting a contribution, include these five artifacts, run `npm test`,
and explain the intended behavior in your pull request. Keep credentials, personal
paths, model names and test servers out of the instructions. Prefer configured
resources and current observations over assumptions about the user's machine.

Verification: the handbook regression failed while the guide was absent, then
passed by copying and loading all five fenced examples, including the real golden
comparison. Network access and model behavior are outside this offline example.
