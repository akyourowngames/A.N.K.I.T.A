# Phone control — verification record

Date: 2026-11-05. Host: Windows 10 x64, Node 24.16.0, branch `feat/phone-control`
based on `ankita` (`e14ba07d`).

## What was verified

### Wireless setup — `node --test test/tools/phone-wireless.test.mjs`

Result: **16/16 pass** (36/36 with the base phone suite). Covers:

- adb mDNS output parses into pairing and connect endpoints, and two phones
  are never guessed between.
- adb is found in the SDK first and falls back to PATH (with the platform
  extension), never inventing a path.
- Pairing codes and addresses are validated before reaching adb; a malformed
  code makes zero adb calls.
- **The pairing code goes over stdin**, and the test asserts it never appears
  in argv.
- A rejected code asks for a fresh one; a pair-then-connect failure points at
  the second step; an unreachable address explains the network cause.
- A dropped wireless phone is reconnected once automatically, and a USB-only
  user never pays for an adb call.
- Wireless actions do not prompt, never mutate the phone, and the code is
  hidden from the approval preview.

Live against real adb on this machine: `wireless` found adb at
`%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe`, ran a real `adb mdns
services` scan, and returned the correct "no phone advertising" guidance.

### Unit and host tests — `node --test test/tools/phone-control.test.mjs`

Result: **20/20 pass**. Covers:

- The family is in the catalog and `find_tools` matches "android phone",
  "phone screenshot" without hijacking unrelated queries.
- Connect writes a **hidden**, **manual-start** record pinned to
  `npx -y @mobilenext/mobile-mcp@1.0.16`, with telemetry disabled and the
  allow-list as its tool ceiling; approval is bound to the command hash.
- A single attached phone auto-selects; with two, a non-listing action reports
  the choice instead of guessing; `use` rejects an id never listed.
- `tap` sends `{ device, ref }`, and a malformed tap never reaches the phone.
- Text, package-id and URL validation (`javascript:` URLs refused).
- `raw` refuses tools outside the ceiling and the cloud/telephony tools.
- A screenshot is copied into `downloaded-images/`, and the host turns its
  receipt into a real attached `image/png` part; receipts pointing outside the
  folder never attach.
- Approval asks once to connect, then only for `uninstall`, `clear_data`,
  `stop_recording` and their raw equivalents.
- Every curated action maps to a tool inside the ceiling (this test caught a
  missing `mobile_uninstall_app` entry that would have failed on a live phone).
- A failed connect returns a readable error and marks the record disabled.

### Existing suites that share this code — still green

- `test/tools/tools.test.mjs` + `test/core/tool-host.test.mjs`: 25/25.
- `test/core/tool-loading.test.mjs`: 18/18 (catalog-driven discovery).
- `test/core/tool-loop.test.mjs`: 19/19.
- `test/core/context-budget.test.mjs`: 5/5 (adding a family did not push a
  prompt budget over its limit). The phone guidance lives in the tool
  description, not the system prompt, so a user who never mentions a phone pays
  nothing for it.
- `tsc --noEmit -p desktop/tsconfig.json`: clean.

### Live run against the real bridge

Launched `@mobilenext/mobile-mcp@1.0.16` through the repo's own `McpManager`
(stdio), then through the `PhoneSession` driver:

- Connected in ~31 s cold (package download); advertised **34 tools**, and every
  one of the 30 tools in `PHONE_MCP_TOOLS` is present (`MISSING: []`).
- Excluded as designed: `mobile_login_to_cloud_provider`,
  `mobile_list_remote_devices`, `mobile_allocate_remote_device`,
  `mobile_release_remote_device`, `get_more_tools`.
- `mobile_list_available_devices` returned `{"devices":[]}` and the tool turned
  that into actionable guidance ("start an emulator or plug in a phone…").
- Approval state on the live path: needed before connect, **not** needed for a
  tap after connect, needed for `uninstall`.
- The store record was `hidden: true`, `manualStart: true`, 30 allowed tools,
  approved. `disconnect` closed the connection.

## Not verified

- **No real phone was driven, wired or wireless.** This machine has no Android
  emulator AVD and no hardware virtualization (`emulator -accel-check` reports
  the hypervisor driver is not installed; `HypervisorPresent = False`), so an
  emulator cannot boot here, and no phone was attached. Taps, typing, real
  screenshots and logs were exercised only through a fake MCP manager, not a
  device.
- **The full wireless pairing handshake was not run against a phone.** mDNS
  parsing, address selection, stdin delivery, validation and every failure
  branch are tested, and the scan ran against real adb, but `adb pair` against
  a real phone with a real code was not executed here.
- **iOS** was not exercised at all; it needs macOS.
- The desktop Electron UI was not launched; the tool was verified through the
  CLI-side host and the MCP manager only.
- `mobile_batch_commands` is passed through as `{ name, arguments }` steps; the
  bridge executes them, but a multi-step flow on a real device was not run.

## To close the gap

Boot one Android emulator (or plug in a USB phone) and run: `phone(action="devices")`,
then `phone(action="see")`, `phone(action="tap", ref=...)`, `phone(action="screenshot")`,
and confirm the attached image and a real `downloaded-images/phone-*.png`.

## Follow-up (2026-11-10)

- Re-ran: `phone-control` 30/30, `phone-wireless` 19/19, `phone-skill` 5/5,
  the related host/loading/budget/skill suites at 111/111, `check-skills` with
  8 skills checked and 0 errors, and `tsc --noEmit -p desktop/tsconfig.json`
  clean.
- Added the bundled `phone-control` skill. It auto-loads when the phone family
  is discovered and is pinned by `skills/phone-control/fixtures/expected.md`
  plus `test/core/phone-skill.test.mjs`, including a discovery round trip.
- Phone screenshots are capped at 3 per turn. Text-only models now get a note
  to use `action="see"` instead of silently dropping the image.
- A screenshot receipt describing a file above the 15 MB cap is refused before
  the file is read.
- Wireless discovery remembers an address only when exactly one connect
  endpoint is advertised; pairing re-scans and connects automatically instead
  of asking the user to read a port.
- Clipboard writes are no longer classified read-only.
- The tool description was trimmed from ~1,700 to under 1,000 characters; the
  skill now carries the step-by-step workflow.
- Still not verified: real taps/typing/screenshots on a device, a complete
  real pairing handshake, iOS, and the desktop UI.

## Full suite (2026-11-10)

Targeted evidence is green: `phone-control` 30/30, `phone-wireless` 19/19,
`phone-skill` 5/5, the related host/loading/budget/skill suites at 111/111,
`check-skills` 8 skills with 0 errors, and `tsc --noEmit -p
desktop/tsconfig.json` clean.

`npm run test:unit` is **not reliably green on this Windows machine** under its
parallel batching: different real-process or timeout tests fail on different
runs, and each failing file passes when run alone (the last one, `voice-worker`,
passed 8/8 alone). The deterministic issues this round were fixed:

- The phone catalogue line is a prompt-budget change. `voice-empty-recovery`
  and `background-worker-policy` now request explicit context headroom, and
  `mcp-images` disables project auto-detection so a developer's registered
  workspace cannot change its prompt.
- The Windows short-name transfer test now skips when the volume exposes no
  8.3 alias instead of crashing on an empty probe.
- The job UI cleanup retries a temp directory that Windows may still hold.

## Security audit (2026-11-10)

Fixed in this round:

- **Batch approval bypass.** A `batch` containing `mobile_install_app`,
  `mobile_uninstall_app`, `mobile_clear_app_data` or
  `mobile_stop_screen_recording` ran without a prompt. State-changing steps
  now trigger the same approval as the curated action.
- **Raw nested batch bypass.** `raw` could reach `mobile_batch_commands` and
  hide destructive steps below a harmless tool name. Raw now refuses nested
  batches and points at `action="batch"`.
- **Install approval.** `install` runs new code on the phone; it now always
  asks, like uninstall and clear-data.
- **Screenshot path escape.** Resolution now follows only generated
  `phone-<timestamp>-<id>.png` names, uses `workspacePath` as the capture root,
  and resolves links so a symlink cannot name a file outside the artifact
  folder. The 15 MB and byte-count checks remain.
- **MCP store collision.** Connecting no longer deletes an unrelated MCP server
  whose id happens to be `phone`; it refuses with a readable error.
- **Device retargeting.** A `raw` argument or batch step can no longer override
  the selected device.
- **Batch bounds.** A batch is capped at 50 steps and 32 KB of serialized steps.
- **Batch approval variants.** Step names are trimmed before the approval
  check, so whitespace cannot dodge it, and typed text inside a batch step is
  hidden from the approval preview.
- **Raw host-file paths.** `raw` and `batch` could pass `saveTo` or `output` to
  screenshot, log and recording tools. Those tools now require their curated
  action, which keeps the path inside the controlled artifact or temp folder.
- **ADB output cap.** `adb` stdout and stderr are capped at 1 MB per stream, so
  a wedged or hostile daemon cannot exhaust memory.

Residual risks (not fixed here):

- The browser screenshot resolver uses the same relative-path pattern without a
  realpath containment check. It validates its own capture filename strictly,
  and changing it is outside this branch.
- `start_recording` passes its `output` path to the bridge. The bridge decides
  whether that is a host or device path; no containment is enforced here.
- Phone screen text remains untrusted model input. Prompt-injection resistance
  relies on the guidance and on approvals, not on a content sandbox.
- The bridge is pinned to `@mobilenext/mobile-mcp@1.0.16`, but `npx` does not
  verify an integrity hash. A compromised registry package is still possible.
