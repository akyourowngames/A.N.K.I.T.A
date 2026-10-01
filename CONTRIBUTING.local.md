# Contributing to Ankita

Read [AGENTS.md](AGENTS.md) before editing. Preserve unrelated worktree changes.
Run affected tests, the serial suite (`npm test`), `npm run desktop:build` for
desktop changes, and `git diff --check`. Browser changes require a real browser
round trip; distinguish fixture providers from live models in the evidence.

## Secrets and persistence

Any feature that writes chat, tool results, job output, memory, text diagnostics
or exports must use a scrubbed copy. Never mutate the model's live turn to scrub
it. Use `redactValue` from `src/security/secret-scrubber.mjs`, or desktop
`SecretHistory.clean` to preserve stored-secret references and protect later
echoes. Add a regression containing a fake supported secret for every new
secret-adjacent write path. Operational provider configuration and encrypted
vault records have their own storage contract; do not migrate the whole config
directory indiscriminately. Binary images/dumps are not text redaction targets.

Examples such as `password="hunter2"` are intentionally redacted. Detection is
deterministic and bounded; arbitrary unlabeled or split secrets are outside v1.
Do not add per-value allowlists. Values retained transiently for echo protection
never go into a plain cache file.

## Palette contributions

Every enabled repository skill appears in the command palette by name and
description. Declare useful actions in an optional `plugin.json` beside its
`SKILL.md`:

```json
{
  "palette": [
    {
      "id": "weekly-review",
      "title": "Review this week's tasks",
      "hint": "Find useful next actions",
      "keywords": ["weekly", "review"]
    }
  ]
}
```

IDs must be lowercase letters, digits or hyphens, at most 64 characters and
unique within a manifest. At most 20 entries are accepted; titles are limited to
100 characters, hints to 300 and keyword lists to 20. Manifests contain data;
they cannot supply executable handlers or bypass approval. Running an action
requests its skill through the normal teammate turn. Registry changes appear
on the next palette query/open without restarting. Recent actions are deferred.
