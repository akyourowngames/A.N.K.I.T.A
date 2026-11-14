# ANKITA productive skills and discovery

The user wants more useful skills, especially mobile MCP action chains, with a
target of at least 20–25% fewer tool calls and a search/install engine built into
ANKITA. The user selected the built-in approach.

## Result

Add focused original skills for mobile MCP, action planning, research synthesis,
workspace changes, and skill discovery. Keep bodies short and load on demand.
Mobile instructions use the connected server's actual schema, accessibility
observations, native batch capability when advertised, and a final readback.
Never guess device identifiers, coordinates, capabilities, or successful effects.
Stop at dynamic screens and uncertain writes; never replay a completed chain.

Add a native skill manager accessible from chat and local commands. Search the
public skills.sh catalogue, list installed skills, preview a selected public
GitHub skill, and install precisely the previewed content. Source owner/repo,
commit, path and content hash accompany the preview and installation receipt.
Use the existing profile skill-root registry so desktop and terminal see the
same installed skill. Bundled skills and existing installs cannot be overwritten.

## Builder choices

Use existing Node APIs without adding packages or invoking third-party installers.
For this first version, import self-contained SKILL.md instructions only. Reject
skills requiring sibling scripts/references/assets rather than silently installing
an incomplete package. Keep ANKITA's current parser limits and explain incompatible
upstream formats. Search results are candidates, never endorsements or permission.
Install requires the existing tool approval flow and a hash from the preview;
the preview resolves a full commit so mutable upstream branches cannot change it.
Only public GitHub HTTPS sources are fetched, with bounded responses, timeouts,
and no redirects. Imported instructions do not grant extra tool permissions.

Expose the manager as a deferred skill-family tool, preserving the compact core
schema. Local `skills` commands run before provider login. Existing Plugins > Skills
continues to list and enable/disable installed skills; no new settings page is
required for chat access.

## Evidence and limits

Add real manager tests with an injected public-service transport, integration
coverage through chat discovery and local commands, import failure/rollback tests,
and a live public search/preview/install/load round trip in an isolated profile.
Give each original skill its required manifest, documentation and golden fixture.
Measure representative deterministic action traces, including discovery, skill
loading, final verification and partial-failure recovery. Gate the reference
workloads at 25% aggregate call savings with equal final outcomes. This measures
scripted workflows, not model adherence or physical-device performance. Report
that limitation; do not claim universal 25% savings.

Fixed reference workloads: filling a stable mobile form; filling that form with
a partial failure and resuming remaining fields; updating independent workspace
files; collecting independent research sources. The baseline performs the same
primitive actions individually and verifies at each necessary state boundary.
The optimized reference uses only advertised batching/concurrency and returned
observations. Both start cold, count tool invocations (including discovery and
skill reads), verify equal final state, and count partial-failure readback and
remaining work. No time/token savings claim follows from this call-count metric.

## Research

- https://github.com/mobile-next/mobile-mcp: mobile accessibility and native batch commands.
- https://github.com/vercel-labs/skills: search catalogue and GitHub skill discovery.
- https://agentskills.io/specification: instruction format and optional support files.
- https://github.com/anthropics/skills: task-specific skill authoring and evaluation.

No publication, dependency installation, MCP-server installation, or live account
actions are part of this change.
