# Voice planner benchmark: Baseten vs Modal DeepSeek (2026-10-28)

**Question.** Would DeepSeek V4.1 Flash on Modal, at its lowest reasoning effort,
make Ankita's voice replies faster than the current Baseten Meta planner?

**Short answer.** No for the real voice path. It is faster only on small prompts
without the tool catalogue. The full voice turn carries 30 tool schemas, and
Modal's time to first token on that payload is slower and less stable than
Baseten's.

## Setup

| | Before | After |
| --- | --- | --- |
| Provider | Baseten | Modal |
| Model | `meta-models/muse-spark-open-1026` | `deepseek-ai/DeepSeek-V4.1-Flash-1017` |
| Reasoning | `low` | `low` (the deployment rejects `minimal`) |
| Context | 1,048,576 tokens | 1,048,576 tokens |
| Speech | Sarvam `bulbul:v4-flash` | Sarvam `bulbul:v4-flash` (unchanged) |

Same Windows machine, same network session, same prompts. The microphone is
simulated; TTS is real. Measurements are transcript-to-audio-player handoff, not
physical headset latency.

## Result 1 — bare planner (no tool schemas)

6 spoken-style prompts × 3 rounds after a discarded warm-up. 18 requests per
planner, 36/36 succeeded.

| Planner | p50 TTFT | p95 TTFT | p50 first answer word | p50 full reply | p50 output tokens |
| --- | --- | --- | --- | --- | --- |
| Baseten | 657 ms | 1,174 ms | 1,445 ms | 1,477 ms | 236 |
| Modal | 408 ms | 1,518 ms | 725 ms | 725 ms | 68 |

- First token: Modal faster by 38% (657 → 408 ms).
- Full reply: Modal faster by 51% (1,477 → 725 ms).
- Delegation tool call: Baseten 898 ms, Modal 490 ms; both called the tool correctly.
- The Modal `p95` includes a 1.5 s first-round request. Warm rounds were 383–721 ms.
- Modal produced 68 output tokens against Baseten's 236, so part of the full-reply
  win is a shorter answer, not only faster generation.

## Result 2 — the real voice loop

`node scripts/verify-voice-latency.mjs` drives the real CLI voice loop with the
real planner, the real agent prompt, all 30 tool schemas, and real Sarvam TTS.
Six turns per planner across two runs.

| Measure | Baseten | Modal | Change |
| --- | --- | --- | --- |
| Transcript → player, p50 | 2,593 ms | 3,414 ms | **32% slower** |
| Planner share (total − TTS), p50 | 1,440 ms | 2,411 ms | **67% slower** |
| Sarvam TTS, p50 | 1,126 ms | 978 ms | unchanged, noise |

Modal's fastest real turn was 2,019 ms and its slowest 3,933 ms. Baseten ranged
2,340–2,724 ms. The instability is the problem, not one bad sample.

## Why the reversal

The real voice request is not the small benchmark prompt. The trace shows:

```
promptChars 11,793 | tools 30 | toolSchemaChars 39,701 | max_tokens 4096 | reasoning_effort low
```

Time to response headers (prefill + queue, before any generated token):

| Planner | Turn 1 | Turn 2 | Turn 3 |
| --- | --- | --- | --- |
| Baseten | 1,136 ms | 1,126 ms | 1,118 ms |
| Modal | 2,229 ms | 669 ms | 1,953 ms |

Baseten is stable around 1.1 s on the full payload. Modal is faster when its
prefix happens to be cached and much slower when it is not. The bare-planner win
does not survive Ankita's tool catalogue.

Trimming the voice tools does **not** rescue it. With an 8-tool, 8.1 k-char
subset instead of 22 tools / 16.3 k chars, Modal still needed 1,662–1,717 ms to
headers while Baseten needed 890–902 ms. Generation speed was never the
bottleneck; prefill/queue on the deployment is.

## Deployment facts learned

- `reasoning_effort: "minimal"` is rejected with HTTP 400. Accepted values are
  `low`, `high`, `xhigh`, `max`, or an integer 1–100 via `chat_template_kwargs`.
- `chat_template_kwargs: { reasoning_effort: 1 }` is accepted but produced **more**
  reasoning than `low` (78 vs 39 reasoning tokens on the same prompt), so it is not
  a faster setting. `low` is the floor used by the preset.
- Streaming, `stream_options.include_usage`, and tool calls all work.
- `/v1/models` advertises a 1,048,576-token window, used for voice turns only.

## Code changes

- `src/core/provider.mjs`: Modal preset plus named `baseUrlConfig`, `modelConfig`
  and `envKey` metadata; provider-specific request defaults now come from one map
  instead of a Baseten name check.
- `src/core/voice-session.mjs` / `src/core/cli.mjs`: use that metadata, so the
  voice brain and typed chat resolve base URL, model and key without special cases.
- `src/core/config.mjs`: `MODAL_PROXY_TOKEN_ID` + `MODAL_PROXY_TOKEN_SECRET` are
  joined into the bearer token; a combined `MODAL_PROXY_TOKEN` wins.
- `scripts/bench-voice-planner.mjs`: reproducible two-planner benchmark.
- `scripts/verify-voice-latency.mjs`: `--voice-provider` / `--voice-model`
  overrides so an A/B does not edit `.env`; `VOICE_LATENCY_TRACE=1` prints request
  size and header timing.
- Desktop voice default stays Baseten. Modal is opt-in with `VOICE_PROVIDER=modal`.

## Recommendation

Keep Baseten as the voice planner for now. Modal is only a candidate if the
deployment changes:

1. Enable prefix caching or give the deployment enough prefill capacity that the
   30-tool payload reaches headers in a stable sub-1.1 s.
2. Re-run `node scripts/bench-voice-planner.mjs --rounds 3`.
3. Re-run `node scripts/verify-voice-latency.mjs --voice-provider modal` and compare
   medians against the same-day Baseten run.
4. Accept only if transcript→player improves, not just the bare planner.

A voice-only tool subset is not a fix on its own; that was measured and still lost.

## Update 2026-10-29 — reasoning is the lever, not payload size
Two follow-up probes changed the picture:

- **Payload trimming did not replicate.** 8 tools beat 22 by 168 ms in the first
  probe, then lost by 31 ms in a 6-round repeat. Treat the size effect as noise.
- **Switching reasoning off on Modal is real.** `reasoning_effort: "none"` is
  accepted (HTTP 200) and produced **0 reasoning tokens on 6/6 attempts**, cutting
  first output from 671 ms to 457 ms. Baseten accepts `none` and `minimal` but
  still reasons (85–96 tokens), so it cannot be switched off.
- **Tool accuracy did not degrade.** Without reasoning, Modal chose the correct
  first tool (`write_file`) in 5–6 of 6 rounds; Baseten chose `list_dir` in 5 of 6.
- **Cold starts still dominate.** The 350–460 ms figures only held while the
  deployment was warm; an idle deployment answered in ~1.6 s.

So the open question is no longer "smaller prompt or not" but "can the Modal
deployment be kept warm". Details in
[the payload plan](plans/2026-10-28-voice-prompt-speed.md#24-reasoning-is-a-bigger-lever-than-tool-count).

## Candidate matrix 2026-10-29 (three Modal deployments)

Same real voice payload (9,175-char system prompt + 22 built-in tool schemas,
16,301 chars), same prompt, alternating loop, 4 rounds each, medians:

| Endpoint | Model | Headers p50 | First output p50 | Reasoning can be off? |
| --- | --- | --- | --- | --- |
| Baseten (current) | `meta-models/muse-spark-open-1026` | **1,011 ms** | 1,920 ms | no — `none`/`minimal` accepted but ignored, still 45–171 tokens |
| `ep-king` | `meta-models/Muse-Spark-Open-816B-A42B` | 2,056 ms | 2,390 ms | no — `none` and `minimal` return HTTP 400; floor is `low` |
| `ep-inkling-nvfp4` | `thinkingmachines/Inkling-NVFP4` | 1,500 ms | **1,540 ms** | yes — `none` gives 0 reasoning tokens |
| `ep-deepseek-v4.1-flash-1017` | `deepseek-ai/DeepSeek-V4.1-Flash-1017` | 1,805–2,018 ms | 2,131–2,237 ms | yes — `none` gives 0 reasoning tokens |

Those numbers include cold starts. Once a deployment has been answering for a
minute, the warm floor is much lower. Measured in follow-up paired runs:

| Arm (warm) | Headers p50 | First output p50 | Tool choice |
| --- | --- | --- | --- |
| Baseten `low` | 946 ms | 1,740 ms | `list_dir` 4/5, `write_file` 1/5 |
| DeepSeek `none` | **370 ms** | **598 ms** | `write_file` 5/5, valid arguments 5/5 |
| Inkling `none` | 479 ms | 581 ms | `list_dir` 12/16, **empty arguments 5/16** |

Baseten also produced one 8,167 ms outlier in that run, against 816–1,206 ms for
its other calls.

### Tool quality, which decides more than speed

- **King (816B)**: chose `list_dir` on **4/4** full-payload rounds. It never
  reached the requested write-then-read task. Fast answers to the wrong action.
- **Inkling NVFP4**: fastest warm floor, but it chose `list_dir` 12/16 times and
  emitted **empty or incomplete arguments in 5/16** rounds (`{}`,
  `{"path":""}`). That would fail or list the wrong directory in production.
- **DeepSeek V4.1 Flash**: `write_file` 5/5 with complete `path` + `content`
  arguments on the real payload. Correct action, valid JSON, no missing fields.
- **Baseten**: valid arguments, but chose the exploratory `list_dir` first in 4/5
  rounds instead of writing the requested file.

### The user's exact curl shape on the two new deployments

`response_format: json_schema` + `strict` + a tool + `reasoning_effort` medium/high
worked on both and returned valid JSON (`{"age":36,"city":"London","name":"Ada"}`),
ignoring the tool as expected: King 1,247–2,004 ms, Inkling 1,370–1,403 ms. So
structured output is supported; it is just slower than tool calling and, as
measured earlier, unreliable when combined with tools.

### Verdict

- **King 816B**: reject for voice. Slowest, no reasoning-off, wrong tool choice.
- **Inkling NVFP4**: reject until argument correctness is fixed. Great speed,
  unreliable actions.
- **DeepSeek V4.1 Flash with `reasoning_effort: "none"`**: the only candidate that
  is both faster than Baseten (598 ms vs 1,740 ms to first output) and correct
  (5/5 right tool with complete arguments). Its weakness is the cold-start tail
  (1.1–1.2 s headers on the first calls).

## Next step

The tool/prompt payload is the remaining speed lever. The measured sizes,
options, acceptance bars and risks are written up in
[the voice payload plan](plans/2026-10-28-voice-prompt-speed.md). It starts
with a measurement spike because prompt caching may hide most of the saving.

## Reproduction

```bash
node scripts/bench-voice-planner.mjs --rounds 3
node scripts/verify-voice-latency.mjs
node scripts/verify-voice-latency.mjs --voice-provider modal
$env:VOICE_LATENCY_TRACE='1'; node scripts/verify-voice-latency.mjs --voice-provider modal
```

`--voice-provider` clears the inherited `VOICE_MODEL`, because the Baseten slug is
not valid input for Modal.

## Caveats

- One machine, one network location, one day. Cloud queueing and serverless state
  vary; the before/after runs were paired on the same day but not simultaneous.
- Six real-loop turns per planner is enough to show a stable direction, not a
  tight confidence interval.
- TTS is unchanged, but its 0.6–1.3 s variance is visible in the total.
- Physical microphone, VAD pause, STT, and headset playback are not measured here.
- The Modal deployment may behave differently with prefix caching enabled; this
  document describes the deployment as configured on 2026-10-28.
