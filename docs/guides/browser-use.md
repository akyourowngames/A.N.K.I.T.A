# Browser use

Ankita can open and interact with real web pages. The browser tool is loaded on demand with `find_tools("browser")`, so ordinary conversations do not pay for a browser schema on every request.

## Set up a browser

Open **Plugins → Apps → By Ankita team**, then select a browser to open its settings. Both choices start off:

- **Playwright Browser** runs a separate Chromium profile. Enable it, then use **Download Chromium** if the card says setup is needed. The download is roughly 310 MB. **Run in the background** keeps the browser window hidden while the live stage shows its page.
- **Chrome local** uses the pinned `chrome-devtools-mcp` server over Chrome DevTools Protocol (CDP). Enable it and choose **Private Chrome**, **Debug port**, or **My session**. Ankita starts the connection when a browser request needs it; **Start connection** also lets you test it in advance. The first connection asks approval for the exact server command. That approval is remembered for the same command, including reconnects. **My session** also requires Chrome 144 or later, remote debugging enabled at `chrome://inspect/#remote-debugging`, and Chrome's permission dialog when it attaches. **Debug port** attaches to a Chrome instance already listening on the selected port; **Test port** checks the connection before starting. [Chrome's connection options](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/configuration.md) explain the upstream behavior.

Chrome's private profile is the least privileged local option. **My session** can see your existing tabs and sign-ins, so use it when a task needs them. Chrome shows its own control banner while attached. The Chrome MCP server is kept behind Ankita's single `browser` tool; its diagnostics are not offered to the agent by default.

Enabling a card records the choice. A disabled browser is never selected. With both enabled, a new session prefers Playwright, then keeps its current enabled browser. Disabling Chrome makes the next page open use Playwright; old Chrome tab IDs and refs must be replaced with a fresh page and snapshot. Plugin choices are stored in `~/.copilot-chat-cli/browser.json`. Playwright's browser profile lives under `~/.copilot-chat-cli/browser/playwright/`.

## Use it

Ask Ankita to open a site, inspect it, and perform a task. `open`, `act`, and `fill_form` return the current snapshot with `[ref=…]` element references. Copy the opaque ref verbatim; a DOM ID, selector, accessible label, or role name is not a ref. Use the returned controls for the next action without taking another snapshot. A successful action whose follow-up snapshot fails still reports success: inspect the page before proceeding rather than repeating the action.

Snapshots replace the previous refs. Navigation, switching tabs, and takeover invalidate them. Playwright can follow a uniquely matching accessible control after a re-render within the original frame; ambiguous replacements are rejected. An invalid ref returns an error with a fresh snapshot when available, without executing the requested mutation. Use the new ref from that output. If a snapshot omits a control because of its size limit, request `snapshot` with a `query` matching its accessible label. Playwright includes visible controls in child frames and open shadow roots, along with values and relevant states; password values are hidden.

Use `fill_form` with up to ten `{ref, text}` entries to fill several fields from one snapshot. All refs are checked before filling begins, and the response includes the next snapshot. Playwright supports text fields, selects by option label, and checkboxes/radios using `"true"` or `"false"`. Chrome delegates form filling to its native MCP tool. A later field failure can leave earlier fields filled; inspect the reported state before continuing. The tool also supports page text, tabs, screenshots, closing a tab, and batches of up to ten steps that stop at the first error.

Use `fill` to replace a field's value and `type` to insert text at its caret. A `press` action targets its supplied ref; Chrome focuses that registered control without clicking it before sending the key. If the control cannot receive focus, the key is not sent. Chrome typing reads the next snapshot after the keyboard action because its native typing tool does not accept `includeSnapshot`.

Screenshots are saved under `downloaded-images/` in the current workspace and returned as structured receipts. During an agent turn, valid captures are attached as PNG image content to the next model request using the existing user-image format; tool messages remain text. Attachment requires a vision-capable model and available context space. Captures are limited to 15 MiB each and three automatic images per turn, and workspace boundaries, file type, byte count, and PNG signature are checked. `read_file` remains a text reader; use the screenshot attachment or desktop artifact to view pixels.

The desktop **browser stage** opens beside chat during a run and collapses the left sidebar to give the page more room. It shows the current tab and URL, a live page preview, and **Stop** and **Take control** actions. Take control pauses Ankita's next browser action. In the Playwright stage, click, type, paste, or scroll on the preview; press `Esc` or **Hand back** to resume. With Chrome local, interact in Chrome itself and then hand back. `Ctrl/Cmd+Shift+B` toggles the stage. The composer Stop cancels pending browser calls, including requests paused for takeover or setup approval. Closing the stage stops the browser run and disconnects Chrome's MCP connection; the next Chrome request can reconnect automatically.

The visible preview targets 10 updates per second with one request in flight. Chrome returns image data directly through MCP, without a temporary screenshot file. Tab metadata refreshes every two seconds. Hidden panes/windows and lost connections refresh less frequently. Recoverable page/action errors keep the live preview and Take control available. Live frames update the browser pane independently of the chat; the chat thumbnail refreshes every two seconds. Actual FPS depends on page complexity and Chrome's screenshot latency. Run `node scripts/verify-browser-automation.mjs` for a disposable local form, screenshot, cancellation, reconnect, and animated-page benchmark of both backends. This script uses an already cached Chrome MCP executable, prints its actual version alongside the configured version, and never downloads a package. The older `verify-browser-chrome.mjs` script can invoke the configured package through npx.

The stage shows short notices for stale controls, page loading and action failures. Fresh snapshots, page code, terminal formatting and call logs remain in tool diagnostics rather than the live pane. Only a lost connection or browser startup failure prompts browser setup. A successful subsequent action clears the notice. A slow preview keeps its last frame and clears its notice when capture resumes.

For a public-site navigation failure, `node scripts/probe-browser-navigation.mjs <url>` compares the actual adapter with HTTP/1, full headless Chromium and visible Chromium using disposable profiles and read-only navigation. It performs no clicks or booking actions. A different transport does not guarantee that the URL exists or that a site accepts automation; inspect the resulting page/status rather than repeating a failed booking step.

## Recovering a connection

Before a Chrome action, Ankita checks the connection. If it was lost, the desktop makes one reconnect attempt and takes fresh refs. It never automatically replays a click or form submission. Chrome requests have deadlines, preview requests time out quickly, and closing the transport rejects outstanding calls. A request that cannot recover returns an error instead of waiting forever. Chrome's own permission dialog remains required when attaching to **My session**.

If a model response stream disconnects or ends without a completion marker, Ankita retries that model step up to twice. Completed tool results stay in context, incomplete tool requests are discarded, and unfinished text is replaced when the recovered wording changes. Stop prevents recovery retries. A provider that repeatedly disconnects still reports an error after the bounded attempts.

In the terminal, use `/browser list`, `/browser enable isolated`, `/browser disable isolated`, or the same enable/disable commands with `local`. Chrome connection setup is in the desktop Plugins page.

## Packaged desktop verification

On Windows, run `npm run desktop:build`, then `node scripts/verify-browser-desktop.mjs`. The verifier packages the installed Electron distribution into a temporary directory and launches the actual executable with isolated configuration and user data. It checks three appearances, a browser task through the real HTTP/SSE and IPC paths, screenshot pixels in the next request, sidebar collapse, takeover, Stop, shipped command stdin/EOF and exit status, and Playwright's installer `--dry-run`. The model decisions are scripted and the page is a local form; this does not test a live LLM or a real booking site. No packages or browsers are downloaded.

Use `--keep-artifacts` to retain the screenshots and disposable build for inspection. To rerun that exact build, pass `--package-dir <win-unpacked-directory>`; otherwise a fresh archive is built. Keep source files settled throughout packaging so an archive cannot combine incompatible module revisions.

## Site controls

Only HTTP and HTTPS pages can open. Loopback and private hosts are blocked by default; set `ALLOW_PRIVATE_HOSTS=1` when working with a local development server. Open a browser's settings to add allowed or blocked domains. An allowed list limits where it may navigate; blocked domains always win. `BROWSER_ALLOWLIST` and `BROWSER_BLOCKLIST` also accept comma-separated domains (including `*.example.com`). Page content is treated as untrusted. Browser interactions ask for tool approval. Tool cards redact text entered through `browser act`; the live preview shows the page as rendered, including any visible field values.

The isolated browser checks navigation and resource hosts, including navigations initiated by a page. Chrome local uses Chrome's own permission and MCP transport; the app validates the URL passed to its `open` action. Browsing directly in Chrome remains under the user's control. Uploads and arbitrary page JavaScript are not included in the first-party `browser` tool.

## Current limits

The stage uses periodic screenshots rather than a CDP video stream. The Playwright takeover works through the preview at a fixed 1280×800 browser viewport. The timeline scrubber, per-element action highlights, and DevTools panel handoff described in the [browser use plan](../plans/browser-use-plan.md) are still future work.
