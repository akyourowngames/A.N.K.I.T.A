# Skill creator

Board idea: `ankita new skill` interactive scaffolder.

Run `node chat.mjs new skill` to answer the three questions. For scripts:
`node chat.mjs new skill explain-log --permissions files --example "Explain this log"`.
Use `--directory` to choose an installation root instead of the bundled skills folder.
The output includes instructions, an advisory access declaration, documentation and
an exact offline fixture. Existing folders are never overwritten. Invalid names,
unknown access domains and empty examples fail before any folder is written.

This runs before login and makes no model or network call. Permission declarations
describe intent; they do not enforce a runtime sandbox or replace tool approvals.

Verification: the real CLI originally rejected `--permissions`. After implementation
the CLI round trip creates a loadable skill with a passing fixture. The four checks
cover that path, all three interactive questions, rejection and collision behavior.
