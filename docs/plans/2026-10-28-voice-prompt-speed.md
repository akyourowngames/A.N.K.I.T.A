# Plan: faster voice by shrinking the planner payload (2026-10-28)

Status: **proposed, not implemented.** No code from this plan is on the branch yet.
Owner decision needed on the default scope and on connector access.

Related evidence: [voice planner benchmark 2026-10-28](../voice-planner-benchmark-2026-10-28.md)
and [voice delegation guide](../guides/voice-delegation.md).

---

## 1. The problem in one paragraph

Ankita's voice turn spends about **1.4 seconds** waiting for the planner and
about **1.1 seconds** waiting for Sarvam to synthesise speech. The planner
payload is large: the live request carries a **11.8k-character prompt** plus
**30 tool schemas totalling 39.7k characters**. Seven of those tools are
Composio MCP connectors and account for **23.0k of the 39.7k characters (58%)**.
The question is whether shipping fewer tools and a shorter system prompt makes
the spoken reply start sooner. The honest answer today is: **probably a little,
but it is not yet proven, and it will not rescue the Modal planner.**

## 2. What we measured before writing this plan

### 2.1 Where the payload goes

Live voice request captured with `VOICE_LATENCY_TRACE=1`:

```
promptChars 11,793 | tools 30 | toolSchemaChars 39,701
```

| Group | Tools | Schema chars | Share |
| --- | --- | --- | --- |
| Composio MCP connectors | 7 | 23,005 | 58% |
| Built-in core tools | 23 | 16,696 | 42% |
| **Total** | **30** | **39,701** | **100%** |

Composio breakdown:

| Tool | Chars |
| --- | --- |
| `mcp__composio__COMPOSIO_SEARCH_TOOLS` | 7,176 |
| `mcp__composio__COMPOSIO_REMOTE_WORKBENCH` | 5,107 |
| `mcp__composio__COMPOSIO_MULTI_EXECUTE_TOOL` | 4,548 |
| `mcp__composio__COMPOSIO_MANAGE_CONNECTIONS` | 2,951 |
| `mcp__composio__COMPOSIO_GET_TOOL_SCHEMAS` | 1,228 |
| `mcp__composio__COMPOSIO_REMOTE_BASH_TOOL` | 1,067 |
| `mcp__composio__COMPOSIO_WAIT_FOR_CONNECTIONS` | 928 |

Built-in breakdown:

| Tool | Chars |
| --- | --- |
| `schedule_status` | 229 |
| `remember` | 655 |
| `recall` | 548 |
| `skill` | 387 |
| `read_file` | 507 |
| `write_file` | 484 |
| `edit_file` | 1,341 |
| `edit_lines` | 1,179 |
| `apply_patch` | 632 |
| `list_dir` | 528 |
| `search_files` | 908 |
| `glob` | 658 |
| `move_file` | 418 |
| `delete_file` | 429 |
| `restore_file` | 598 |
| `run_command` | 1,123 |
| `job_status` | 551 |
| `job_stop` | 287 |
| `job_input` | 414 |
| `job_wait` | 511 |
| `write_todos` | 1,085 |
| `http_request` | 2,149 |
| `find_tools` | 1,044 |

The system prompt, measured separately, is **9,175 characters** (~2.3k tokens).
Tool schemas are therefore roughly **4×** the prompt text. If the goal is a
smaller payload, tools come first.

### 2.2 Does a smaller tool set actually arrive sooner?

A controlled probe on the same day, same machine, same system prompt, real
Baseten planner:

| Tools shipped | Schema chars | Time to headers (3 rounds) | Median |
| --- | --- | --- | --- |
| 22 built-ins | 16,301 | 1,045 / 1,070 / 1,232 ms | 1,070 ms |
| 8 built-ins | 8,134 | 902 / 890 / 907 ms | 902 ms |

Removing **8.2k characters saved ~168 ms** (about 16%). At the time, that was the
only clean measurement of schema size we had.

But the live 30-tool request (39.7k chars) measured **1,136 / 1,126 / 1,118 ms**
— essentially the same as the 22-tool probe despite 23k more characters. The
most likely explanation is provider-side prefix caching: Baseten reuses the
unchanged prefix, so the extra bytes are cheap once warm. That means the saving
from dropping Composio is **not** 23k ÷ 8.2k × 168 ms = ~470 ms. It could be as
small as 50 ms, or as large as 400 ms, depending on cache behaviour.

**This is why the plan starts with a measurement spike, not a refactor.**

#### Repeat run, 2026-10-29 — the 168 ms did not replicate

The same comparison was repeated on the next day, 6 alternating rounds each, with
the full real voice system prompt:

| Planner | Tools | Headers p50 | Min–max |
| --- | --- | --- | --- |
| Baseten | 22 (16.3k chars) | **901 ms** | 851–973 ms |
| Baseten | 8 (8.1k chars) | **932 ms** | 885–1,153 ms |
| Modal | 22 | 1,655 ms | 1,121–1,690 ms |
| Modal | 8 | 1,513 ms | 1,120–1,699 ms |

Cutting the tool set by half did **nothing** for Baseten this time — the 8-tool
case was 31 ms *slower*, well inside run-to-run noise. Two conclusions:

1. The earlier 168 ms was probably cache warmth, not schema size.
2. The expected gain from Phase 1 must be revised **down**. Trimming voice tools
   is still worth doing for correctness and context headroom, but it should not
   be sold as a 100–300 ms speed win until the Phase 0 spike proves it on the
   day.

### 2.3 Why this does not make Modal the winner

The same probe with Modal's DeepSeek stayed at **1,662–1,717 ms** even with only
8 tools, while Baseten was **890–902 ms**. Modal's problem is not the tool count
alone; it is prefill/queue behaviour on that deployment. Shrinking the payload
is a general speed improvement, not a reason to switch planners. Keep Baseten.

**"Use Modal only for tool calls and planning" does not fix this.** Planning is
the call that carries the tool schemas, so it is the same slow payload — not a
small one. A two-model split also adds a second serial round trip: planner reply,
then answer generation. Even a 350 ms planner plus a 900 ms answer hop is ~1.25 s,
which is not better than the current ~1.0–1.4 s single call.

Measured variants on 2026-10-29 (headers p50, two rounds each):

| Variant | Baseten | Modal |
| --- | --- | --- |
| Full voice prompt, 22 tools | 987 ms | 931 ms |
| Slim 8 tools | 863 ms | **351 ms** |
| Slim 8 tools, forced `tool_choice` | 968 ms | 348 ms |
| Compact router prompt, 8 tools | 838 ms | 344 ms |
| `json_schema` strict, no tools | 643 ms | 354 ms |
| `json_schema` + 8 tools | 704 ms | 346 ms |

The Modal column looks excellent — and it was, for about ten minutes. The 6-round
repeat immediately afterwards put the same slim payload back at **1,513 ms**
(range 1,120–1,699 ms). Modal can reach ~350 ms when the deployment is warm and
drops to 1.1–1.7 s when it is not; a 4–5× swing between two runs an hour apart.
That is an availability property of the deployment, not something a prompt or
tool refactor can fix.

Two further findings from the same probe:

- **Structured output is slower, not faster.** With `response_format:
  json_schema` and `strict: true`, headers were fast (331–377 ms on Modal) but the
  total reply took **2.3–5.0 s** because reasoning inflated to 1,171–2,726
  characters before the JSON. The valid JSON arrived, just very late.
- **Do not combine `response_format` with `tools`.** Baseten ignored the schema
  and emitted a tool call with empty content (`jsonValid: false`); Modal emitted
  JSON and no tool call. The two planners disagree, so a voice path relying on
  both would behave differently per provider.


### 2.4 Reasoning is a bigger lever than tool count

Measured 2026-10-29, real voice system prompt, 8 tools, same prompt, 6 rounds per
arm (Baseten 4 rounds for the second table), medians:

| Arm | Headers p50 | First output p50 | Reasoning tokens p50 | Tool calls emitted |
| --- | --- | --- | --- | --- |
| Baseten `low` (current voice planner) | 960 ms | **1,905 ms** | 87 | 6/6 |
| Modal `low` | 359 ms | 671 ms | 46 | 6/6 |
| Modal `reasoning_effort: none` | 373 ms | **457 ms** | **0** | 6/6 |
| Modal `chat_template_kwargs: {enable_thinking: false}` | 351 ms | 419 ms | 0 | 5/6 |

Turning reasoning off on Modal removes **~214 ms** (671 → 457 ms) and produces
zero reasoning tokens on every attempt. The same attempt on Baseten cannot be
disabled:

| Baseten arm | First output p50 | Reasoning tokens p50 |
| --- | --- | --- |
| no `reasoning_effort` sent | 1,759 ms | 150 |
| `reasoning_effort: none` | 1,592 ms | 85 |
| `reasoning_effort: minimal` | 1,476 ms | 96 |
| `reasoning_effort: low` | 1,433 ms | 54 |

`none` and `minimal` both return HTTP 200 on Baseten but still reason. There is no
supported way to switch it off on the current planner.

Tool choice did **not** get worse: Modal without reasoning picked the correct
first tool (`write_file`) in 5–6 of 6 rounds, while Baseten picked `list_dir` in 5
of 6. So the "reasoning is needed for tool accuracy" worry is not supported by
this data.

**Caveat that still decides the outcome:** the 350–460 ms figures only appear
while the Modal deployment is warm. When it had been idle, the first call took
~1.6 s and a separate 6-round run averaged 1.5 s. Reasoning-off does not remove
that cold-start tail; it only lowers the warm floor.

Groq was also tested (same payload): `openai/gpt-oss-120b` reached 262–312 ms to
headers with first output at 734–855 ms, but the free tier returned HTTP 429
(rate limit) after two calls at this prompt size, so it is not usable for voice
without a paid tier. `allam-2-7b` does not support tool calling (HTTP 400) and
`gpt-oss-safeguard-20b` rejected the payload as too large (HTTP 413).

### 2.5 The speech floor

Sarvam TTS is about **1.0–1.3 seconds** per spoken reply and is unchanged by this
plan. Even removing the entire planner wait would leave a ~1.1 s floor. A
10–15% planner win means roughly **2.6 s → 2.3 s** transcript-to-player, not
instant speech. Speech streaming is a separate project.

## 3. Goal and non-goals

**Goal:** reduce the voice planner's time-to-first-token by at least **15%**
(about 200–250 ms on the real loop) without breaking voice delegation, and
without changing typed chat.

**Stretch:** 25% planner improvement (about 350 ms).

**Reality check (2026-10-29):** the size→latency link did not reproduce on the
repeat run, so this 15% target is a hope, not a forecast. Section 10 carries the
revised estimate.

**Non-goals:**

- Do not shorten tool descriptions globally. Typed chat depends on them.
- Do not remove capabilities from typed chat.
- Do not switch the voice planner to Modal in this plan.
- Do not implement streaming TTS here.
- Do not claim a win from synthetic prompts alone; only the real loop counts.

## 4. Approach

Three phases, each gated by measurement. Stop at any phase that does not clear
its acceptance bar.

### Phase 0 — Measure the ceiling before changing code (½ day)

Build a throwaway measurement path, not a product feature:

1. Add `scripts/probe-voice-payload.mjs` (temporary, can stay as a script) that
   loads the real voice agent, grabs `agent.systemText()` and
   `agent.currentSpecs()`, then sends the real voice prompts with four payload
   variants:
   - `full`: current 30 tools.
   - `no-connectors`: built-ins only (drop every `mcp__*` name).
   - `slim`: built-ins minus `job_*`, `skill`, `edit_lines`, `apply_patch`.
   - `slim-compact`: `slim` plus a reduced system prompt.
   - `slim-noreason` (Modal only): `slim` with `reasoning_effort: none`.
2. Run each variant 3 rounds against Baseten, warm-up discarded. Record headers,
   TTFT, total, prompt tokens, output tokens.
3. Run the same payloads through `verify-voice-latency.mjs`-style turns if the
   direct probe shows promise.

**Priority change (2026-10-29):** §2.4 shows reasoning-off on Modal cutting first
output from 671 ms to 457 ms, while payload trimming cut nothing that replicated.
So the first arm to test is `slim-noreason`, and Phase 1 (tool scope) should only
start if that arm is rejected for a non-speed reason such as cold starts.

**Gate to Phase 1:** `no-connectors` or `slim` must show at least **10%** median
improvement in time-to-headers over `full` on Baseten. If not, stop and record
the negative result in the benchmark doc. Do not refactor on a hunch.

Cost: ~30 minutes of API calls, no product risk.

### Phase 1 — Voice-only tool scope (1–2 days)

If Phase 0 passes, add a voice-only allowlist and wire it through the existing
`allowedTools` mechanism. No new tool-execution machinery.

**Design**

- A voice turn ships only a curated core set.
- Deferred built-in tools stay loadable through the existing `find_tools` path,
  because their names remain in the allowlist.
- MCP connector tools are excluded from voice by construction: the allowlist is
  built from `tools/index.mjs` `names()`, which only contains built-ins.
- Typed chat keeps `allowedTools = null` and its full catalogue.

**Proposed curated core (shipped on every voice turn):**

```
schedule_status, remember, recall,
read_file, write_file, edit_file, list_dir, search_files, glob,
move_file, delete_file, restore_file,
run_command, write_todos, http_request, find_tools
```

Schema total: **12,704 chars** (16 tools), down from 39,701 (−68%).
If Phase 0 shows the connector cut alone is enough, ship the smaller change
first: all 23 built-ins, no connectors (**16,696 chars, −58%**).

**Deferred built-ins that stay loadable on demand:** the rest of `names()`
(web, browser, git, process, project, github, images, automation, subagents),
minus anything deliberately excluded.

**Explicitly unavailable in voice (Phase 1):** Composio connectors. Voice says
so plainly if asked for Gmail/Slack work and suggests typed chat. This is the
main product trade-off and needs an owner decision (see §8).

**Files to change**

| File | Change |
| --- | --- |
| `src/core/voice-tools.mjs` (new) | `VOICE_CORE_TOOL_NAMES`, `voiceAllowedTools(config)`, scope parsing helpers. Pure data, unit-testable. |
| `src/core/voice-session.mjs` | `withVoiceBrain`: add `allowedTools` to the saved fields; set it from `voiceAllowedTools(agent.config)`; restore in `finally`. `refreshPrompt()` is already called per tool round, so the system prompt and schema subset follow automatically. |
| `src/core/config.mjs` | New `VOICE_TOOL_SCOPE=slim|full` (default `full` until Phase 0/2 results are accepted; flip to `slim` only after the live gate). Add the `showConfig` row. |
| `src/core/cli.mjs` | `--config` row for `VOICE_TOOL_SCOPE`; no other logic. |
| `.env.example` | Document the flag and the connector limitation. |
| `src/core/voice-session.mjs` | Add one suffix line: if a needed tool is unavailable, say so and suggest typed chat; never claim the work is done. |

**Why `allowedTools` is the right hook**

- `Agent` already stores `allowedTools` as a `Set` and filters both core specs
  and optional groups (`src/core/agent.mjs:679-682`) and tool execution.
- `systemText()` already filters the listed catalogue by `allowedTools`
  (`src/core/agent.mjs:511-515`), so the prompt shrinks with the schema set.
- The desktop and CLI voice paths both call `withVoiceBrain`, so one change
  covers both surfaces.
- `refreshPrompt()` runs at the start of every tool round
  (`src/core/agent.mjs:1322-1326`), so no stale catalogue is sent.

**Edge cases to handle**

- `agent.allowedTools` may be absent in unit fixtures; default to the voice set
  only when `agent.config` exists, and always restore the prior value.
- Skills: the `skill` tool is core. Decide whether voice keeps it. Proposed:
  drop it in `slim` (saves 387 chars) because voice cannot read long skill
  bodies aloud; typed chat keeps it.
- Background jobs: `job_*` tools are proposed for removal. Voice delegation uses
  the voice task store, not the job tools, but confirm with the delegation gate.
- MCP always-on: Composio is configured always-on, so it lands in `core`.
  `allowedTools` filtering removes it; verify no crash and no "unknown tool"
  prompt line. Add a test with a fake always-on MCP server.
- `find_tools` group listing: ensure excluded connector groups do not appear in
  the prompt. `buildSystemPrompt` already receives the filtered name set.

### Phase 2 — Compact voice system prompt (1–2 days, only if Phase 1 is not enough)

Only start if Phase 1 lands between 10% and 15% and the remaining prompt text is
still a meaningful share.

**Design:** add a voice-only system profile that keeps safety, tool-use rules,
file/path rules and honesty rules, and drops:

- the full tool-group catalogue (already smaller with the allowlist),
- connector/composio guidance,
- browser and long-form workflow guidance,
- skill catalogues and project hints,
- verbose formatting instructions.

**Files:** `src/core/agent.mjs` (`buildSystemPrompt`/`systemText` accept a
`compact` option or read `config.voiceCompactPrompt`), `config.mjs`,
`voice-session.mjs` (set the flag inside `withVoiceBrain`, restore after).

**Gate:** prompt must shrink from ~9.2k to **≤5k characters**, and the
delegation gate plus a 10-prompt tool-choice check must still pass. If tool
choice degrades, abandon Phase 2 and keep the fuller prompt.

### Phase 3 — Re-evaluate Modal (later, deployment-side)

Out of scope here. If the Modal deployment enables prefix caching or gets more
prefill capacity, re-run the benchmark. Until then, Baseten stays the voice
planner.

**Keeping it warm — use Modal's own controls, not an external pinger.** Measured
2026-10-29: the same request costs **1.1–2.0 s** on a cold container and
**0.37–0.60 s** on a warm one, so warmth is worth ~1 s per voice turn. Modal
exposes three deployment parameters (per Modal's cold-start guide):

- `scaledown_window` — idle seconds before a container stops; default **60 s**,
  settable **2 s to 20 min**.
- `min_containers` — a floor that stops the Function scaling to zero.
- `buffer_containers` — spare capacity while active.

Recommended order:

1. `scaledown_window=300` — keeps the planner warm across a conversation, costs
   five idle minutes after the last turn.
2. `min_containers=1` only if a warm-first-turn guarantee is worth 24/7 GPU
   billing; this is the expensive option and needs a cost decision.
3. Optionally pre-warm from the app when voice mode starts, hiding the remaining
   cold start behind microphone setup.

UptimeRobot is **not** a substitute. Its free tier checks every **5 minutes**,
while Modal idles a container after **60 seconds**, so three of every four minutes
would still be cold; the Solo plan (60 s) is exactly at the boundary, and only
Team (30 s, $35/mo) or Scale (15 s, $65/mo) could keep pace. That adds a paid
dependency, cannot guarantee a specific container, and does not replace
`scaledown_window`, which the Modal autoscaler honours directly.

## 5. Measurement protocol

Use the same machine, same day, alternating order to reduce drift.

**Direct payload probe** (Phase 0):

```bash
node scripts/probe-voice-payload.mjs --variants full,no-connectors,slim,slim-compact --rounds 3
```

**Real loop** (Phase 1/2):

```bash
# before
node scripts/verify-voice-latency.mjs
# after (temporary override until the default flips)
$env:VOICE_TOOL_SCOPE='slim'; node scripts/verify-voice-latency.mjs
```

Record per run: `transcriptToPlayerMs`, `ttsMs`, planner share
(`transcriptToPlayerMs − ttsMs`), prompt chars, tool count, prompt tokens,
output tokens, and the tool names actually shipped.

**Acceptance**

| Check | Bar |
| --- | --- |
| Planner share, p50 | ≥15% faster than same-day `full` |
| Transcript→player, p50 | ≥10% faster (≥250 ms) |
| Tool schema chars | ≤16.7k (Phase 1 safe cut), ≤14k if slim |
| Delegation | `verify-voice-delegation.mjs` 3/3 done, file written and read |
| Tool errors | No increase in failed calls or "unknown tool" replies |
| Typed chat | Unchanged catalogue, unchanged behaviour |
| Tests | All voice/desktop/provider suites green |

If the real-loop gain is under 10%, **do not flip the default**; keep the code
behind `VOICE_TOOL_SCOPE=full` or revert it and record the negative result.

## 6. Test plan

**Unit**

- `voiceAllowedTools` returns the curated set for `slim`, `null` for `full`, and
  falls back safely for invalid values.
- `withVoiceBrain` sets and restores `allowedTools`, including when the agent
  had none.
- The voice system prompt lists only allowed tools and never mentions Composio
  when connectors are excluded.
- An always-on fake MCP server is filtered out without throwing.
- Excluded core tools cannot be called through the tool host during a voice
  turn (execution guard, not just the prompt).
- `VOICE_TOOL_SCOPE` parsing and `--config` output.

**Integration**

- Existing `test/core/voice-cli.test.mjs` loop still passes with the slim set.
- Add one fixture turn that asks for a file write and read, proving delegation
  still works with the curated set.
- Add one fixture turn that asks for a connector action and asserts a clear
  "not available in voice" answer, not a fake success.

**Live**

- `node scripts/verify-voice-delegation.mjs` (real Sarvam STT/TTS, 3 rounds).
- `node scripts/verify-voice-latency.mjs` with and without the flag.
- Desktop voice UI script if the settings copy changes.

## 7. Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Connector work becomes unavailable in voice | A user asks Ankita to send a Slack message by voice and it cannot | Say so plainly, point to typed chat; offer `VOICE_TOOL_SCOPE=full`; document it in the guide |
| Prompt caching already hides the cost | No measurable gain; wasted change | Phase 0 gate; stop if under 10% |
| Dropping `job_*` breaks background delegation | Voice tasks stop working | Keep job tools in the safe cut; only remove in `slim` if delegation gate passes |
| Shorter descriptions cause wrong tool calls | Failed tasks, wrong arguments | Do not rewrite descriptions; remove whole tools and keep the deferred path |
| System prompt trim loses safety/honesty rules | Unsafe or boasting replies | Keep those sections explicitly; run the existing brevity/failure tests |
| Voice-only allowlist leaks into typed chat | Typed chat loses tools | Save/restore in `withVoiceBrain`; assert in tests; typed chat never calls it |
| Provider cache makes A/B noisy | False win or loss | Alternate order, discard warm-up, use medians, same-day comparison |
| Modal temptation returns | Scope creep | Phase 3 is explicitly deployment-side only |

## 8. Decisions needed from the owner

1. **Default scope:** `slim` for everyone, or `full` with `slim` opt-in? Proposed:
   ship `full` until Phase 0 proves ≥10%, then flip to `slim` and document the
   connector limitation.
2. **Connectors in voice:** accept them being unavailable, or keep the 23k-char
   Composio schemas for the few turns that need them? Proposed: unavailable in
   `slim`, available in `full`.
3. **Drop `job_*` and `skill`?** Proposed: yes in `slim`, no in the safe
   `no-connectors` cut.
4. **Phase 2 appetite:** is a ~200 ms planner win worth touching the system
   prompt, given the ~1.1 s TTS floor? Proposed: only if Phase 1 is under 15%.

## 9. Rollout and rollback

- Land Phase 0 as a script + doc update only. No product change.
- Land Phase 1 behind `VOICE_TOOL_SCOPE` with the default `full`.
- Flip the default only after the live gate and the owner decision.
- Rollback is one config value (`VOICE_TOOL_SCOPE=full`) or a one-line revert;
  no data migration, no stored state.
- Update `docs/guides/voice-delegation.md` and the benchmark doc with the final
  numbers and the connector limitation.

## 10. Estimated effort and expected result

| Phase | Effort | Expected gain | Confidence |
| --- | --- | --- | --- |
| 0 — measure | ½ day | none (information) | high |
| 1 — tool scope | 1–2 days | 0–150 ms planner; the 2026-10-29 repeat showed **no** reliable size effect | **low** (revised down) |
| 2 — compact prompt | 1–2 days | 50–200 ms | low–medium |
| Total realistic | 2–4 days | **2.6 s → ~2.4–2.5 s**, possibly 2.6 s unchanged | low–medium |

The 100–300 ms figure in the first draft came from a single probe that did not
replicate the next day (§2.2). Treat Phase 1 as a correctness/context change that
*might* buy speed, not as a speed feature. The Phase 0 gate decides.

**Not in this plan, but measured bigger:** running the Modal planner with
`reasoning_effort: "none"` cut first output from 671 ms to 457 ms (§2.4), roughly
four times sooner than the current Baseten planner's ~1.9 s. That is a planner
switch, not a payload change, so it belongs in its own decision.

The TTS floor means this will not feel like a dramatic change. If the goal is a
visibly faster voice, the bigger lever is starting speech before the full reply
is finished, which is a separate design and should be planned separately.

## 11. Open questions

- Does Baseten actually cache the system+tools prefix, and for how long? A cold
  and warm comparison of the identical payload would settle the size sensitivity.
- Do voice users ever need connectors? Check the saved voice task transcripts
  under `.ankita_backups`/task storage before removing them by default.
- Does `find_tools` reliably load a deferred built-in inside a two-sentence voice
  turn, or does the extra round cost more than the schema saved? Measure.
- Would a smaller `http_request` description be safe, given it is the largest
  built-in schema (2,149 chars)? Only consider after Phase 1 numbers.
