# Eight ideas from the Ankita board

Source: [Ankita ideas, project 8](https://github.com/users/akyourowngames/projects/8).
The board was read with GitHub CLI on 2026-10-10 and contained 94 draft entries,
including duplicates. Eight bounded ideas became repository issues with their
original draft text and source item links. In-place draft conversion was denied:
`does not have the correct permissions to execute ConvertProjectV2DraftIssueItemToIssue`.
Original board drafts remain unchanged; the linked repository issues are the delivery records.

| Issue / PR | Implemented behavior | Branch, in merge order |
| --- | --- | --- |
| [44](https://github.com/akyourowngames/A.N.K.I.T.A/issues/44) / [52](https://github.com/akyourowngames/A.N.K.I.T.A/pull/52) | Exact offline skill instruction fixtures; artifact link guards | `codex/skill-fixtures` |
| [45](https://github.com/akyourowngames/A.N.K.I.T.A/issues/45) / [53](https://github.com/akyourowngames/A.N.K.I.T.A/pull/53) | Complete copyable handbook with tested, allowlisted artifacts | `codex/skill-author-handbook` |
| [46](https://github.com/akyourowngames/A.N.K.I.T.A/issues/46) / [54](https://github.com/akyourowngames/A.N.K.I.T.A/pull/54) | Three-question or offline skill creator, refusing overwrite | `codex/skill-scaffolder` |
| [47](https://github.com/akyourowngames/A.N.K.I.T.A/issues/47) / [55](https://github.com/akyourowngames/A.N.K.I.T.A/pull/55) | Pull-request skill contribution checks and complete bundled metadata | `codex/skill-contribution-gate` |
| [48](https://github.com/akyourowngames/A.N.K.I.T.A/issues/48) / [56](https://github.com/akyourowngames/A.N.K.I.T.A/pull/56) | Actual skill parsing and MCP handshake timings in terminal and desktop | `codex/startup-profile` |
| [49](https://github.com/akyourowngames/A.N.K.I.T.A/issues/49) / [57](https://github.com/akyourowngames/A.N.K.I.T.A/pull/57) | Searchable command guide generated from the real registries | `codex/command-cheat-sheet` |
| [50](https://github.com/akyourowngames/A.N.K.I.T.A/issues/50) / [58](https://github.com/akyourowngames/A.N.K.I.T.A/pull/58) | Four configurable scheduled briefing/digest templates | `codex/job-templates` |
| [51](https://github.com/akyourowngames/A.N.K.I.T.A/issues/51) / [59](https://github.com/akyourowngames/A.N.K.I.T.A/pull/59) | Redacted task runbooks with current definition, history and recovery guidance | `codex/job-runbooks` |

The repository asks for one issue per PR. These branches form eight stacked PRs:
the first targets `ankita`; each later PR targets the preceding branch. Merge in
order using merge commits and retarget the next PR to `ankita` after its parent
merges. Squashing or rebasing a parent requires rebasing the remaining stack first.
The original checkout's unrelated local edits were preserved in its own checkout.
Generated media, logs, dumps and build artifacts are excluded from the changes.

## Verification

Final code revision `706e9cc`: `node --test --test-concurrency=1` (the repository's
`npm test` command) completed with **1159 tests: 1158 passed, 0 failed, 1 skipped**;
duration 427596.117ms. The skip is the existing POSIX executable-permission test
on Windows. Documentation-only receipt additions follow this tested code revision.
The clean pre-change baseline passed 1121 tests, with 1 skip and 0 failures.
`npm run desktop:build` passed: 368 modules transformed, build completed in 6.28s.
`git diff --check origin/ankita..HEAD` passed. The changed-literal audit found shared
artifact names and policy limits with units/reasons; CLI tokens, schema keys,
Markdown rendering syntax and template schedules are intentional interface/data
literals. No fixed production ports, user paths, providers or external service URLs
were introduced. Repository Node requirements remain the workflow's runtime source.

All substantive review findings were reproduced and fixed; the final
independent review found no remaining Critical or Important findings. Regression
coverage includes malformed history, existing job migration and advancing clocks.

Local round trips:

- Fixture checker: `Skill fixtures: 6 passed, 0 failed`; contribution checker:
  `Skill contributions: 6 checked, 0 errors`.
- Real Windows junction: `FIXTURE_LINK_LIVE realDirectoryLink=true outsideRootRejected=true`.
  Direct file redirects use filesystem stubs in additional regressions.
- Handbook: five real artifacts copied, loaded and checked; traversal/duplicates
  rejected before any write. Combined authoring checks passed 15/15.
- Skill scaffolder, searchable commands, template listing/enabling and runbooks
  execute through the real CLI using isolated configuration before provider login.
- Profiling includes a real local HTTP MCP handshake and a failed process launch.
- Real Vite renderer in Chromium, fixture IPC transport calling the real engine:
  `STARTUP_PROFILE_UI_LIVE report=true refresh=true existingDisable=true rendererErrors=0 transport=fixture engine=real`.
- Real daemon/store, fixture worker: `TEMPLATE_DAEMON_LIVE configuredTimezone=UTC attempts=3 successfulDigests=2 previousSuccessSurvivesFailure=true`.
- Real desktop scheduler, fixture worker: `TEMPLATE_DESKTOP_LIVE logOnly=true worker=fixture scheduler=real initialDeliveries=0 retryDeliveries=0 retainedResult=true`.
- Failed/missed local-only tasks: `TEMPLATE_FAILURE_LIVE failedNotifications=0 missedNotifications=0 nativeSink=fixture`.
- Real desktop scheduler with advancing clock: `RUNBOOK_DESKTOP_LIVE started=08:00:00 completed=08:00:05 distinctRuns=1 displayedOutcomes=1`.

## Remaining limits

No new dependency was installed. Remote contribution CI passed on all five PRs
where the workflow exists (55–59); PRs 52–54 precede the new workflow and have no
remote check. GitHub reported all eight PRs `OPEN`, non-draft and `MERGEABLE` into
their respective bases. Each PR is attached to the Codex chat. Branch protection
is not changed. These changes are submitted for merge;
no default-branch merge, installer or release is created by this delivery.

The packaged Electron binary and physical native notification display are not
tested here. Renderer IPC and notification sinks use fixtures, while engine/store/
scheduler and Chromium paths are real. Future cloud answers, live topic/page
research and external notification transport depend on the configured provider.
Instruction fixtures do not promise identical model answers. Permission metadata
is advisory; it is not a new sandbox. Runbooks scrub recognized secrets using the
existing detector, which cannot identify every arbitrary low-entropy secret.

Initial remote receipts (all `completed / success`, before this documentation-only
receipt update):

| PR | Head prefix | Skill contribution gate run |
| --- | --- | --- |
| 55 | `1d2d659` | [38070786752](https://github.com/akyourowngames/A.N.K.I.T.A/actions/runs/38070786752) |
| 56 | `2f1deaa` | [38070790448](https://github.com/akyourowngames/A.N.K.I.T.A/actions/runs/38070790448) |
| 57 | `70d9767` | [38070794233](https://github.com/akyourowngames/A.N.K.I.T.A/actions/runs/38070794233) |
| 58 | `c3cc5ce` | [38070798604](https://github.com/akyourowngames/A.N.K.I.T.A/actions/runs/38070798604) |
| 59 | `6d5d971` | [38070802143](https://github.com/akyourowngames/A.N.K.I.T.A/actions/runs/38070802143) |

The PR 55 Ubuntu log independently reports `Skill contributions: 6 checked, 0 errors`
and `tests 15`, `pass 15`, `fail 0`, `skipped 0`.
