# ChatGPT browser integration evidence

Approved design: `superpowers/specs/2026-10-12-chatgpt-browser-integration-design.md`.
Plan: `superpowers/plans/2026-10-12-chatgpt-browser-integration.md`.
Branch: `codex/chatgpt-browser`, based on `a31c882` from remote `ankita`.
The original checkout's uncommitted edits are preserved.

## Task 1: execution host and local native MCP

- Baseline: `npm test` exited 0; 1208 tests, 1207 passed, 0 failed, 1 skipped.
- RED: the two new test files failed with `ERR_MODULE_NOT_FOUND` for ToolHost.
  A later native-output bound test failed before text/image sanitization was added.
- GREEN: the new host/gateway tests and existing agent audit, browser protocol,
  MCP tiers and MCP images suites passed **63/63**, 0 failed.
- The extracted ToolHost owns policy, prepare/recheck, workspace context, cancellation,
  search/browser budgets and desktop pointer-session injection. Agent retains API image
  history projection and project/memory refresh. Native results retain bounded text/images.
- A discovered API regression dropped native target metadata. Restoring structured
  content made both existing target-ID regressions pass without weakening assertions.
- `rtk proxy node scripts/verify-chatgpt-gateway.mjs` exited 0:
  `{"protocol":"2025-11-25","tools":["read_file"],"exactFileBytesMatched":true,"writeDenied":true,"hostedChatGpt":false}`.
  This executed the real MCP HTTP client, SDK server and filesystem worker against a
  unique temporary file, then drained/closed both transports. It is a local protocol proof.
- `npm run desktop:build` initially failed because npm omitted the existing TypeScript
  Windows platform package. Restoring that package from the original installation after
  confirming exact version 7.0.2 resolved the environment failure; the subsequent build
  exited 0. No compiler version or dependency declaration was changed.
- HTTP tests reject wrong capability, Host, Origin, missing source request ID, wrong
  lease, oversized body and changed payload on retry. Duplicate calls execute once.
  Protected-resource discovery requires the endpoint capability and does not expose it
  through public discovery. Endpoint URLs/secrets and proof bytes are excluded from Git.
- Production protocol identifiers, limits, versions and routes are named constants.
  Result text and tool names are wire/UI vocabulary; fixture literals stay in tests/scripts.

## Dependencies

Sonatype component tools were unavailable after tool/plugin discovery. This independent
trust scan remains uncovered; it is not substituted with a fabricated rating.
Pinned official TypeScript SDK packages: `@modelcontextprotocol/server@2.3.1` and
`@modelcontextprotocol/node@2.1.1`, Apache-2.0, official MCP SDK repository.
Registry integrity/provenance inspected before installation, lifecycle scripts disabled.
The isolated candidate audit reported **0 vulnerabilities**; `npm audit signatures`
reported **6 verified registry signatures and 6 verified attestations**.
The final production-only dependency audit reported **0 vulnerabilities**.
Root installation reported 10 development dependency findings (8 moderate, 2 high);
the change does not upgrade those existing dependencies. No broad audit fix was applied.
Npm replaced the worktree's dependency junction with an independent installation;
the original checkout's dependency directory was not modified.

## Subsequent regression results

The first full post-extraction run had 1219 tests, 1215 passed, 3 failed, 1 skipped.
It caught a removed browser-classifier import still used by schema discovery and changed
background refusal wording. Restoring the import and explicit background scope made the
unchanged affected suites pass **19/19**. The subsequent full serial suite exited 0:
**1229 tests, 1228 passed, 0 failed, 1 skipped**, 456903 ms.

The final host policy regression then exposed stale config precedence and a missing
standalone approval formatter. Current host approval takes priority over old config;
the real formatter is shared with Agent, and cancellation tests require the approval
callback to run before checking that no mutation occurred. The regression failed before
the correction. The final affected suites, native adapters and complete renderer startup
checks passed **96/96**, 0 failed; `npm run desktop:build` exited 0 after these changes.
The earlier full-suite total predates this final host correction. The final serial run
against commit `10cb119` exited 0: **1231 tests, 1230 passed, 0 failed, 1 skipped**,
435069 ms. The skip is the existing Windows/POSIX fixture branch.

## Task 2: external companion attach checkpoint

- Two new files initially failed against the absent bridge/readers. Offline companion,
  evaluated-model and gateway tests then passed **14/14**.
- Focused MIT DOM/Fiber functions are forked from the pinned CoS source, with SHA-256
  provenance and unchanged license under `vendor/chat-on-steroids`. The fork contains no
  app/overlays/assets, DOM mutation, page message listener, private analysis recording,
  React action callback or private API request. Parser bounds are named and unchanged.
- The generated manifest and wire data share host config. Permissions omit debugger
  and cookies; injection occurs only after an explicit durable conversation binding.
  Popup-origin checks reject website/content-script control messages. Navigation during
  a read discards the observation. Same-title tabs do not substitute for the selected ID.
- Pairing lives only in process RAM and Chrome session storage. A protected secret
  provider is injectable; no plaintext pairing credential is persisted. Disconnect intent
  survives reconnect attempts within the bridge lifecycle; process restart requires new
  manual pairing. Desktop encrypted persistence is part of the gated later runtime.
- `rtk proxy node scripts/verify-chatgpt-companion.mjs` exited 0:
  `{"realHttpPairing":true,"selectedFixtureTab":true,"attributedLocalReadMatched":true,"disconnectRefusedTools":true,"browserRelaunches":0,"hostedChatGpt":false}`.
  This is a real loopback bridge→gateway→filesystem round trip with synthetic tab/model
  observations. It does not establish a browser/account connection.
- Historical request IDs from the first read cannot authorize a new lease. Only subsequent
  exact native request joins can execute. Missing, conflicting or stopped ownership fails
  closed; account/model observations expire. No request argument supplies host context.
- Setup instructions: `chatgpt-companion-setup.md`. One-time owner displays are explicitly
  requested with `--print-pairing`; diagnostic mode prints no credential or MCP capability.

## Remaining live gate

Task 2 must prove the already-open Chrome conversation can call this read-only surface
through a supported native ChatGPT connection, with exact request/conversation attribution.
Account/model availability, custom MCP access, tunnel provisioning and current page
compatibility remain unproved. Tasks 3–7 remain gated by that hosted proof. No desktop
ChatGPT provider is advertised as ready, and no unlimited-model claim is made.
The Chrome relay available to this chat has no targetable Chrome DOM surface; the Windows
computer-use skill forbids handling security/privacy permission prompts. The local
companion is ready for manual loading, pairing and model observation in the existing
Chrome profile. No browser restart or profile transfer was attempted. `cloudflared` was
not found on PATH; no supported HTTPS endpoint/tunnel or account connector is provisioned.
The user handoff is pending. The final fresh branch review and packaged desktop/account
workflow remain later gates; this checkpoint is not a released desktop browser provider.

## Execution rulings and deferred work

- Reused the attached isolated worktree on a new branch, preserving original edits and
  the separate computer-use checkout. Installed Git Bash was used for the plan ledger
  scripts because no `bash` executable was available on PATH.
- Sonatype's service was unavailable; actual registry/provenance/license/integrity,
  signatures/attestations and vulnerability audits were used, with the missing scan
  disclosed. No dependency trust score or account capability is inferred.
- Lifecycle-local MemoryToolReceipts arrived ahead of Task 5 to prove duplicate-call
  handling in Task 1. They are deliberately unsuitable for restart/mutation recovery;
  the gateway gets a new secret URL on each lifecycle.
- Used the real McpClient `callTool` method; `callToolResult` belongs to the manager.
  Native structuredContent is carried optionally to the API adapter to preserve Cua
  target identity, while native publication emits bounded metadata/content.
- Npm omitted the existing Windows compiler platform package. The original exact
  version was restored after OS/architecture/name/version checks; no compiler upgrade
  or manifest change was introduced.
- Proof pairing remains memory-only instead of creating a plaintext credential file.
  Encrypted desktop persistence and deliberate restart/reconnect UX are later tasks.
- Native account proof remains the binding gate. Manual extension/connection permissions
  cannot be performed by this Windows skill, and no public endpoint is provisioned.
  Tasks 3–7 therefore remain pending rather than treating local fixtures as account proof.
- Deferred API interface work: operation-store durability, Send/accept/completion receipts,
  tool receipt persistence, complete native surface publication, full action/image
  aggregate budgets, attachments/Stop/recovery, desktop routing/packaging and final fresh
  review. The current bridge's model-only enqueue identifier is not a durable Send receipt
  and must be replaced at Task 3 before any delivery acknowledgment is exposed.

## Live setup repairs and CoS source re-check

The user reproduced HTTP 409 after repeating Connect and confirmed that Chrome was on a
blank new-chat page. The service was reachable; the extension's new random browser ID on
each Connect caused the ownership conflict. Same-URL reconnect now reuses its session ID
and preserves the binding. An empty picker now explains that a saved conversation is needed
and disables Observe until one appears. These two tests failed before correction.

A subsequent screenshot showed a signed-in, selected saved conversation while the popup
said `logged-out`. Actual bridge observations had no model choices. Missing picker evidence
was wrongly treated as absence of the account, and the picker search included unrelated
page menus. The focused CoS lookup now limits generic menus to the selected composer,
deduplicates explicit native triggers and publishes only safe diagnostic codes. Three
regressions failed before correction. The actual paired Chrome observation subsequently
reported `model-picker-unavailable`; its composer was present. The user confirmed the
corrected explanation in the popup. No further Windows input occurred after physical Escape
stopped Computer Use; screenshot capture had also failed twice.

The user then clarified that ordinary desktop-to-web messaging and the native MCP plugin
are the goal. Latest upstream `9b6d104e958c3b130bf25a92f7b29baa1b422a25` was fetched into the
read-only reference repository, preserving the original adapter checkout/hash pin.
`extension/chatgpt-dom.js`'s `selectModelSettings` returns immediately when no model/effort
is requested. CoS supports an optional built-in Electron browser and external Chrome;
its Core MCP connector and authenticated control API are separate from model discovery.
Current-model mode therefore leaves the browser selection unchanged and its unknown
model name null. Explicit-model mode still requires evaluated selection. Native request
provenance is read independently of the picker; exact binding/lease/nonce ownership and
Disconnect refusal remain required. Three regressions failed before this correction.

Latest affected suites passed **22/22**. The real Chromium popup fixture checks empty-list
recovery and honest page/current-model explanations; this is not the user's Chrome profile.
The final full serial `npm test` exited 0: **1239 tests, 1238 passed, 0 failed, 1 skipped**,
515175 ms. The existing Windows/POSIX skip remains. `npm run desktop:build` exited 0 and
`git diff --check` passed. Both local HTTP proof scripts passed again with exact temporary
file bytes and disconnected-tool refusal; both still explicitly report `hostedChatGpt:false`.

The user reports that CoS Core and its tunnel already exist. Read-only local inspection found
CoS **2.1.34** installed, its selected browser `cos`, no running CoS/tunnel process, no control
endpoint, and both control API switches disabled. No CoS settings, secrets, installation or
browser profile were changed, and the app was not launched. Reusing its existing runtime
would change tool authority from ANKITA's ToolHost to CoS's tools. The user delegated the
choice and clarified the startup/EXE goal; the selected product route remains standalone
ANKITA with bundled reusable CoS components, preserving ANKITA's tools and pointer.
The user's live companion now reports **Connected · using the current model in your
ChatGPT chat**, with `modelMode:current`, an unknown model name and the optional picker
unavailable. Hosted native MCP, full desktop routing, packaging and final whole-branch
review remain pending.

The native proof runner was prepared separately in ignored `.commandcode`. It verifies the
installed tunnel helper against the official OpenAI tunnel-client v0.0.16 Windows archive:
archive SHA-256 `edef7241b0c647fcb30f1a80ff376b6b25c51927960f257a3f01e21b17c2aba6`,
helper SHA-256 `cd0bc49aec24d0d62a37b6e842dad46000f7b401f6167b4cbace4e170819c9a2`.
The audit exited 0 with `installedMatchesPublisher:true`; the helper's executed version
check returned `cloudflared version 2026.8.2`. No dependency or binary was added to the
product. Publisher identity does not replace the unavailable Sonatype scan.

The previous owner terminal had ended. Process inspection returned
`ownerTerminalAlive:false,nodeProcesses:[],listeners:[]`; no process was terminated.
The fresh owner terminal and its Node child are running, with an actual loopback HTTP
check returning `serviceReachable:true,unpairedStatus:401`. Its diagnostic log currently
reports `pairing-required`, so no public tunnel has started. After a fresh companion
binding, the runner will publish only the scratch proof surface, validate native MCP
initialization and `read_file` discovery without executing a tool, then display the
private connection URL in the owner terminal. The user's existing CoS tunnel is untouched.
Actual hosted request attribution/file bytes remain the proof gate.

## Public proof startup repair

The user's actual bound browser started the scratch tunnel, but the first public probe
failed with `TypeError`. Live diagnosis found `/ready` HTTP 200 and one tunnel connection,
while Windows name lookup failed with `ENOTFOUND` (direct DNS queries also returned
`ECONNREFUSED`). Two HTTPS DNS resolvers returned DNS status 0 with two IPv4 answers.
Connecting to the allocated hostname using those answers, with its original TLS hostname
and certificate verification intact, returned HTTP 401 for an invalid endpoint capability.
This proves reachability and rejection, not hosted tool execution.

The optional `services/chatgpt-bridge/public-probe.mjs` fallback is scoped to the explicit
public proof origin and read-only initialization/tool discovery. It never replays
`tools/call`, changes Windows DNS, disables TLS or retries authorization/admission failures.
Resolver input contains only the public hostname; no endpoint path or pairing secret is
sent. DNS and discovery responses are bounded and cancellation is retained.

A transport-only live fixture then reproduced a second startup condition: a new hostname
had no DNS answers initially. Six failed probes were followed by successful MCP discovery
on attempt 7 without another tunnel or browser send. A bounded readiness check now waits
for public DNS/proxy readiness; its next live run returned HTTP 530 on attempt 1 and then
`toolNames:[read_file],attempts:2,protocol:2025-11-25,success:true,executions:0`.
It explicitly reports `hostedChatGpt:false`. Eight regressions were observed RED in two
stages, then passed GREEN. The affected companion/popup/gateway suites passed **30/30**;
the desktop build exited 0. That full serial suite subsequently exited 0: **1247 tests,
1246 passed, 0 failed, 1 existing Windows/POSIX skip**, 590165 ms.

The user also supplied CoS setup screenshots showing its selected built-in browser,
OpenAI Secure MCP Tunnel flow, masked stored key and connected tunnel transport. They do
not prove a completed native tool call or ANKITA ownership. The original standalone
design already prefers Secure MCP Tunnel for the product; this temporary quick-tunnel
proof neither takes over that CoS connector nor copies its stored credentials.

The user's actual re-paired checker then produced the same successful path:
`public-mcp-startup-wait` with HTTP 530 on attempt 1, followed by
`public-read-only-mcp-ready`, `tools:[read_file]`, `attempts:2`,
`publicTransportVerified:true`, `hostedNativeMcp:not-proven`. Safe local diagnostics
confirm that output. The private proof URL is shown only in the owner terminal and
is not recorded here. The public Server URL app setup was rejected by the account UI.
That rejection does not establish that all public Server URL setups are unsupported.

## Secure native tunnel and request attribution repair

The proof moved to the supported OpenAI Secure MCP Tunnel flow shown in CoS. The official
`tunnel-client` executable matched publisher archive member SHA-256
`4226bb74a72388147882881f29f79801b95e285d731a138071812e3aa6766571` and its executed version
was `0.0.16+5f99daabd4aa4a77049e6d81d54a0d8c18335397`. This is a development helper only;
no product binary or dependency was added. CoS's stored credentials/tunnel were untouched.

The integrated runner owns pairing, the temporary read-only workspace and its local MCP
endpoint. It prompts for only the dedicated tunnel ID and hidden restricted key; the user
cannot accidentally substitute a pairing URL as the MCP endpoint. Private input is piped
to the owner process, never placed in argv, diagnostic files or source. Input validation
regressions passed **2/2**; its actual unpaired bridge returned HTTP 409 and started no
native process. The user then paired successfully; local discovery exposed only `read_file`,
and safe health diagnostics reported `localReady:true,openAiPollSeen:true`.

The installed ANKITA Proof app reached `read_file`, but the user's first actual call failed
with **FORBIDDEN: Request owner is unavailable**. The user confirmed the exact conversation
selected in the companion. This proves native request transport, not a successful tool
execution. The focused adapter had omitted CoS `extension/usage.js`: React request IDs can
arrive tens of seconds after the live response stream, outside the bounded ownership wait.
Its `readOrigin` explicitly joins a conversation handoff to a later
`input_message.metadata.request_id` within the same HTTP response. The focused port now
captures that evidence, plus native WebSocket handoff IDs, independently of the model picker.

No private API request, credential/header read, prompt/analysis recording or page message
authority was added. Only the bound page is injected. Scope is fenced by lease, epoch,
tab and exact route before publishing metadata; historical DOM IDs cannot crowd out fresh
stream IDs. Contradictory responses, unknown delta formats/channels, wrong socket chains,
foreign origins, navigation and stale bindings abstain. Safe diagnostics contain source
counts/readiness only. The unchanged exact ownership gate remains mandatory.

Seven new cases first failed for the missing observer, then passed. Latest affected suites
passed **39/39**. An actual isolated Chromium page made an HTTP streaming request; its
React request count stayed zero while the stream supplied one exact ID. A real MCP call
arrived before observation, waited for that join, and read the unique scratch bytes:
`actualIsolatedChromium:true,realHttpStream:true,reactRequestIds:0,streamRequestIds:1,`
`exactJoinReadMatched:true,originalResponsePreserved:true,disconnectedCallRefused:true,`
`elapsedMs:204,hostedChatGpt:false`. The fixture's initial disconnected assertion incorrectly
expected an error result; the real client rejects HTTP 403. That assertion was corrected
without changing production admission. Ignored trace: `.commandcode/verify-request-stream-live.mjs`.

The desktop build exited 0; the full serial suite exited 0: **1257 tests, 1256 passed,
0 failed, 1 existing Windows/POSIX skip**, 569667 ms (request-reader checkpoint `70a6740`). The user reloaded and
paired the new owner runner, reused the installed native app/tunnel, and sent the proof
request in the selected saved conversation. The safe local trace confirms
`requestEvidence:{observerReady:true,streamIds:1,domIds:0}` followed by
`native-request-ownership:{exactJoin:true,elapsedMs:0}` and
`hostedNativeMcp:attributed-file-bytes-matched`. The user returned the unique scratch marker.
**Task 2's real hosted native read gate is now passed.** It uses the account's existing
current model without an observed catalog or an invented model name. Existing
WebSockets opened before attachment are not retroactively observable; additional handoff/recovery,
desktop Send/Stop/attachments/recovery, packaging and final branch review remain uncovered.

## Durable Send and reply custody

The host now records queue/claim/dispatch before granting the companion one native Send.
Atomic, versioned profile-local records include the exact host binding and native baseline;
file contents are flushed before replacement. Unsupported/corrupt state refuses work.
Same-operation changed text/owner and reused native user receipts are rejected. A lost
acknowledgement or restart becomes uncertain and never earns another click. Stop intent
is fenced in the ledger; actual browser generation/ToolHost Stop integration remains Task 6.

The companion uses CoS's native editor insertion/control/acceptance rules. It preserves a
human draft, refuses a busy page, waits briefly for the actual control to enable, and spends
page custody before clicking. Only a fresh exact native user row supplies acceptance.
Final completion requires that user's exact conversation/turn and a terminal public answer;
commentary, private analysis, quiet time and unrelated replies cannot settle it. Both classic
message objects and the current typed shell are covered. An owned public widget fallback
preserves authored Markdown and code escapes. No guessed Enter or automatic model change
was added; delivery currently inherits the chat's existing model.

The new store/delivery files first failed for missing modules. HTTP Send authorization then
failed against the read-only-only bridge before its command paths were added. Reload
readback and typed-shell projections each had their own observed RED failures, then GREEN.
Latest affected suites: **57/57 passed**, 8623 ms. Real isolated Chromium tests send once,
read an accepted native user and exact final independently, preserve busy/human drafts,
handle delayed control readiness, lose an ACK, reopen the ledger, reload/hydrate the page
and finish reading the same turn with exactly one accepted question. Native hosted read
is separately proven above; these delivery pages are fixtures, not the user's account.

The desktop build exited 0 (`built in 6.25s`); both live local protocol checks still pass:
`realHttpPairing:true,attributedLocalReadMatched:true,disconnectRefusedTools:true` and
`actualIsolatedChromium:true,realHttpStream:true,exactJoinReadMatched:true,`
`originalResponsePreserved:true,disconnectedCallRefused:true,elapsedMs:388`.
Both explicitly report `hostedChatGpt:false`. The existing account proof remains the
separate actual hosted read above. `git diff --check` passed.

The existing proof runner remains read-only scratch and contains no Send controller.
Desktop provider routing and an actual account desktop Send are the next gate; no desktop
provider, full Stop, attachment or packaged shipment claim is made at this checkpoint.
Known limits: 64 Ki characters/public final projection (oversized answers stay unsettled),
explicit model changes are refused, retained unchanged draft residue needs user clearing,
and file fsync/atomic replacement does not establish machine-power-loss durability on all
filesystems. Existing socket interception and packaged recovery remain uncovered.

## Desktop provider and actual account round trip

ChatGPT Browser is now an explicit desktop provider. Selecting it starts no browser or
tunnel and requires no API chat credentials. Connect attaches one teammate/workspace to
the user's existing Chrome conversation. The settings panel uses the desktop's existing
theme, displays the current ChatGPT model honestly when its name is unavailable, and
offers the companion folder and a private owner-only pairing link. Browser Send bypasses
API bootstrap and Agent; public native progress/final receipts drive the existing chat
events and SecretHistory. Browser token/cost usage remains unknown.

Provider routing/settings and progress each failed their new regression first. The
isolated real Electron/Chromium verifier then reported `sends:1,acceptedUserRead:true,`
`finalReceiptRead:true,desktopReplyMatched:true,savedHistoryMatched:true,turnEnds:1,`
`inventedUsage:false,rendererErrors:[],hostedChatGpt:false`. Its connection UI screenshot
was inspected. The pre-account serial suite passed **1280 tests, 1279 passed, 0 failed,
1 existing Windows/POSIX skip**, 675713 ms. Both full renderer CSP surfaces mounted
without errors.

The user's actual account sent instantly, but native delivery remained dispatched.
CoS has a third public projection, `props.turn.items` on search units; our focused port
had covered only classic `turn.messages` and typed `entry.turn.items`. Adding that
projection recovered the original exact user/final without another Send. Its answer
comparison exposed a second bug: the search-unit final contained only a ChatGPT widget
reference. That is not answer text. Both typed layouts now resolve only their own DIL
public fallback; missing, contradictory or oversized fallbacks remain unread. Two new
reader regressions first failed then passed. A real isolated search-unit Send fixture
also records its exact unescaped widget answer with one click.

A fresh check used the already paired actual ANKITA test window and real saved ChatGPT
conversation. The safe trace was `actualElectron:true,hostedChatGpt:true,sends:1,`
`finished:true,replyMatched:true,historyMatched:true,turnEnds:1,errors:0`. The original
question was not replayed. No private URLs, account transcripts or marker bytes are
recorded here. The earlier development-profile completion contains the unresolved
widget reference and is not counted as a successful answer; the fresh check is the
successful account gate.

After both reader fixes, the combined provider/settings/startup/delivery/ownership
checks passed **96/96**, 21755 ms. The desktop build exited 0 (`built in 6.38s`)
and `git diff --check` passed. The full suite above preceded these final reader
fixes; the final whole-branch serial run remains Task 7's gate.

The standalone desktop native tool gateway/tunnel, tool cards and pointer are Task 5.
Actual browser generation Stop, attachments and restart recovery are Task 6. Packaged
resource verification and the final whole-branch review are Task 7. The existing API
provider remains tested. This checkpoint does not claim a released EXE or complete
browser tool/Stop support.

## Native tools, Stop and recovery checkpoint (2026-10-13)

Tasks 5 and 6 now implement three native tool surfaces, exact full host binding
joins and durable action receipts. A lost socket does not discard a committed
write; an uncertain action is never executed again. Task browser discovery and
direct targeting refuse the selected model page. The isolated browser path was
run live; the connected Chrome backend contract was stub-driven.

`test/desktop/chatgpt-browser.test.mjs` reports
`NATIVE_LOCAL_ACTION_PROOF {realHttpMcp:true,exactOwnership:true,`
`writeEditReadback:true,commandDone:true,exitCode:0,hostedChatGpt:false}`.
`test/integrations/chatgpt-tool-ownership.test.mjs` reports
`NATIVE_IMAGE_PROTOCOL_FIXTURE {realHttpMcp:true,nativeImagePreserved:true,`
`freshTargetReadback:true,pointerSessionOwned:true,approvals:0,`
`actualCuaDriver:false,hostedChatGpt:false}`. Neither trace is a hosted screenshot
or actual Cua action proof. The later combined desktop/native/attachments
checks passed **21/21**, exit 0, 13461 ms. The helper/desktop focused set passed
**16/16**, exit 0, 6714 ms.

Stop fences the epoch before another dispatch and retains one owned remote
Stop grant. Reproductions exposed a false confirmation from button disappearance,
a still-running background job, a pending approval shutdown deadlock, and
transport cleanup skipped after cancellation errors. Their regressions failed
then passed. Fresh setup under an already stopped binding also reproduced a
late helper launch; it now starts zero helpers. Actual isolated page checks
refuse a newer human turn and never click Stop twice. Only the exact owned
terminal receipt confirms Stop.

An encrypted pairing restores the same selected tab/host binding and remembered
loopback address with fresh observation required. Unsent queued work is rejected;
accepted or uncertain work is read without another Send. Explicit Resume imports
one saved reply. A regression exposed desktop history normalization stripping
its receipt ID and duplicating import; desktop metadata preservation now fixes
that while default API normalization stays unchanged. Explicit Disconnect is
remembered. Native action helpers do not launch during restart recovery.

Uploads reuse the desktop bounds, MIME handling and secret scrubber. The native
composer waits for exact new owned attachment tiles, no busy/progress state,
and enabled Send; old same-name or substring tiles and extra human files are
refused. An upload's longer wait refreshes the same selected page before its
one authorization. Extracted documents are named text uploads. English semantic
quota/authorization/refusal/model/transport alerts block without account/model/
conversation changes, while quoted user alert text does not establish a limit.
The relevant upload/bridge/reader set passed **30/30**, exit 0, 3944 ms. The
handoff includes objective/project, actual admitted results, unresolved receipts
and corrections and copies only on explicit user action.

Windows resource preparation verified the official publisher archive and both
helper members, included all **five** publisher notice/inventory files, and
executed no binary during preparation. Runtime also checks both hashes before
a credential-bearing child starts. Independent Sonatype scanning was unavailable.
The package copies the extension and native helper outside ASAR and includes
services and source provenance inside ASAR. A new builder test reproduced vendor
helper signing that would invalidate those pins; metadata-generated signing
exclusions now preserve both publisher binaries and still sign ANKITA. Resource
and complete main/island CSP checks passed **3/3**, with both renderers mounted
and `errors:[]`; the signing/resource pair subsequently passed **2/2**.

`npm run desktop:pack` exited **0**, desktop renderer built in **4.26 s**, and
created the local Windows app directory. Both packaged helpers matched publisher
hashes and all notice files were present. This is a local app directory, not a
published installer.

The actual packaged executable was run with an isolated profile and native-DOM
browser using `scripts/verify-chatgpt-browser.mjs --executable <owned executable>`.
Its safe trace exited **0** and reported `packagedApplication:true,`
`attachmentAccepted:true,actualOsEncryptedPairing:true,samePairingRestored:true,`
`crashResumeWithoutReplay:true,resumedReplyImportedOnce:true,`
`nativeHelpersLaunchedOnRestart:0,ownedStopClicks:1,nativeStopConfirmed:true,`
`userBrowserSurvived:true,lifecycleSends:3,rendererErrors:[],hostedChatGpt:false`.
The abrupt exit affected only the isolated test app; its independent browser
survived and its accepted question was not sent again. Original user/CoS settings
were untouched. The first final serial regression subsequently exited **1**:
**1324 tests, 1320 passes, 3 failures, 1 skip**, 851256 ms. Two unprotected
Playwright target regressions and a process-preview verification failure were
reported. After conditional protection and duplicate-tunnel guards, the affected
desktop/native/browser/process serial set passed **60/60**, exit **0**, 48060 ms.
The process test was unchanged and passed on that rerun; a final full rerun is
still required.

Hosted native routing reproduction: all three configured tool groups shared one
tunnel ID. Actual receipts recorded `find_tools` and `run_command` on
`surface:desktop,isError:true` with the unavailable-surface refusal. Only the
owned Desktop/Plugins helpers were disconnected; Core remained connected.
The next hosted request produced successful Core `write_file` and `edit_file`
receipts, but later calls returned `CONFLICT: Receipt payload changed`.
A safe native ingress-shape probe subsequently measured the same generation root
and JSON-RPC ID **0** for `list_dir` and `run_command`, while the full native
request IDs differed. The generation root remains the exact conversation join;
the complete transport token plus RPC ID now distinguishes admitted calls.
The new regression failed **409 versus expected 200**, then passed. Exact retries
still share a receipt, changed payload under the same full identity is refused,
and a different full call token can repeat an intentional action. Old
generation-wide receipts refuse upgrade replay instead of being re-executed.
The combined desktop/gateway/ownership set passed **27/27**, exit **0**, 25322 ms.
Malformed and oversized native call tokens are refused before execution.
Tunnel/Stop/packaging/gateway checks subsequently passed **21/21**, exit **0**,
20016 ms. These tests still do not establish the hosted multi-action gate.

The updated local Windows app directory packaged successfully. An independent
ASAR/source check matched **five** changed source modules, both publisher helper
hashes and all **five** publisher notices. Only the owned test app was restarted;
normal quit drained its helpers. A verification script first used POSIX archive
member paths against the Windows ASAR API and was corrected to use detected
platform path normalization. No production packaging workaround was added.

Remaining gates: the product's real account Core/Desktop connections, actual
hosted screenshot → fresh target action/readback, hosted Stop and attachment/
restart checks, full serial suite result, final fresh whole-branch review and
integration into `ankita`. A separate packaged test window is open for manual
account setup and sends **zero** messages automatically. No browser integration
PR, merge, installer publication or completed Task 5/6/7 claim has occurred.

## Hosted multi-tool completion and discovery follow-up (2026-10-13)

The native job-status request initially arrived during a brief `observing` page
state and returned `FORBIDDEN: Request owner is unavailable`. A regression
reproduced immediate refusal instead of waiting for the same selected binding.
The resolver now uses its existing bounded wait and readiness predicate; changed
bindings, blocked states and historical requests remain refused. The affected
freshness/bridge/gateway/ownership set passed **42/42**, exit **0**, 17984 ms.

The rebuilt packaged application completed the actual hosted Core gate. Safe
trace: `actualPackagedElectron:true,hostedChatGpt:true,sends:1,finished:true,`
`fileReadbackMatched:true,replyMatched:true,turnEnds:1,errors:0`. It admitted
`write_file,edit_file,read_file,run_command,job_status,find_tools,job_wait`.
Independent native receipts proved `actualChildDone:true,exitCode:0,`
`outputMatched:true,nativeStatusReceipts:2,replyMatched:true`; both checks exited
**0**. The ordinary file/command permissions were completed by the human.

The next full serial run exited **1**: **1328 tests, 1326 passes, one failure,
one skip**, 915820 ms. The unchanged skill-scaffold rollback test failed under
that run's load; its isolated recheck passed in the 42-test affected set. This
is an outstanding full-suite finding, not a claimed green result.

The account had installed only ANKITA Proof, despite three connected ANKITA
tunnel cards. The human created ANKITA Desktop on its separate tunnel. Native
`mcp__ankita-computer__list_windows` reached the actual driver with **zero**
approval requests. The first owned WinForms fixture had no visible window and
was corrected in ignored test code. A subsequent session-ended driver error
was left stopped until the human explicitly stopped and reconnected it.
This is not yet a screenshot/action proof.

Core discovery previously claimed Desktop tools were callable while its own
MCP interface excluded them. The regression failed before using the same private
host interface set for discovery and execution. Focused host/gateway/ownership
checks passed **25/25**, exit **0**, 8937 ms. Ordinary API discovery, tool loop,
browser focus/protocol/skill and MCP context/store checks subsequently passed
**106/106**, exit **0**, 75914 ms, including real isolated and local browser
round trips. Final packaging and full-suite verification of this change remain
pending at this checkpoint.

The next serial log reported **1331 tests, 1330 passes, zero failures, one
skip**, 835255 ms; its runner exited **0**. The unchanged scaffold rollback
passed. This precedes the driver lifecycle follow-up below.

The current source packaged successfully with renderer build **8.49 s**. Its
ASAR independently matched **10** changed source files, both pinned publisher
binaries and all **five** notices. The refreshed isolated packaged lifecycle
again exited **0**: encrypted pairing/restart matched, explicit resume imported
once, attachment accepted, native Stop confirmed with one click, three Sends,
zero restart helper launches and `rendererErrors:[]`. This is a native-DOM
fixture, not a hosted account Stop/upload/restart claim.

An unaccepted owned test was cancelled: `remoteStop:confirmed,`
`nativeHelpersClosed:true,otherApplicationsClosed:false`. A non-production
diagnostic listener briefly consumed observation bytes before the application;
it was removed and replaced with an iterator-preserving trace. The affected
claimed request was cancelled without Send replay. The user then removed their
unrelated composer text, which had correctly caused the next Send to be refused.
After refreshing the same ChatGPT chat, an exact new request root appeared in
companion evidence and the native gateway returned **HTTP 200**. No freshness,
request-ownership or human-draft guard was relaxed.

Actual driver inspection found `list_windows.inputSchema.additionalProperties`
**false** and no `session` property. `get_window_state` supports a named session.
Its owned pointer session read succeeded; the attached implicit session read
returned **isError:true** with the ended-session refusal. Preparing only the
named pointer left strict discovery unusable. A real external-protocol fixture
reproduced that refusal RED, then explicitly initializing the transport's
implicit lifecycle before reserving its separate owned pointer made it GREEN.
The existing stopped-pointer fast path never restarts an ended pointer.
Controller/host/native-ownership checks passed **44/44**, exit **0**, 23339 ms.
The rebuilt hosted Desktop gate and a final full suite after this correction
remain required.

The driver-lifecycle candidate packaged successfully (renderer **12.24 s**).
Independent ASAR/source comparison matched **11** modules, both publisher
helper binaries and all **five** notices. The old isolated app normally quit;
its verified owner exited before the replacement opened. The actual replacement
restored the same encrypted browser connection and reported `automaticSends:0`
with all three native cards `setup-required`. Reconnecting the unchanged,
already approved driver reported `connected:true,pointerEnabled:true,toolCount:25`.
Saved Desktop/Core tunnel connections were reused without entering credentials.

The **actual hosted Desktop vision/action check exited 0**. Exact safe trace:
`actualPackagedElectron:true,hostedChatGpt:true,actualCuaDriver:true,finished:true,`
`nativeImages:5,firstMetadataContainedNumber:false,freshNativeActions:2,`
`actualUiMatched:true,actualButtonClicks:1,replyMatched:true,approvals:0,errors:0`.
The eight calls were `list_windows`, five `get_window_state` calls, `set_value`
and `click` under the ANKITA computer namespace. The random six-digit value was
drawn only in the fixture bitmap and was not provided in the prompt or initial
accessibility/target text. Independent fixture readback confirmed the textbox
and exactly one Apply click. This closes Task 5's hosted screenshot plus fresh
action/readback gate; it is not a simulated provider or mock driver result.

## Accepted execution after HTTP disconnect

The first hosted Stop attempt exited **1** before issuing Stop. Independent
owned-job readback found both harmless 90-second commands `done:true,`
`stopped:false,exitCode:0`; no Stop completion is inferred. One native receipt
said `admission ended without an execution receipt` while its command later ran.
The SDK's Node adapter returns on socket loss independently of the accepted
tool callback. Gateway fallback settlement had treated adapter return as tool
completion, permanently replacing the later actual result.

The real HTTP/SDK/ToolHost/filesystem regression disconnects while human approval
is pending, then verifies no false result, teardown waiting for accepted work,
the exact written bytes and a durable successful retry with one approval/write.
It failed RED with the same premature error, then passed GREEN after retaining
and awaiting the admitted execution promise. The serial host/gateway/ownership/
Stop set exited **0**, **35/35**, 18375 ms. This is a real disconnected local
transport proof, not a hosted Stop completion claim. Desktop build exited **0**,
renderer **9.29 s**. Initial repack failed with `ENOSPC`; only old ignored test
build directories were removed from the verified worktree before retrying.

## Final hosted Stop, upload and restart checks

The corrected candidate packaged with exit **0**. Its ASAR matched all **11**
inspected source modules, both publisher binaries and all **five** notices.
The subsequent **actual hosted Stop check exited 0**:
`actualPackagedElectron:true,hostedChatGpt:true,remoteStop:confirmed,`
`nativeHelpersClosed:true,ownedCommandDone:true,ownedCommandStopped:true,`
`finalExitCode:1,finalSignal:null,ownedPointerCleared:true`.
The actual Cua `end_session` call for the owned pointer acknowledged success.
The check first observed the actual command PID and its printed marker while
the hosted reply was active, then invoked ANKITA cancel exactly once. A separate
OS check reported `originalUserAppsSurvived:true,checkedUserApps:1,`
`ownedJobProcessExited:true,ownedTestWindowSurvived:true`. The visible original
application was Chrome. This verifies session release, not an independently
measured arrow-pixel disappearance; the native end result exposes `active` and
`session` fields rather than a cursor visibility field.

The first reader in the ignored Stop script captured an as-yet absent job map;
its failed check did not invoke Stop. Reading the current engine map corrected
the test reader, without changing product code. The preceding waiting command
finished normally with exit code 0. The subsequent successful gate above used
a fresh explicitly approved command.

The **actual hosted text upload check exited 0**:
`sends:1,uploads:1,uploadAccepted:true,nativeUserAccepted:true,outcome:completed,`
`exactReplyMatched:true,importedOnce:true,errors:[]`. The unique exact expected
text existed only inside the uploaded file, not the question. Native composer
acceptance, exact accepted user receipt, final content and ANKITA history all
matched.

The **actual hosted abrupt-restart and explicit Resume check exited 0**:
`samePairingRestored:true,originalAcceptedReceiptMatched:true,`
`operationCountUnchanged:true,outcome:completed,consumed:true,`
`replyReadbackMatched:true,userImportedOnce:true,replyImportedOnce:true,`
`newHelperLaunches:0,errors:[]`. Before closing only the owned test app, its
question was `accepted` and unconsumed with an exact native user/turn receipt.
All **three** original helper PIDs subsequently exited. The same packaged app
restored its encrypted binding and read that original response through explicit
Resume; no extra operation or user-history question was created. Chrome stayed
open throughout.

Several preliminary Send/Resume attempts failed before queue/dispatch with the
existing setup-required message when fresh page evidence was unavailable. A
later explicit attempt succeeded. The exact timing cause was not independently
captured, so no new freshness fix is claimed and no automatic retry was added.
These refusals remain a UX finding; accepted questions were never resubmitted.

Final serial Node suite: **1333 tests, 1332 passes, 0 failures, 1 existing skip**,
**1083265 ms**. The PowerShell wrapper saved the actual Node exit immediately
and reported `final-node-suite-exit:0`; the tool also exited **0**. This run
includes the driver lifecycle and accepted-execution lifetime corrections.
Final independent whole-branch review and integration remain next.

## Independent review follow-ups and personal automatic actions (2026-10-14)

The independent reviewer found no critical defects and six important defects.
Each has a regression that failed before the correction:

- Live uncertainty now refreshes Resume in the running app, including later
  observation-only final receipts. Reobserving the exact accepted user after a
  provider block reconciles uncertainty without granting another Send.
- Repeating Observe on the same selected chat preserves its lease/epoch and
  original reply. Selecting another chat refuses unsettled Send, unimported
  completion or unconfirmed Stop custody. Host renewal after settled Stop
  still creates a fresh epoch. Temporary tab disappearance retains custody,
  revokes page authority and allows observation when that same tab returns.
- Native Core neither advertises nor executes `mcp_manage`/`composio` global
  connection management. Discovery and execution share the boundary; API
  behavior and structured workspace/project tools remain available.
- Always allow persists for the browser teammate's live session across host
  replacement, without granting another teammate or changing global defaults.
- Missing/malformed/over-quota images within one native tool result return an
  explicit unavailable visual-state error. Each later native screenshot result
  has its own allowance; API image attachments keep the separate per-generation
  quota and normal API behavior.
- Clear removes cached local browser messages and its checklist while keeping
  running jobs, file changes and spent native receipts intact.

The actual bridge/runtime/ledger/desktop/browser/Stop affected set passed
**65/65**, exit **0**, **19973 ms**. The ToolHost/API-images/browser-protocol
set passed **44/44**, exit **0**, **20779 ms**. Those include real isolated
browser round trips and connected-browser contract fixtures, not account
substitutes. Rebuilt packaging, final full suite and reviewer recheck remain
required after these changes.

The user explicitly requested no repeated ANKITA approval cards. The existing
`AUTO_APPROVE=true` preference was persisted in the normal and owned test
profiles, preserving other settings and credentials; no customer-wide default
was changed. A reopened actual packaged app completed the hosted check with
`sends:1,finished:true,fileReadbackMatched:true,replyMatched:true,turnEnds:1,`
`approvals:0,errors:0`. Its six calls were write/edit/read/command/two job waits.
Independent job receipts confirmed `actualChildDone:true,exitCode:0,`
`outputMatched:true`; both checks exited **0**. This account proof predates the
review follow-up rebuild. ChatGPT's own account/app permissions remain its
separate setup controls.

The reviewer independently reproduced five corrected paths successfully, then
found a remaining selection/Send timing race in the initial sequential guard.
The shared bridge admission queue now serializes selection/tab changes and
durable enqueue, and production Runtime uses that queue. A delayed Stop-custody
read reproduced RED with an old-binding queued operation. GREEN rejected the
losing Send before persistence: `pending:0,oldOperationCount:0,`
`currentOperationCount:0`. The updated affected set passed **66/66**, exit **0**,
**28863 ms**. Independent recheck cleared all six findings; no code-review
blocker remains within that correction scope.

The user subsequently requested a new release. Version **2.6.0** updates both
root manifests, README, release notes and guides, including the earlier merged
computer/skill/scheduling work. Release CI now prepares the pinned native
resources before either signing branch; its packaging regression failed RED,
then passed **3/3**, exit **0**. Dependency pins are unchanged.

The final **2.6.0** Windows app directory built and packaged with exit **0**
(renderer **4.42 s**). Independent ASAR comparison matched **15** source
modules, version **2.6.0**, **two** publisher binaries and **five** notices.
The actual packaged isolated lifecycle check exited **0** again: encrypted
pairing/restart matched, explicit Resume imported once without replay, upload
accepted, one native Stop confirmed, browser survived, no new restart helpers,
three lifecycle Sends and `rendererErrors:[]`.

The final rebuilt **actual hosted** Core check also exited **0**:
`sends:1,finished:true,fileReadbackMatched:true,replyMatched:true,turnEnds:1,`
`approvals:0,errors:0`. Six calls completed: write/edit/read/command/two waits.
Independent current-operation receipts proved `actualChildDone:true,exitCode:0,`
`outputMatched:true,nativeStatusReceipts:2,replyMatched:true`, exit **0**.
The diagnostic reader excludes older same-binding jobs by the operation's
dispatch time; its earlier aggregate mixed reused job IDs from old questions.
That was a test-reader issue, not a changed product receipt.

The final full serial suite used a separate temporary config directory,
preserving the user's saved automatic-action preference. It exited **0**:
**1345 tests, 1344 passes, zero failures, one existing skip**, **552428 ms**.
The wrapper captured the actual Node exit immediately; the tool also exited
**0**. This covers all six corrections, admission serialization and release
resource preparation. The source passed the introduced-literal audit and
`git diff --check`; only code/tests/docs/manifests are staged, with no generated
media, dumps, keys, profiles, native binaries or local release builds.
Final integration, exact-commit remote workflow and installer publication
remain pending at this checkpoint.

## First merged release runner and line-ending regression

PR #65 merged at `a373165d75b01103792b6ec428226ea82063ac05`; the original
checkout fast-forwarded to it. Seventeen local source edits were preserved,
including clean three-way merges of its local changelog/workflow edits; their
original bytes and two older untracked plan copies were retained separately.
The merged tree matches the checked feature tree exactly.

Release run `38500981836` stopped before publication: **1345 tests, 1333 passes,
one failure, 11 skips**, **333674 ms**. The only failure was the signing-policy
test's LF-only regular expression, which returned empty exclusions on Windows
CRLF checkout. Adding a CRLF variant reproduced its exact `true !== false`
failure locally. The test now parses the same YAML with the builder's existing
locked parser, exercises both LF and CRLF, and still invokes the real
`WinPackager.shouldSignFile` for publisher members and ANKITA's executable.
It passed **3/3**, exit **0**, **1898 ms** after correction. Production code,
package configuration, dependency pins and signing assertions are unchanged.
No test was skipped or relaxed to publish. The final corrected merged commit
must complete the full release workflow before the release is claimed.
