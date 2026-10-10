# Offline skill fixtures

Board idea: Golden-input regression fixtures for skills.

Each bundled skill includes a canned skill-tool input and the exact expected
Markdown returned by the real renderer. Run `node scripts/check-skill-fixtures.mjs`.
Changing instructions now fails this offline check until the expected output is
reviewed and updated deliberately. No contributed code or model call is executed.

These fixtures protect the deterministic instructions users receive. They cannot
promise identical answers from a language model; live model behavior remains outside
this offline contract.

Verification: `node --test test/core/skill-fixtures.test.mjs` — 5 passed, 0 failed.
`node scripts/check-skill-fixtures.mjs` — `Skill fixtures: 6 passed, 0 failed`.
The regression first failed because the runner did not exist, then passed; a
changed instruction is detected by the real render comparison.
All contributed artifacts must be regular files under their explicit skill root.
Review reproduced an outside fixture-directory junction being accepted. After the
guard, `FIXTURE_LINK_LIVE realDirectoryLink=true outsideRootRejected=true`; direct
source/JSON/expected-file redirects are additionally covered with filesystem stubs.
