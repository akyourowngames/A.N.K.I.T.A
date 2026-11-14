# Everyday assistant: browser task checkpoints

## Status

Implemented the browser-provider host path. Browser requests now save their
original human goal, reviewed attachment excerpts, owner, project, workspace,
source surface and routine/source-task links before native delivery. Queue
admission immediately saves the immutable native operation identity in the same
task store used by Today. Native tools attach the current task run to the shared
ToolHost, which checkpoints requested, actually started and settled actions at
the existing approval boundary. Merely waiting for approval is not execution.

Continue in Today routes an owned browser task through the original native
operation's observation-only resume path. It cannot create a replacement Send.
The existing browser manager/runtime still enforce account, conversation and
binding ownership. The desktop also rejects task/operation substitution and
project/workspace changes before resuming. A final reply already imported into
the conversation is reused without a second resume. Confirmed identical writes
remain fenced by the shared task journal; uncertain writes still need review.
Fresh native leases restore the original task's saved checklist.

## Reproductions and evidence

- Before integration, the new task suite passed 0/4 with `browser requests need
  a durable task before native completion` and `failed browser turns retain
  their original task`: native browser Send bypassed Agent's task creation.
- Saved work passed directly to native Send was accepted before the guard; the
  focused regression reported `Missing expected rejection.` It now requires
  the saved native operation instead of creating a replacement request.
- Checklist recovery initially failed with `unknown todo ID: s1. Available IDs:
  (none).` A fresh native lease now restores the task checkpoint before tools
  run, and the same status update succeeds.
- `rtk proxy node --test --test-concurrency=1
  test/desktop/assistant-browser-tasks.test.mjs
  test/desktop/chatgpt-browser.test.mjs
  test/integrations/chatgpt-stop-recovery.test.mjs`: **43/43 pass**, zero failures.
- The seven task regressions exercise the actual desktop Send/Today continuation
  entrypoints, local file execution through ToolHost, waiting approval, duplicate
  write prevention, fresh-lease checklist restore, and durable native
  operation/task-store reload. The recovery trace is:
  `BROWSER_TASK_RECOVERY_PROOF {"durableReload":true,"todayResume":true,"nativeSends":1,"nativeOperations":1,"hostedChatGpt":false}`.
- The existing native gateway test performs real local HTTP MCP write, edit,
  readback and a completed command with exact ownership. Its trace is:
  `NATIVE_LOCAL_ACTION_PROOF {"realHttpMcp":true,"exactOwnership":true,"writeEditReadback":true,"commandDone":true,"exitCode":0,"hostedChatGpt":false}`.
- `rtk proxy node node_modules/typescript/bin/tsc --noEmit -p
  desktop/tsconfig.json`: exit 0. `rtk git diff --check`: exit 0.

## Remaining acceptance

The native-operation journey uses real local persistence and execution with
fixture native page receipts. No hosted ChatGPT account/request was sent by this
check, and it does not prove a physical desktop crash while an external service
is changing state. The full suite, packaged desktop, real hosted account binding
and physical phone-to-browser continuation were not run for this focused change.
Existing manager ownership/Stop regressions ran unchanged. This is evidence for
the browser host integration, not completion of the whole everyday assistant.

New production literals are API field names, authored one-use error messages,
and task status values from the existing contract. The checklist tool name is
imported from its definition. No new environment paths, ports, timeouts, provider
models, package versions or network URLs were introduced.
