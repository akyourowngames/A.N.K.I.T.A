# Productive skills and native discovery

Implemented in the working checkout on 2026-11-06. New functionality; no release
or publication was performed.

## Using the new skills

- mobile-mcp: grounded Android/iPhone actions, batching and timeout recovery.
- action-chain: dependencies, task handoffs and unfinished-work tracking.
- workspace-batch: several file changes in one reviewable patch.
- research-brief: source reuse without repeated equivalent searches.
- skill-discovery: find and review further skills inside ANKITA.

Example chat: “Find skills for mobile app forms.” Then “Preview that skill” and
“Install the exact preview.” These original skills are bundled and enabled by
default. Plugins > Skills can disable them. A fresh turn refreshes the catalogue.
Mobile skills require a separately connected MCP server and an available device;
they install neither. Matching MCP instructions load from admitted tool names,
independent of the server's local name, including on subsequent turns.

## Search and install engine

`skill_manage` is deferred. List/search/preview read only; installation follows
existing approval rules and is refused in read-only/noninteractive hosts.

```text
node chat.mjs skills list
node chat.mjs skills search mobile forms
node chat.mjs skills preview owner/repo skill-name
node chat.mjs skills install owner/repo skill-name --commit <preview-commit> --path <preview-path> --sha256 <preview-hash>
```

Local commands run before provider login. Preview resolves a full Git commit and
returns instructions plus SHA-256. Install fetches that immutable source again,
checks the digest, records provenance and registers a profile root shared by chat
and desktop. Existing/bundled skills cannot be overwritten. Downloads run no code.
Fixed public HTTPS origins, refused redirects, bounded responses/deadlines,
exclusive directory creation and checked rollback protect the import path.

This first importer conservatively accepts self-contained SKILL.md files only.
Support directories, sibling helpers, relative resources, linked entrypoints,
incomplete trees, bodies exceeding the shared 8000-byte read limit and incompatible
bounded frontmatter are refused. Ancillary
README/license files are not copied. Static checks cannot establish that untrusted
prose is safe or sufficient; preview review and ordinary permissions still apply.
Some useful upstream skills will be refused. There is no package execution,
automatic update, private-source authentication or full YAML compatibility.

## Research and selection

- [Mobile Next Mobile MCP](https://github.com/mobile-next/mobile-mcp): accessibility
  observations and native mobile_batch_commands with optional returned elements.
  Instructions use the connected schema and require advertised stop-on-error
  behavior; they invent no command arguments.
- [Vercel skills search](https://github.com/vercel-labs/skills/blob/main/src/find.ts):
  public catalogue API and source/name selectors. No runtime package was added.
- [Agent Skills specification](https://agentskills.io/specification): entrypoint
  and optional resource format; ANKITA's existing parser remains narrower.
- [Anthropic skills](https://github.com/anthropics/skills): task-focused authoring.
  A temporary-profile brand-guidelines import tested real upstream compatibility
  without redistributing that package into the bundled skills.

## Call-count evidence

`node scripts/bench/skill-workflows.mjs` exercises the real tool host with an
injected mobile server, real temporary file edits and a loopback source server.
Decision plans are scripted. The mobile fixture guarantees stable controls,
batch stop-on-error and returned persisted values. A real device may differ.

Both sides read current state, perform identical effects and verify outcomes.
Discovery, instruction reads, failure recovery and readback are counted. A timeout
occurs after a write takes effect; recovery must not append twice. Parallel fetches
each remain a call. Reference file changes are data replacements verified together;
source-code changes still need their applicable typecheck, tests and diff review.

| Reference task | Individual actions | Optimized calls | Outcome |
| --- | ---: | ---: | --- |
| Stable mobile form | 13 | 4 | Same saved values |
| Mobile timeout recovery | 14 | 6 | Same values, zero duplicate writes |
| Four workspace changes | 9 | 7 | Same files |
| Three complete sources | 3 | 4 | Same evidence; guide read adds overhead |
| Total | 39 | 21 | 46.15384615384615% fewer calls |

This exceeds the 25% reference threshold, but does **not** prove 25% improvement
against ANKITA's existing model behavior. An independent planning check already
chose batching without these guides. Actual improvement needs paired runs of the
same model on real tasks before/after, including failures and screen changes.
No universal call, latency, token or cost improvement is claimed.

## Verification record

- Initial manager tests failed before implementation. Added regression cases
  reproduced omitted pins, malformed results and missing support files before fixes.
- Final combined run across 20 relevant test files: `159/159`, zero failures,
  zero skips, `duration_ms 84831.2437`. Covers skills, manager, imports, real links,
  cancellation, call-count references, core/worker budgets, command discovery,
  tool permissions, MCP contexts and desktop browser-guide delivery. These cover
  the changed contracts without running unrelated voice/release suites.
- After replacing a catalogue keyword literal with its shared constant, the
  affected manager-access checks passed again: `5/5`.
- Contribution gate: `Skill contributions: 12 checked, 0 errors`.
- Desktop build/typecheck passed: `414 modules transformed`, exit code 0.
  A final standalone desktop typecheck also exited 0. Literal review kept service
  origins, byte limits, deadlines, Git modes and profile paths in named constants
  with purpose/unit comments; action/schema tokens remain protocol vocabulary.
  `git diff --check` exited 0.
- Final live public smoke test: 12 search candidates; brand-guidelines imported from
  anthropics/skills at commit `ca45fc496a3436251f191354091d557da31c15b5`, SHA-256
  `1120b3769e2985cefb3d25be981b1f914abeba57ae079b83c20c666c164fa9fe`.
  Result: `chat:true`, `desktop:true`, `restartedCli:true`, temporary profile,
  and a full-body equality assertion passed. The longer frontend-design skill was
  rejected after adding the byte-limit guard; its earlier import is not treated
  as evidence for the final implementation.
- Existing browser regression produced:
  `BROWSER_SKILL_LIVE_OK modelRounds=4 toolCalls=3 extraSkillCalls=0 realFieldReadBack=true advertisedGuide=true`.
- Actual desktop delivery/rendering regression produced:
  `DESKTOP_SKILL_RENDERER_LIVE actualEngineReceipt=true visibleHeader=true clearsOnNextTurn=true pageErrors=0`.
- Review found outside-subtree resources; regression cases cover parent paths,
  reference-style Markdown, HTML links and required omitted README content. The
  independent reviewer confirmed all findings closed. Forward review clarified terminal Save
  and eliminated needless searching when exact file paths are supplied.

Uncovered: physical Android/iOS devices, the real mobile batch implementation,
arbitrary-model adherence, packaged Electron installation, private repositories,
and the full repository suite. These remain limits on the savings/production claim.
