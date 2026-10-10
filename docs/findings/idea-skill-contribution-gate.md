# Skill contribution check

Board idea: CI gate for skill pull requests.

`node scripts/check-skills.mjs` checks every skill's frontmatter, exact offline
fixture, advisory permission manifest, palette entries and named documentation.
The dedicated pull-request workflow runs this check and the authoring regressions
with read-only repository permission. It does not execute community code or call a
model. All existing bundled skills now include the required author artifacts.

Local verification covers valid bundles, missing manifests/docs, invalid access
declarations and changed instructions. Remote execution is checked after the pull
request is opened. Repository branch protection is outside the workflow itself:
maintainers can select this check as required if desired.
The authoring gate passed 15/15 checks locally. The copied handbook bundle also
passes the contribution validator. Paths are limited to five unique known artifacts
before any example writes; realpath guards reject contributed artifact redirects.
