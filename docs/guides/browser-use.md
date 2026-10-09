# Browser use

Ankita can open and interact with real web pages. The browser tool is loaded on demand with `find_tools("browser")`, so ordinary conversations do not pay for a browser schema on every request.

## Browser instructions

Interactive desktop and CLI chats include the [browser-use skill](../../skills/browser-use/SKILL.md).
Initially the model sees its name and description. Accepted browser discovery or an
actual browser call loads the full guide into the next model request, once in the
system prompt for that turn. There is no extra router, skill-tool call or memory
handoff. When browser tools remain advertised from earlier discovery, matching
instructions now load before the first model decision of the next turn, including
short continuations. This can also include a conversational turn while the browser
remains available. The stored turn prompt is cleared at turn end and rebuilt for
the next request; raw observations remain in the transcript. Automatic loading is
prompt delivery, so it does not require a separate visible skill-tool card.

The desktop header now shows **Instructions loaded: browser-use** when the whole
automatic body is present in a prepared model request after history trimming.
The engine emits the names once per turn; it does not add a model round or copy
the guide into chat. This is evidence of request inclusion, not proof that a
provider followed the instructions. Disabled, omitted and stopped-before-request
guides do not produce this status. The next turn and clearing the thread reset it.

When running from source, restart `desktop:dev` after engine changes. Its Vite
watcher refreshes the renderer; it does not reload Electron's imported agent or
browser adapters. For `desktop:start`, run `npm run desktop:build`, then relaunch
`npm run desktop:start` to use the current renderer and main-process source.

During active browser work, a model may print a standalone `[Tool call: ...]`
and JSON object (on the same or following line), or a browser-form markup block
with JSON fields, instead of returning a native tool call. Ankita asks it to correct
that once within the existing step budget. The printed JSON is never executed,
and the correction says not to replay completed writes. Repeated proposals or
an exhausted step budget stop with `invalid_tool_protocol` and unfinished work.
Ordinary replies take no extra round. Quoted/fenced examples, malformed proposals
and explanatory turns without a browser call in that turn stay ordinary text.
Scheduled workers retain their existing broader printed-marker check. A final
tools-free writer that proposes more actions cannot report those actions as done.

Disable it in **Plugins → Skills** to disable both automatic and manual reads.
Standalone non-chat agents continue without skills. Browser focus retains the
read-only `skill` tool when skills are enabled; it still refuses discovery of
unrelated groups until an explicit `scope:"general"` switch.

The guide covers exact browser discovery, automatic enabled-backend selection,
fresh refs, editable-only form batches, avoiding redundant snapshots/screenshots,
checking actual outcomes, and recovering without duplicate mutations. It adds
instructions, not a guarantee that every provider follows them. The lab can compare
it with `--browser-skill on|off` and records actual automatic activation.

Long tool loops retain up to three recent user requests, including short follow-ups
such as "use browser", so the original goal and corrections do not disappear solely
because many tool messages were added. Prior request anchors share a 4,096-byte
bound and yield under actual context pressure; this is bounded history preservation,
not a new router or guaranteed permanent task memory.

For flight searches, the guide requires confirming origin → destination, airport
codes, trip type and exact date before Search and again on results. Autocomplete
typing alone is not selection: use each airport's observed picker and commit its
option separately. Native `select` accepts HTML select controls; custom trip-type
menus require clicking the menu and its observed option. A malformed action string
is refused with native JSON recovery guidance. Find page buttons with targeted
browser snapshots, not filesystem search. Results stay open unless closing was
requested, and search results are never reported as a booked ticket.

If Playwright detects first-field replacement after form preflight but before
dispatch, it returns a fresh snapshot as a zero-write reference failure. Once any
field actually starts dispatching, partial-batch handling remains conservative:
inspect values and never replay the entire batch automatically.

Independent mixed `batch` steps can combine `fill_form` with clicks, fills and
native selects using distinct refs from one observation on the same backend/tab.
Before the first edit, a read-only live target check resolves every original node
and checks its current state. Each later step rechecks its targets. Intermediate
full snapshots are deferred so they do not invalidate the remaining original
bindings; the final step returns the fresh snapshot. Replaced, hidden, disabled,
inert or covered targets stop the batch with observed recovery refs. This is
checked execution, not rollback: completed earlier steps remain completed.

Duplicate refs, navigation, keyboard/drag operations and mixed tabs/backends keep
ordinary per-step behavior. Dynamic autocomplete should use separately observed
steps. A ref segment is not a tab ID: omit `tab` for the current page or copy its
ID from `tabs`. Split forms at the advertised field limit and use each returned
snapshot for the remaining fields. This batch repair works with runtime V2 on or
off and does not require an experimental flag. See the
[desktop and batch evidence](../browser-use-reference-findings.md#desktop-guide-visibility-and-mixed-form-batches--9-october-2026).

Authors may opt a built-in skill into discovery/use with comma-separated native
tool identifiers in `auto-tools`. This is separate from the display-only
`suggested-tools` hint. Automatic instruction blocks have a shared 6,000-character
budget per turn; complete bodies that do not fit remain available for manual reads.
Disabled skills and rejected discovery never load an automatic body.

This follows the progressive-disclosure pattern described in [OpenAI's skill guide](https://learn.chatgpt.com/docs/build-skills).
The instructions are adapted to Ankita's own tool contract from [Playwright's snapshot guidance](https://github.com/microsoft/playwright.dev/blob/main/mcp/snapshots.mdx)
and [Anthropic's tool-design guidance](https://www.anthropic.com/engineering/writing-tools-for-agents):
use current observations, make parameter choices unambiguous, and evaluate task
success together with rounds and runtime. Ankita's refs bind an observed control
to its backend, tab, frame and document. Playwright additionally checks the actual
observed node; an identically named replacement cannot inherit an old ref. After
replacement, use the fresh observation returned by recovery. Guessed labels or
selectors cannot establish that identity. See [the repair evidence](../browser-use-reference-findings.md#current-browser-repair--9-october-2026).

## Page text and execution receipts

Snapshots use shared control and text limits. A limit notice means controls or
context were omitted; narrow a snapshot by its label rather than guessing a
ref. Chrome preserves native UID-looking text inside labels as page data.
Playwright also preserves hidden/inert ancestry and semantic groups across
open shadow roots. Missing backend identity/actionability information remains
unknown; it is not proof that a control can be used.

Controls are rendered as Markdown lists with opaque refs and semantic groups.
Visible controls can carry `covered`, `offscreen`, `inert` or `hidden` flags.
Dismiss an observed overlay before using a covered control; expand a disclosure
through its observed summary ref. Chrome enriches at most 16 native targets per
snapshot to bound UID resolution work. Other controls retain unknown state;
targeted `snapshot(query=...)` requests can inspect a later control.

Use `browser(action="find", query="literal page text")` to locate visible text beyond
the first read chunk. Matches include their source URL and character ranges. Search
is literal and bounded; it does not invoke a second model. A limit notice means
more content may exist outside the captured source.

`read` returns Markdown headings, paragraphs, lists, links and basic tables from
the loaded DOM, including open shadow-root content. Use `filter:"all"` on `read`
or `find` to include labelled hidden DOM text, including closed disclosures.
That text is read-only evidence, without action refs; it may describe content
that is unavailable in the current UI. Scripts, styles, templates and form values
are excluded, including SVG script/style nodes. Reading does not dismiss overlays
or expand a section. Ordinary reads include text behind overlays when it is in
the loaded DOM; control flags distinguish whether it can receive interaction.

For longer reading, use `read` with `start` and `length`. Repeat the same `filter`
setting and continue using the returned
`observation_id`; changed page text or selected tab refuses continuation. Playwright
also invalidates cursors on document reloads, including identical text at the same
URL. Offsets use UTF-16 characters. Playwright can capture bounded frame text;
Chrome's approved MCP helper currently reads the main document only and cannot
prove document identity across an external identical reload. Unloaded content,
closed shadow roots and text drawn only in canvas are not extracted by this DOM
reader; visual information still uses the screenshot path. Node/depth/source and
chunk budgets disclose omissions instead of returning an unlimited HTML dump.

`BROWSER_RUNTIME_V2=on` enables experimental internal execution receipts. It defaults
off while broader rollout checks remain open. A completed action is separate from
verification of the user's goal. A timeout after dispatch can be uncertain: inspect
the current page instead of repeating a possible write. Numbered partial batches
are failures, and their failure evidence survives request history projection.

Experimental Playwright snapshots also return an `Observation` ID. `sequence`
accepts that ID and related `act` fill/select steps, followed by an optional final
click/press. It binds the original controls, rechecks the form before each write
and returns one final snapshot. A replaced control, changed form, new tab,
navigation or Stop halts the remaining steps. Receipts preserve completed work;
inspect the current page before continuing a partial sequence. Submission or a
dialog boundary must be the last step. Chrome reports guarded sequences unsupported
until its UID/document guards have live proof. Primitive operations count toward
a separate per-turn ceiling derived from the existing tool-call budget.

Playwright rechecks related controls inside open shadow widgets, including
inherited hidden/inert state and the current form/group owner. A change outside
that owner does not interrupt an unchanged widget. Oversized form or ancestor
probes refuse the sequence with guidance to use individual actions and fresh
observations; increasing the model's step budget does not expand this probe.
Stop is rechecked at the native action boundary after metadata inspection.
Completed field edits remain partial progress; a cancelled response does not
mean an already dispatched submission was undone. Inspect uncertain writes
before continuing rather than resubmitting them.

`BROWSER_EVIDENCE_RETENTION=on` retains bounded captured quotations and their URLs
when request history is compacted. `BROWSER_PROGRESS_TRACKING=on` detects unchanged
observed state even when refs change and supplies bounded read-back guidance.
Both default off and consume structured runtime results. Oversized quotes are
refused with a visible limit notice; use targeted find/read instead of relying on
clipped facts. Progress changes do not independently verify the user's goal.

Use `navigate` to change the requested tab, and `back`/`forward` for native history.
These invalidate old refs and reading cursors. Chrome history under a navigation
policy refuses a destination it cannot prove; use an approved explicit URL then.
Chrome's native failure receipts are failures rather than successful navigation.

## Set up a browser

Open **Plugins → Apps → By Ankita team**, then select a browser to open its settings. Both choices start off:

- **Playwright Browser** runs a separate Chromium profile. Enable it, then use **Download Chromium** if the card says setup is needed. The download is roughly 310 MB. **Run in the background** keeps the browser window hidden while the live stage shows its page.
- **Chrome local** uses the pinned `chrome-devtools-mcp` server over Chrome DevTools Protocol (CDP). Enable it and choose **Private Chrome**, **Debug port**, or **My session**. Ankita starts the connection when a browser request needs it; **Start connection** also lets you test it in advance. The first connection asks approval for the exact server command. That approval is remembered for the same command, including reconnects. **My session** also requires Chrome 144 or later, remote debugging enabled at `chrome://inspect/#remote-debugging`, and Chrome's permission dialog when it attaches. **Debug port** attaches to a Chrome instance already listening on the selected port; **Test port** checks the connection before starting. [Chrome's connection options](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/configuration.md) explain the upstream behavior.

Chrome's private profile is the least privileged local option. **My session** can see your existing tabs and sign-ins, so use it when a task needs them. Chrome shows its own control banner while attached. The Chrome MCP server is kept behind Ankita's single `browser` tool; its diagnostics are not offered to the agent by default.

In desktop chats, external Playwright/Chrome MCP browser tools are excluded from
discovery, prompts and model schemas. Calls carried over from an old conversation
are rejected before execution and load the built-in `browser` tool for recovery.
Other MCP integrations remain available. Browser tabs and refs always belong to
the selected enabled built-in backend.

Enabling a card records the choice. A disabled browser is never selected. With both enabled, a new session prefers Playwright, then keeps its current enabled browser. Disabling Chrome makes the next page open use Playwright; old Chrome tab IDs and refs must be replaced with a fresh page and snapshot. Plugin choices are stored in `~/.copilot-chat-cli/browser.json`. Playwright's browser profile lives under `~/.copilot-chat-cli/browser/playwright/`.

## Use it

### Secure sign-in

For a password sign-in, the desktop agent uses `browser login` with the actual
login URL (or a page already open at the website's exact origin) and an optional
username. Open the site's real login page first if necessary; Ankita does not
invent login routes. Never paste passwords into chat or memory. The **Secure
store** card's **Add** button opens the secure dialog, where you enter the username
and password and choose whether to save them. Website is fixed to that request.
**Enter** resumes the same browser call. A request without fields returns a
snapshot and confirms that credentials are available privately; no form detector
or particular button name is required to open the dialog.

Saved accounts are scoped to the exact origin, including scheme/host/port; a
different subdomain does not inherit credentials. Multiple saved accounts require
an explicit username or fresh input. Only usernames, website, timestamps and
`hasPassword` appear in **Plugins → Saved sign-ins**, where Remove deletes a record.
Encryption uses Electron's asynchronous OS storage in the main process. Windows
DPAPI protects against other users, not other programs running as you; macOS
Keychain needs consistent application signing across updates. Linux's plaintext
`basic_text` fallback is refused. If secure encryption is unavailable, saving is
disabled; you may use credentials for this sign-in only or take control manually.
The vault is local to this machine and does not sync.

Only isolated Playwright supports this helper. Chrome uses its own signed-in
session/manual login; CLI and Telegram cannot access the vault. Login needs a
separate tool call so its secure card can receive input. The model selects refs
from the snapshot using `credential_fields: [{ref, credential: 'username'},
{ref, credential: 'password'}]`, with an optional `submit_ref`. No plaintext is
supplied in these arguments. All targets are bound and validated before filling;
password slots require password inputs, and origin/form-action checks prevent
cross-origin and native GET password submissions. Button labels and form layouts
are chosen from the actual page by the model.

Username-first screens use one login call to fill username/Next and another for
the subsequent password ref. Unsaved credentials stay private in the main process
for that thread/origin/tab/page until password use, Stop, turn end or expiry.
Calls return **Selected controls filled** and a snapshot, not a claimed login
success. The model inspects the resulting page, handles further steps and resumes
the original task when the page confirms it. A changed control returns fresh refs
to the model without automatically retrying credentials. For a wrong password,
the model may request the secure dialog again. Take control supports CAPTCHA/2FA;
Hand back returns the observed page for the model to inspect. Escape/Cancel or
Stop settles the wait without another fill. A prompt expires after thirty
minutes. Passwords exist briefly in
the input DOM and main-process fill callback; JavaScript strings cannot promise
secure memory erasure. They are never returned to the model or persisted in chat.

### Page interactions

Ask Ankita to open a site, inspect it, and perform a task. `open`, `act`, and `fill_form` return the current snapshot with `[ref=…]` element references. Copy the opaque ref verbatim; a DOM ID, selector, accessible label, or role name is not a ref. Use the returned controls for the next action without taking another snapshot. A successful action whose follow-up snapshot fails still reports success: inspect the page before proceeding rather than repeating the action.

Playwright observes a blank document for visible content before returning the
first snapshot. HTTP refusals (such as 403) or an empty page that does not render
produce **Needs attention**, not **Ready**. Repeating snapshots does not bypass a
refusal. Use an approved local Chrome session or manual control when the website
rejects a background browser; no automation can guarantee acceptance by every site.

Snapshots replace the previous refs. Navigation, switching tabs, and takeover invalidate them. Playwright can follow a uniquely matching accessible control after a re-render within the original frame; ambiguous replacements are rejected. An invalid ref returns an error with a fresh snapshot when available, without executing the requested mutation. Use the new ref from that output. If a snapshot omits a control because of its size limit, request `snapshot` with a `query` matching its accessible label. Playwright includes visible controls in child frames and open shadow roots, along with values and relevant states; password values are hidden.

Use `fill_form` with up to ten `{ref, text}` entries to fill several fields from one snapshot. All refs are checked before filling begins, and the response includes the next snapshot. Playwright supports text fields, selects by option label, and checkboxes/radios using `"true"` or `"false"`. Chrome delegates form filling to its native MCP tool. A later field failure can leave earlier fields filled; inspect the reported state before continuing. The tool also supports page text, tabs, screenshots, closing a tab, and batches of up to ten steps that stop at the first error.

Use `fill` to replace a field's value and `type` to insert text at its caret. A `press` action targets its supplied ref; Chrome focuses that registered control without clicking it before sending the key. If the control cannot receive focus, the key is not sent. Chrome typing reads the next snapshot after the keyboard action because its native typing tool does not accept `includeSnapshot`.

Screenshots are saved under `downloaded-images/` in the current workspace and returned as structured receipts. During an agent turn, valid captures are attached as PNG image content to the next model request using the existing user-image format; tool messages remain text. Attachment requires a vision-capable model and available context space. Captures are limited to 15 MiB each and three automatic images per turn, and workspace boundaries, file type, byte count, and PNG signature are checked. `read_file` remains a text reader; use the screenshot attachment or desktop artifact to view pixels.

The desktop **browser stage** opens beside chat during a run and collapses the left sidebar to give the page more room. It shows the current tab and URL, a live page preview, and **Stop** and **Take control** actions. Take control pauses Ankita's next browser action. In the Playwright stage, click, type, paste, or scroll on the preview; press `Esc` or **Hand back** to resume. With Chrome local, interact in Chrome itself and then hand back. `Ctrl/Cmd+Shift+B` toggles the stage. The composer Stop cancels pending browser calls, including requests paused for takeover or setup approval. Closing the stage stops the browser run and disconnects Chrome's MCP connection; the next Chrome request can reconnect automatically.

The visible preview targets 10 updates per second with one request in flight. Chrome returns image data directly through MCP, without a temporary screenshot file. Tab metadata refreshes every two seconds. Hidden panes/windows and lost connections refresh less frequently. Recoverable page/action errors keep the live preview and Take control available. Live frames update the browser pane independently of the chat; the chat thumbnail refreshes every two seconds. Actual FPS depends on page complexity and Chrome's screenshot latency. Run `node scripts/verify-browser-automation.mjs` for a disposable local form, screenshot, cancellation, reconnect, and animated-page benchmark of both backends. The verification scripts use the shipped, pinned Chrome MCP executable and never download a package.

Progress shows thinking, reading, acting, checking, recovery, waiting for you,
stopped, and finished phases, with completed primitive counts for a form sequence
or batch. A completed step does not independently verify the entire task.
Recoverable reference errors mean Ankita could not locate the requested control;
they do not prove the website changed. Their notice is quiet and keeps the page
preview available. Connection and navigation failures retain attention warnings.
Native window visibility also throttles preview capture while minimized or hidden,
even when the renderer's Page Visibility API still reports visible.

Experimental native page dialogs appear in the live panel with an explicit
Dismiss/Continue decision and optional prompt reply. Deciding takes control;
Hand back resumes the next model browser action. The last good frame remains
visible while a dialog blocks capture. Questions and entered replies are excluded
from broadcast progress and shared thumbnails. Chromium decisions bind the native
dialog event; Chrome's MCP cannot distinguish an identical dialog replaced
externally between probes.

The stage shows short notices for stale controls, page loading and action failures. Fresh snapshots, page code, terminal formatting and call logs remain in tool diagnostics rather than the live pane. Only a lost connection or browser startup failure prompts browser setup. A successful subsequent action clears the notice. A slow preview keeps its last frame and clears its notice when capture resumes.

For a public-site navigation failure, `node scripts/probe-browser-navigation.mjs <url>` compares the actual adapter with HTTP/1, full headless Chromium and visible Chromium using disposable profiles and read-only navigation. It performs no clicks or booking actions. A different transport does not guarantee that the URL exists or that a site accepts automation; inspect the resulting page/status rather than repeating a failed booking step.

## Recovering a connection

Before a Chrome action, Ankita checks the connection. If it was lost, the desktop makes one reconnect attempt and takes fresh refs. It never automatically replays a click or form submission. Chrome requests have deadlines, preview requests time out quickly, and closing the transport rejects outstanding calls. A request that cannot recover returns an error instead of waiting forever. Chrome's own permission dialog remains required when attaching to **My session**.

If a model response stream disconnects or ends without a completion marker, Ankita retries that model step up to twice. Completed tool results stay in context, incomplete tool requests are discarded, and unfinished text is replaced when the recovered wording changes. Stop prevents recovery retries. A provider that repeatedly disconnects still reports an error after the bounded attempts.

In the terminal, use `/browser list`, `/browser enable isolated`, `/browser disable isolated`, or the same enable/disable commands with `local`. Chrome connection setup is in the desktop Plugins page.

## Packaged desktop verification

On Windows, run `npm run desktop:build`, then `node scripts/verify-browser-desktop.mjs`. The verifier packages the installed Electron distribution into a temporary directory and launches the actual executable with isolated configuration and user data. It checks three appearances, a browser task through the real HTTP/SSE and IPC paths, screenshot pixels in the next request, sidebar collapse, takeover, Stop, shipped command stdin/EOF and exit status, and Playwright's installer `--dry-run`. The model decisions are scripted and the page is a local form; this does not test a live LLM or a real booking site. No packages or browsers are downloaded.

Use `--keep-artifacts` to retain the screenshots and disposable build for inspection. To rerun that exact build, pass `--package-dir <win-unpacked-directory>`; otherwise a fresh archive is built. Keep source files settled throughout packaging so an archive cannot combine incompatible module revisions.

`node scripts/verify-browser-progress-desktop.mjs --developed --keep-artifacts`
checks actual progress events, a deliberately invalid control on a static page,
manual prompt handling, reduced motion, Stop, minimize/quit, and preview cost in
three visibility states. Omit `--developed` to build and check a disposable actual
executable. Native main-process instrumentation measures capture/view work;
one renderer IPC calibration call is recorded outside each profiling interval.
These local scripted-provider checks do not measure real-model browser speed.

`node scripts/verify-browser-automation.mjs` exercises actual isolated Chromium and
the bundled Chrome bridge. The ordinary task page is static: five preview refreshes
must leave its original control ref usable without a warning. A separate animated
fixture checks changing preview pixels. Add `--runtime-v2` to repeat those checks
with experimental receipts; the command does not change application defaults.

`node scripts/verify-browser-vault-packaged.mjs` builds and launches a disposable
actual executable, reproduces the legacy exit-before-initialize failure, then
checks the shipped Chrome bridge with empty PATH/cache and OS-encrypted login
through the renderer/IPC/agent/browser path. It tests cold/warm login, appearance,
keyboard focus, eye toggle, cancellation, explicit retry and takeover. Artifacts
are retained for review. `--package-dir` reuses an exact build. These checks use
local forms and scripted model decisions, not personal accounts or a real LLM.

The Chrome bridge is included in the app and its version is pinned in
`package.json`. The Chromium browser binary remains a separate browser download;
Chrome local requires Chrome installed. First launch after an older npx-based
configuration can ask approval again because the actual launch command changed.

## Site controls

Only HTTP and HTTPS pages can open. Loopback and private hosts are blocked by default; set `ALLOW_PRIVATE_HOSTS=1` when working with a local development server. Open a browser's settings to add allowed or blocked domains. An allowed list limits where it may navigate; blocked domains always win. `BROWSER_ALLOWLIST` and `BROWSER_BLOCKLIST` also accept comma-separated domains (including `*.example.com`). Page content is treated as untrusted. Browser interactions ask for tool approval. Tool cards redact text entered through `browser act`; the live preview shows the page as rendered, including any visible field values.

The isolated browser checks navigation and resource hosts, including navigations initiated by a page. Chrome local uses Chrome's own permission and MCP transport; the app validates explicit navigation URLs. Policy-bound Chrome history refuses an unknown destination. Browsing directly in Chrome remains under the user's control. Arbitrary page JavaScript is not a first-party browser action.

With `browserRuntimeV2` enabled, isolated Chromium keeps native alert/confirm/prompt dialogs open. `handle_dialog` requires an explicit accept/dismiss decision; prompt input is hidden in tool previews. A triggering action that stops at a dialog remains uncertain and is never replayed automatically. Chrome uses its approved native dialog operation and page-specific attention; a global tab list cannot prove a dialog closed. Accepting a dialog does not verify the underlying task's outcome.

Experimental isolated uploads require a current file-input ref and a native desktop file selection. A host may separately allowlist a workspace file; a model-provided path or automatic tool approval grants no file access. Files are bounded to 32 MiB, checked for changes while reading, and supplied as the selected bytes. A tab/document change or canceled selection refuses before dispatch. Selection confirms filename/size; verify server submission separately. Background uploads require foreground help.

Start the isolated session with the experimental runtime to receive downloads. `downloads` reports owned IDs and pending/completed/canceled/failed states; `download` saves a completed file inside the authorized workspace after ordinary mutation approval. Names are sanitized, saves use temporary files, and published artifacts include an existence/size check. `cancel_download` and Stop while waiting abort pending transfers. Native transfers have a 20-second completion deadline; saved artifacts are bounded to 32 MiB. Temporary browser downloads may use more disk space before completion and are removed with the session. Background saves require foreground approval. Chrome transfer capability stays unavailable until its file-root and completion contracts are proven; use isolated Chromium or manual takeover/import.

## Current limits

Artifact copying checks its byte bound before each chunk is written and refuses
symlink/junction sources or source identity/size/modification changes before
publication. A growing or replaced source leaves no published file. The actual
native-picker verifier is `node scripts/verify-browser-file-picker-desktop.mjs
--scenario select|cancel|stop`; it requires a native operator to choose only its
generated local file or cancel, and an `operator-finished` marker after the action.
`--package-dir` reuses an archive. The first Windows-helper run timed out; the
next was interrupted by physical Escape, so native chooser coverage is pending.

The stage uses periodic screenshots rather than a CDP video stream. The Playwright takeover works through the preview at a fixed 1280×800 browser viewport. The timeline scrubber, per-element action highlights, and DevTools panel handoff described in the [browser use plan](../plans/browser-use-plan.md) are still future work.
