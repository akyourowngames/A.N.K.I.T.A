# Context and parallel-agent verification

Checked across 2026-11-04 and 2026-11-05 against `e14ba07d`, including merged PRs #73, #74, #75 and #76.

## Confirmed bugs and changes

- Compaction counted messages, so a few large turns could be trimmed before a recap ran. It now checks the actual history budget and the configured message limit. Output, tool schemas, personal memory and protocol overhead are reserved first.
- Changing a model retained the preceding model's limit. Compatible and Copilot model catalogues now retain their reported limits. Default models, individual teammates, tool models, fallback requests and voice use the selected model's metadata. A saved manual limit takes priority. Providers without usable metadata keep the configured fallback. Groq's `context_window` field is included among the supported shapes. [Groq API reference](https://console.groq.com/docs/api-reference).
- Cancelling voice while its catalogue was loading could still launch a reply after discovery finished. Discovery now responds promptly to cancellation, checks the signal before starting the reply and safely observes a later catalogue failure. Typed settings are restored.
- A long tool loop could summarize away the current user task. Compaction now retains it, including when subagent inbox messages arrive. Tool exchanges remain atomic. Cancellation leaves the original history intact.
- A recap was visible only after loading the saved transcript. Completion now reaches the main chat and companion immediately, with a separate labelled note. Saved transcripts retain that label.
- Near-limit history could trigger repeated identical recaps. The cooldown applies to near-limit requests, while newly overflowing content can trigger another recap.
- Re-summarizing could cut a prior recap at the ordinary per-message excerpt limit. Bounded earlier recaps now reach the next summarizer complete.
- History reservation ignored a provider's default reply cap and minimum. It now reserves the cap actually sent by the active client, including tool and fallback clients, before fitting the conversation.
- Delegation waited for a final answer, preventing parent messages during independent child work. Background delegation now returns a handle and supports owned list, send, wait and cancel operations. Children can send only to their parent. Delivery occurs between model decisions. Parents process messages and results before finishing, and outstanding work is cancelled on stop or failure.
- Abandoned parent drafts could reappear after loading a session. Drafts discarded while waiting for a child now stay out of saved history.
- A parent could edit files while a background worker held the workspace lock, overwriting either agent's changes. Parent mutations now join the same canonical workspace queue through the shared tool host. Reads and mailbox controls remain available.
- A successful one-shot CLI could crash during immediate Windows native-handle teardown after overlapping requests. It now closes owned jobs, the existing browser and MCP clients, closes the terminal and lets native handles drain before exit.
- Human recap and startup notices could appear before a one-shot JSON response, making it fail to parse. Resume, recap, MCP startup, missing-key, model-fallback, detected-project and connected-app setup notices now respect JSON mode. Human-mode notices remain visible.
- Memory merging could erase a positive fact when its negation was saved. The English-negation guard retains both and flags the conflict.

The context calculation retains the existing conservative UTF-8 byte upper bound for text. Reported model windows are token counts. The app may summarize earlier than a provider's tokenizer would require.

## Reproduction and focused evidence

- Real `chat.mjs --json --continue` checks with seeded history first passed 1/3, with both JSON cases failing. After the resume notice was guarded, successful and skipped-recap notices still corrupted stdout. Guarding the agent's print callback passed 3/3. A separate startup matrix then passed 5/10, with MCP, missing-key, model-fallback, detected-project and connected-app failure notices corrupting all five JSON cases. The final combined target passed 13/13, including all five human-mode controls. MCP used a real approved stdio child, model replies used loopback HTTP and connected-app failure used local URL validation without a hosted request. Syntax checks, desktop typecheck and diff whitespace checks passed.
- Five new compaction regressions failed before the fix. Subsequent mailbox integration tests reproduced two more task-anchor failures. The combined compaction, budget and history checks passed 27/27 before the companion addition.
- The short configured-history case failed with zero recap calls, then passed with one. The normal HTTP send emitted `COMPACTION_HTTP_ROUNDTRIP_OK` with two requests, context 20000 and phases `started`, `completed`. Both the recap and response were checked against that active model's budget with multibyte text.
- Model discovery initially failed 5/5 new checks. The final focused model/provider/voice/desktop/channel run passed 77/77, plus one normal CLI voice-to-typed round trip. A real loopback catalogue request changed a selected small model from active window 128000 to its advertised 16000.
- The real voice-worker cancellation reproduction initially sent two model requests after cancellation. It now sends zero and returns `Cancelled during discovery`. Both late catalogue success and failure are covered. The focused voice-worker, voice-session and model-context run passed 31/31.
- The desktop HTTP path emitted `DESKTOP_COMPACTION_HTTP_OK` with completion before turn end and one persisted recap. Its two checks passed 2/2.
- Removing the live renderer reducer reproduced a timeout waiting for the new recap. Restoring it passed the Chromium check. The test also checks the companion's separate recap label.
- Companion state initially passed 7/8 with the new live/reload recap check failing. The fix passed 8/8. The combined companion and background messaging check passed 12/12.
- Background messaging initially failed because the control host was absent. The final focused backend run passed 35/35. A real loopback HTTP streaming run emitted `MESSAGING_HTTP_OK children=2 messages=6 requests=11 pending=0`. Both children were active while the parent sent replies. Browser state and panel checks passed 10/10.
- The messaging file passed 5/5 after adding a CLI subprocess check. It emitted `MESSAGING_CLI_OK directions=2 waited=1 requests=10 exit=0`. The test now launches the real `chat.mjs` entry point with model discovery, tool discovery, delegation and controls. A deterministic gate holds the child until the parent drafts, proving the parent waits and keeps the abandoned draft out of saved history.
- The provider-output regression failed before the reservation fix, both at the helper and on a real HTTP request. The final focused budget, compaction and model checks passed 34/34. `PROVIDER_OUTPUT_BUDGET_HTTP_OK` reported context 32768, output 12000 and history 19678, leaving room for the protocol allowance.
- The workspace regression initially passed 1/3 with `WORKSPACE_MUTATION_API parent_during_worker=true final=child finished`. The corrected trace is `WORKSPACE_MUTATION_API parent_during_worker=false final=parent finished`. Real API and native file writes, canonical aliases, queued cancellation, MCP hint classification and unrelated workspaces are exercised.
- Direct CLI messaging reproduced Windows exit 3221226505 and `UV_HANDLE_CLOSING` three times after successful message exchange. Graceful cleanup passed the real entry point repeatedly. The focused cleanup and messaging run passed 40/40, including `CLI_BROWSER_SHUTDOWN_OK opened=1 exit=0`, real owned process termination and real stdio MCP termination. The voice CLI suite passed 23/23.
- Memory regressions first passed 28/30, then the focused memory suites passed 62/62. The add/list round trip now keeps both facts and mutual conflict links. Channel, personality, desktop MCP and voice audit checks passed 114/114. Discord and Slack tests used real local HTTP and WebSocket transports.
- An independent review reproduced repeated recap counts `1 → 2 → 3` with unchanged history. After the fix it observed `1 → 1 → 1`. A separate stub-backed fallback check switched the recap and reply to the smaller fallback model.
- The first broad run exposed a request-projection regression from an extra trim. A direct browser request must preserve saved observations. Extra fitting now runs only when the active model changes, including fallback. The existing browser-evidence regression reproduced the failure before that correction.
- A native-target fixture also failed. A disposable `e14ba07d` baseline reproduced the same failure, with 769 bytes available for native identifiers. The changed catalogue left 634 bytes. Both safely omitted all identifiers. The fixture now derives usable headroom from its actual prompt and schemas, retains 11 complete targets, and passed 13/13 image checks. This is a test-budget correction.
- A hosted compaction scenario passed using an anonymous free Kilo model discovered from its live catalogue. The selected model was `reflection/beam-free`, advertising context 1048576. A real `Agent.send` compacted 42 messages to 12, stored the recap and correctly recalled the synthetic detail `Juniper Harbour`. The recap returned HTTP 200 with `finish_reason=stop`, `max_tokens=400`, prompt usage 724, completion usage 338 including 224 reasoning tokens, and reported cost 0. The final streamed reply also returned HTTP 200 with `max_tokens=1024`. No keys, user settings or user files were used or changed.
- A separate honest hosted parent/background-child scenario made eight real HTTP 200 model requests. The parent discovered delegation, received a running handle, sent an updated price, received the child's preliminary finding, waited for its terminal receipt and used the revised total 33 in its final answer. Each direction carried one message. The child finished after 21150 ms. The model mentioned the revised price 11 as a prohibited assumption in its initial brief, so this sample does not prove clean changed-detail secrecy. After completion the parent also attempted an unavailable `ReadFile` tool. The availability guard rejected it, and the final answer used the actual completed receipt. No tool-based file read or write occurred in this scenario.

## Commands

```text
node --test --test-concurrency=1 test/core/context-compaction.test.mjs test/core/context-budget.test.mjs test/core/history-performance.test.mjs
node --test --test-concurrency=1 test/core/model-context.test.mjs test/core/voice-worker.test.mjs test/core/voice-session.test.mjs
node --test --test-concurrency=1 test/core/subagents.test.mjs test/core/subagent-messaging.test.mjs test/core/subagent-workspace-mutations.test.mjs
node --test --test-concurrency=1 test/core/cli-shutdown.test.mjs
node --test --test-concurrency=1 test/desktop/compaction-engine.test.mjs test/desktop/island-state.test.mjs
node --test --test-concurrency=1 test/desktop/compacted-message-ui.test.mjs
npm run desktop:build
npm test
node scripts/test-tier.mjs browser
git diff --check
```

The final non-browser gate expands `classifyTests()` into one serial Node run.
The shutdown matrix belongs to the existing heavy-file group because it launches
real CLI subprocesses and Chromium. `TEST_TIER_HEAVY_OK heavy=2 browser=39`
confirmed that it is excluded from parallel units.

The desktop build passed with 414 transformed modules. All three broad browser runs passed all 39 files. The final browser tier passed 172/172 checks with zero failures or skips in 623 seconds. Parallel broad unit runs exposed Windows fixture cleanup and startup-timing failures. Cleanup now waits for child process closure and server shutdown, then uses bounded asynchronous deletion retries. An independent native cwd-holder reproduced immediate `EPERM`, followed by successful bounded cleanup in 310 ms. Shared cleanup checks passed 14/14. The job deadline fixture now uses the existing bounded event-driven settle allowance, with its behavior assertions retained. Two complete serial jobs-file runs passed 20/20 each.

The final complete serial non-browser run passed with exit 0. It reported 1899 tests, 1898 passes, zero failures and one platform skip in 662.7 seconds. The POSIX executable-permission check is skipped on Windows. Together with the browser gate, the final verification covers all 261 files with 2070 passing checks, one platform skip and zero failures.

The preceding complete serial non-browser run reported 1886 tests, 1884 passes, one failure and one platform skip. Its sole failure was the new owned-MCP CLI cleanup check returning exit 1 with empty stderr. That check passed six focused reruns, a full eight-case non-browser shutdown sequence and the final complete serial gate. The cause of the earlier exit remains unconfirmed.

That single exit-1 observation has no confirmed root cause. It is distinct from
the reproducible native `UV_HANDLE_CLOSING` failure with exit 3221226505 that the
graceful one-shot change fixed. The owned-process assertion now retains stdout,
stderr, the CLI PID and the model-request count on a mismatch. Further isolated
background-to-MCP sequences passed with the original outcome assertions intact.
No speculative production change was made for the exit-1 observation. The final
complete serial gate passed the owned-MCP case in 1754 ms with its original
outcome assertions intact. This remains a disclosed intermittent observation.

Final logs are outside the checkout in the runtime temporary directory.

```text
ankita-context-serial-confirm-aa5fc210-32d2-4140-8814-7f421006056e.log
ankita-context-browser-final-df5ca35f-8d2a-42c3-a41e-1c43a83f61ed.log
```

The serial gate ran all unit and heavy files from `classifyTests()` with
`--test-concurrency=1`. The browser gate ran all 39 browser files serially.
The final whitespace check passed. Changed production literals were reviewed
for shared protocol names, named bounds and configuration-derived values.

## Coverage boundaries

Local HTTP responses are scripted fixtures, with the separate anonymous hosted compaction and messaging runs described above. Other hosted models, real Discord/Slack accounts, physical microphone and speaker behavior, and a packaged native desktop acceptance run remain untested. Browser-only ChatGPT owns its remote conversation window, so these API compaction changes apply to API-backed conversations. English negation detection remains heuristic and other languages use the existing similarity logic.

The messaging and shutdown fixtures now launch `chat.mjs` directly. One-shot cleanup covers plain and JSON success, error and empty input, plus owned processes, MCP and browser sessions. Interactive and daemon shutdown behavior retain their existing paths.

Parallel read-only children overlap. Editing workers keep the existing shared-workspace lock. Their message history is visible during a live run, while delivered messages and tool calls remain in the child transcript. Restarting the app does not resume a running child. See the subagent guide for the full lifecycle and limits.
