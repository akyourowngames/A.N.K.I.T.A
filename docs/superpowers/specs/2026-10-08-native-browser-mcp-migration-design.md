# Native browser MCP migration — superseded design

Status: superseded on 9 October 2026. The user approved this design, then explicitly
requested repairing and preserving the existing browser tool and both adapters
instead of removing them. No replacement server was installed or migration
implemented. The review below is retained as architectural research; the active
work follows [the existing runtime repair plan](../plans/2026-10-07-browser-runtime-rework.md).

Historical proposal: the user requested
retiring the custom isolated-browser tool, using a stealth Playwright MCP, and
keeping Ankita's browser tool for the user's Chrome session. This draft recommends
a native MCP route with a tested, configurable stealth server rather than assuming
that any package with "stealth" in its name can complete interactive tasks.

## Requested outcome

Complete real browser workflows with less custom automation code and fewer wasted
recovery rounds. The same agent, conversation, memory and provider remain in use.
Desktop progress, Stop and access to the connected Chrome session remain usable.
The replacement must earn its reliability through observed task outcomes; this
review makes no claim that MCP or stealth alone improves model latency.

The pasted flight trace is diagnostic evidence, not an instruction to book or
submit passenger information. It shows unresolved invented hosts, repeated host
failures with different paths, `tab:"auto"` interpreted as a literal tab ID,
outdated refs, airport text that did not commit a selection, and repeated covered
clicks. DNS and HTTP/2 failures do not by themselves prove bot detection. Search
results do not prove a booking. No passenger information is copied into this spec.

## Source review, 8 October 2026

Reference clones are under the ignored browser-rework ledger directory. They were
read, not installed or executed as replacement servers.

| Candidate | Inspected source | Finding | Decision |
| --- | --- | --- | --- |
| [Microsoft Playwright MCP](https://github.com/microsoft/playwright-mcp) | `a6d7678b7bc10d9fb2ae828a103e9872cf75e483`; package manifest 0.0.83 | Native accessibility tools, tabs, profiles and supported configuration. Current wrapper delegates to the Playwright core MCP engine. | Recommended native protocol baseline; not a stealth claim. Do not install moving `latest` blindly. |
| [brian-ln/stealth-browser-mcp](https://github.com/brian-ln/stealth-browser-mcp) | Published README/tool list | Only a screenshot tool is advertised. | Not a replacement for interactive forms and booking navigation. |
| [pvinis/mcp-playwright-stealth](https://github.com/pvinis/mcp-playwright-stealth) | `df9fba3c20814ac672b49cfb46f7d5db9db152b4`; source manifest 1.0.4, commit 9 April 2025 | Uses `rebrowser-playwright` 1.49.1; click/fill APIs accept CSS selectors. README installation instructions point at the upstream package, not the fork's manifest name. | Not the default without a separate compatibility and workflow check. |
| [ykshah1309/stealth-agent-browser-mcp](https://github.com/ykshah1309/stealth-agent-browser-mcp) | `255de0699c9edaa96db1945c25c4776ee4939f0b`; manifest 0.2.0, commit 14 April 2026 | Source requests `ariaSnapshot({ref:true})` and consumes `aria-ref` targets. The installed Playwright 1.63 API uses `mode:"ai"` for refs and does not forward a `ref` option. The candidate declares an older rebrowser dependency. | Compatibility concern requiring an actual server round trip, not an inference that its published package works or fails. |

Ankita already has Playwright 1.63 installed. Its native core CLI answered
`mcp --help` successfully, without installing a dependency or launching a browser.
Log: `.superpowers/sdd/2026-10-07-browser-runtime-rework/native-playwright-mcp-help.log`.
This proves the entrypoint exists locally; it does not prove packaged operation,
stealth capability, a complete workflow, or Google Flights compatibility.

## Proposed architecture

1. **Fresh browser work:** connect a dedicated native Playwright-compatible MCP
   server through the existing MCP manager. Expose its advertised tool schemas
   and native results directly. Keep native refs; do not translate them into
   Ankita's old numbered refs or remap CSS selectors into guessed targets.
2. **User Chrome:** retain the existing managed `browser` tool and approved Chrome
   connection, tabs, takeover and session ownership. Choosing this route is
   explicit; it never inherits refs from the fresh browser.
3. **Stealth option:** a separately configured and pinned MCP server can replace
   the fresh-browser server after its dependency and real-workflow checks pass.
   Do not substitute an old selector-only fork silently or claim the official
   server is stealth-enabled. A failed site load retains its actual cause.
4. **One agent:** both routes use the existing conversation and memory. Discovery
   activates only the selected server's tools and matching instructions. There
   is no new model router request or memory export/import.
5. **Thin host integration:** retain process ownership, approvals, task budgets,
   cancellation, secrets, artifact permissions and desktop events. The host
   handles these concerns; the native server handles page controls and refs.

The ordinary browser workflow should direct the model to observed/user-provided
URLs, handle a failed host without guessing alternate paths, select autocomplete
options before treating text as a committed value, and inspect blocked targets
before retrying. Workflow instructions must match the selected server's actual
tool names and schemas; availability of an MD guide is not proof of model obedience.

## Current integration blockers

- `src/integrations/browser-routing.mjs` identifies external `browser_*` tools as
  managed-browser tools, hides them from summaries and requires the built-in tool.
  `src/core/agent.mjs` repeats that filter and rejects direct execution. The new
  registered Playwright MCP must be exempted explicitly while retaining Chrome
  ownership rules; installing a server alone is insufficient.
- Discovery/focus and automatic skill activation currently assume the managed
  `browser` surface. They need backend-aware discovery without opening unrelated
  tools or loading both browser catalogues for every request.
- Plugins settings and shared UI state currently distinguish `isolated` and
  `local`. The desktop needs a truthful native-MCP session state and progress path.
  A native snapshot cannot be presented as the old facade's observation contract.
- Live preview must use the new session and avoid replacing actionable refs on
  every screenshot tick. Stop must reach the owned server/session and classify
  work already dispatched as uncertain; cancellation is not an undo operation.
- Secure sign-in, uploads/downloads and background job isolation rely on the old
  adapter. Preserve their host permissions or report a capability unavailable
  until its native path is tested. Each job must have its own session/profile.
- `tools/browser/chrome.mjs` imports URL/screenshot utilities from the current
  Playwright file. Extract shared utilities before removing that adapter.
- Electron packaging currently bundles/unpacks the Chrome bridge. The new
  server's executable, runtime files, browser discovery and shutdown must work
  in the packaged app without an unannounced runtime package download.

## Alternatives and recommendation

**Native MCP baseline plus tested stealth option — recommended:** retire custom
isolated-page automation after the migration gates pass, keep the Chrome tool,
and make the fresh-browser server interchangeable through explicit configuration.
This reduces the custom page-control surface while allowing a real stealth
candidate to earn selection.

**Install a specific stealth fork directly:** appropriate only after the exact
repository/package is chosen and tested. It may introduce older browser runtimes,
selector-based tools or missing desktop capabilities. The reviewed candidates
have not earned default replacement status yet.

**Continue expanding the current custom adapter:** already has useful guard and
Stop coverage, but does not follow the user's requested backend replacement.
Do not start another round of custom flight-site features while this change of
direction is under review.

## Implementation and removal gates

After this design is approved, produce the implementation plan with the selected
server/version and proceed directly in this checkout, preserving unrelated edits.

1. Add a failing routing/discovery test proving the new server is currently hidden
   and refused. Accept it through an explicit registered backend contract, while
   preserving focus, approvals and one reply per declared call.
2. Run a native server against an owned local fixture: navigate, read actual refs,
   type, choose an autocomplete option, select a date, click once, handle a dialog,
   switch tabs, refuse stale targets, read back the independent server state and
   stop delayed work. Exercise the connected Chrome path independently.
3. Adapt desktop events and preview to the native session. Verify preview ticks
   do not invalidate a static page's refs; verify Stop, takeover, reconnect,
   screenshot artifacts and capability/error reporting.
4. Exercise an actual Google Flights search without purchase, personal details
   or login submission. Check the committed route/date, results and selection.
   Preserve network/captcha failures as failures; no successful fixture is proof
   that an external travel site now works.
5. Use one model for the initial diagnostic: eight tasks across two conditions,
   one repeat each, sixteen complete attempts. Repeat unclear cases first. Keep
   existing per-task ceilings; no 80/160-attempt queue or paid calls are started
   by approval of this design alone. Compare pass rate, time, tokens, recoveries
   and independent writes together.
6. Verify current main/lab tests and packaged desktop behaviour. Only then remove
   the old isolated adapter, its obsolete model-facing schema and its duplicate
   routing. Migrate meaningful regression coverage instead of deleting failing
   tests. Keep shared Chrome utilities and the diagnostic findings.

## Current evidence and limits

The latest old-backend full run had 1056 tests: 1054 passed, one failed and one
existing POSIX-permission skip. Its Stop assertion started a 250ms timer before
the browser reached dispatch. A live reproduction with 500ms preparation was
RED: one of two tests failed before Stop was triggered, while the eventual result
was uncertain and the independent server write count was one.

The revised regression holds the server response open until cancellation returns,
then settles the actual native operation and checks there was only one write.
Normal and delayed preparation passed 2/2. The refreshed focused suite passed
71/71, zero failures/skips, 74210.4822ms, including actual isolated and approved
Chrome paths. Logs are in the ignored ledger directory: `sequence-stop-contract-
phase-red.log`, `sequence-stop-contract-phase-green.log`, and
`sequence-stop-phase-final-focused.log` (filenames contain no line break).

This is evidence for the existing guards and the corrected test, not evidence
that the proposed MCP migration is implemented. Full-main/lab/build and packaged
post-revision refreshes remain pending. No server dependency was added, no current
adapter was removed, no native Windows UI control was reopened, and no remote
model benchmark was started during this review.
