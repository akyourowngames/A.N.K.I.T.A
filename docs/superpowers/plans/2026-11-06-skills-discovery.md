# Productive skills implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement inline.

**Goal:** Native skill discovery/import plus five focused productive workflows.
**Architecture:** Bounded public catalogue/GitHub client; commit/hash-bound import;
existing profile roots; deferred manager tool and provider-free local commands.
**Tech stack:** Existing Node ESM APIs only.
**Spec:** ../specs/2026-11-06-skills-discovery-design.md

## Constraints and review focus

- No added packages, host execution, automatic overwrites or permission grants.
- Check truncated trees, links, support-file requirements and invalid frontmatter.
- Keep imports consistent across restarts and desktop/terminal discovery.
- Count discovery, skill reads, verification and recovery in reference traces.
- Scripted savings cannot establish model or real-device savings.

## Tasks

- [x] Manager: write failing `test/core/skill-manager.test.mjs`, implement
  `src/skills/manager.mjs`: search, preview, pinned install and list; test malformed
  sources, bounded downloads, hashes, collisions, symlinks and rollback.
- [x] Access: write failing local-command/discovery/approval tests; add
  `tools/skills/skill-manage.mjs`, a deferred category, local `skills` commands,
  shared help, and interactive-only host guard. Test real CLI before login and
  tool-host install approval/denial.
- [x] Skills: add mobile-mcp, action-chain, research-brief, workspace-batch,
  skill-discovery with manifests, docs and real rendered-output fixtures.
- [x] Reference measurement: add executable scenarios and a threshold regression
  test, compare equal effects for normal/partial-failure mobile, workspace and
  research flows. Record exact counts and limitations.
- [x] Verify: focused existing/new tests, contribution checks, desktop typecheck,
  live public search/preview/install/load in a temporary profile, literal review,
  diff check and one fresh review. Update the findings document with evidence.
