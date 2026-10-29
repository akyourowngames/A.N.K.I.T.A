# Voice Delegation — Meta Global AI Developer Hackathon Plan

> Status: terminal implementation in progress (2026-10-27); microphone and desktop gates remain open.
> Target: Meta Global AI Developer Hackathon 2026, track Indie Developer, theme
> **Build for Your World**. Building period 27 Oct – 4 Nov 2026.
> Deadline: 4 Nov 9:00 PM ET = **5 Nov 07:30 IST**. Plan submits the evening of 4 Nov IST.
> Repo: `github.com/akyourowngames/A.N.K.I.T.A` (this working copy, `ankita 2.7.1`).
> Supersedes the local PDF `meta-hackathon-voice-plan.pdf` where this document says so;
> every change from that PDF is listed in [§2](#2-what-changes-from-the-pdf).

## 1. Pitch, and what is actually new

**Pitch.** You speak one sentence in Hinglish — "Ankita, VS Code kholo aur mera workspace
set up karo" — and Ankita turns it into a tracked job, does the work while you move on,
speaks short progress updates, and reports back by voice when it is done.

**The honest framing.** Voice input and spoken replies already exist in the base (see §4).
They are **not** hackathon work and must never be presented as such. What is new this week:

1. Sarvam AI speech-to-text and text-to-speech, tuned for Hinglish (§7.1).
2. A spoken request becomes a **tracked job** with an id, status, steps and summary (§8).
3. **Spoken progress at step boundaries** plus a spoken final report (§8.3).
4. A **Meta planner** (Muse Spark Open via Baseten) behind the delegation path (§7.2).
5. The end-to-end VS Code workspace flow, filmed in Hinglish (§11).

The one-line story for judges: **"Voice was already there. This week it learned to take
delegated work, run it in the background, and report back in the language you spoke."**

## 2. What changes from the PDF

| PDF says | Reality (verified 2026-10-27) | Decision |
|---|---|---|
| Ears: Meta Muse Voice Transcribe | No Meta Model API credits; a Sarvam key is already installed | **Sarvam `saaras:v4`** |
| Voice out: reuse existing CLI voice, "do not add a TTS provider" | Existing TTS is Edge (default) or Groq Orpheus | **Sarvam `bulbul:v4-flash`**, Edge stays as automatic fallback |
| Brain: Muse Spark Open via Baseten, model string `-1026` | Smoke tested 2026-10-27: `meta-models/muse-spark-open-1026` returns 200; the documented slug `meta-models/muse-spark-open` returns **403** on this key | **Use `-1026`** — the guide was right, the docs slug is the one that fails |
| Plan JSON from the model | Baseten docs: **Muse Spark Open has no structured outputs and no JSON mode** | Steps are derived from real tool calls, never from a JSON plan |
| Background job visible in the island UI | The island belongs to the desktop app's own engine and only appears when the main window is hidden (`desktop/electron/island.mjs:143`) | Terminal job first; desktop bridge only if Saturday's gate is green (§12) |
| English-only demo | Sarvam handles Hinglish natively, which is a stronger "Build for Your World" story | Hinglish take, English backup take |

The PDF's instruction "do not add a new TTS provider" is deliberately overridden because
the Meta voice credits are unavailable. This is disclosed in the README, not hidden.

## 3. Reality checks before building

- **Eligibility.** The participant guide says nothing about age; the mandatory waiver
  reportedly requires 18+, and third-party coverage confirms it. Platform approval is not
  waiver clearance. Never sign anything with false information. Treat shipped work, a
  working demo and judge feedback as the reliable outcome; this plan claims no prize.
- **Meta fit is pass/fail.** Stage 1 requires reasonable use of the Meta Model API and/or
  Meta open-weight models. **Sarvam does not satisfy this** — it is an Indian provider, not
  Meta. The planner must stay on a Meta model even if voice runs on Sarvam.
- **No free Meta route exists on this machine.** Checked 2026-10-27:
  - Kilo gateway lists `meta/muse-spark-open`, but a keyless call returns
    `401 PAID_MODEL_AUTH_REQUIRED`. The repo's current keyless Kilo setup cannot use it.
  - The repo's Groq key only exposes GPT-OSS/Qwen models — no Meta Llama.
  - So the submission depends on the Baseten key. **This is the single blocking risk.**

## 4. Baseline — what already exists (reuse, do not re-frame as new)

| Piece | Location | Notes |
|---|---|---|
| Mic capture, 16 kHz mono PCM WAV | `src/channels/voice.mjs:141` `startRecording` | Exactly the format Sarvam wants |
| Voice activity / turn detection | `src/channels/voice.mjs:304` `openVoiceInput`, `:274` `createTurnDetector` | Pause-to-send, hands-free |
| Whisper STT via Groq | `src/channels/voice.mjs:376` `transcribeGroq` | To be joined by a Sarvam path |
| Edge TTS (default, keyless) | `src/channels/voice.mjs:665` `synthesizeEdge` | Automatic fallback |
| Groq Orpheus TTS | `src/channels/voice.mjs:829` `synthesizeGroq` | Optional path |
| Playback + stop | `src/channels/voice.mjs:881` `playMp3`, `:873` `stopPlayback` | Container-agnostic via ffplay |
| Speech summarising | `src/channels/voice.mjs:1069` `summarizeForSpeech` | Long replies are shortened |
| Voice loop, barge-in | `src/core/cli.mjs:1098` `voiceLoop`, `:986` `speakWithBargeIn` | Insertion point for jobs |
| Turn runner + tool hooks | `src/core/cli.mjs:697` `runTurn` | `onToolCall`/`onToolResult` already exist |
| Approval prompt | `src/core/cli.mjs:543` `confirm` | Reused by a job turn |
| Job cards, `/jobs`, `/bg` | `src/tooling/job-ui.mjs:11` `jobEventText`, `tooling/process/*` | Shell-process jobs, a different concept |
| Provider presets | `src/core/provider.mjs:87` `PROVIDERS` | Add a Baseten preset |
| Config defaults | `src/core/config.mjs:101`…`:121` | Add keys and switches |
| Desktop island | `desktop/electron/island.mjs:143` `islandModeFor` | Owned by the desktop engine |

**Important:** the existing "jobs" are OS processes (`/bg`, `job-status`, `job-wait`).
The new voice job is a delegated **agent task**, not a shell process. Give it its own
module and its own card so the two are never confused.

## 5. Non-goals (explicit)

- No wake word, no always-listening. Push-to-talk or pause-to-send only.
- No arbitrary voice control of every feature; one flow done reliably.
- No UI redesign, no new desktop window, no new dependency.
- No change to default providers: Groq/Edge stay the defaults so existing tests and users
  are unaffected.
- No second demo flow until the first passes three times in a row.
- No claim that the island runs the terminal job unless the desktop bridge actually ships.

## 6. Architecture

```text
 push-to-talk / pause-to-send
        │
        ▼
 [ffmpeg 16 kHz mono WAV]                       src/channels/voice.mjs:141
        │
        ▼
 [Sarvam STT  saaras:v4]                        new: transcribeSarvam()
   transcript + language + confidence
        │   transcript printed before anything runs
        ▼
 [job created: id, status, steps]               new: src/automation/voice-task.mjs
        │
        ▼
 [Agent turn  planner = Muse Spark Open]        src/core/cli.mjs runTurn()
   tool calls execute; each call = one step
        │
        ├── step boundary → spoken line (throttled) + card update
        ├── destructive tool → existing approval gate, status "waiting for approval"
        ▼
 [final report] → spoken (barge-in allowed) + printed + stored in the job record
```

Failure rule: **voice is never a single point of failure.** If STT fails, the typed prompt
still works. If TTS fails, the report prints. If the planner fails, the job fails loudly
with the exact error and the transcript is kept.

## 7. Providers

### 7.1 Sarvam (voice in and out)

**STT** — `POST https://api.sarvam.ai/speech-to-text`, `multipart/form-data`,
header `api-subscription-key`.

| Field | Value | Why |
|---|---|---|
| `file` | the recorded WAV | 16 kHz mono is the documented best case |
| `model` | `saaras:v4` | Current default, supports all output modes |
| `language_code` | `unknown` | Auto-detect; handles Hinglish better than an English hint |
| `mode` | `translit` | Keeps commands in Latin script; tool names and folder names stay readable on video |
| `keyterms` | `["Ankita","VS Code","workspace", …]` | Up to 50 terms; biases recognition, does not guarantee |
| `with_timestamps` | `false` | Not needed |

Response: `{ transcript, language_code, language_probability }`.

**TTS** — `POST https://api.sarvam.ai/text-to-speech`, JSON, same auth header.

| Field | Value | Why |
|---|---|---|
| `text` | chunked at 2000 chars (Bulbul's documented cap is 2500) | Reuses the existing sentence splitter, so nothing is truncated |
| `model` | `bulbul:v4-flash` | ₹1 per 1,000 chars vs ₹3 for v3 |
| `language_code` | chosen from the reply text, not raw detection | see the note below — detection is unstable |
| `speaker` | `sanchita_hi_assistant` / `sanchita_en_companion` / `ishita_enhi_companion` | Assistant-style personas |
| `output_audio_codec` | `mp3` | Reuses `playMp3` unchanged |
| `speech_sample_rate` | `22050` | Default; playback handles it |

Response: `{ audios: [base64] }` → `Buffer.from(base64, "base64")`.

**Measured on this machine, 2026-10-27** (real key, real calls):

- TTS, one Hinglish sentence: **1.4 s**, 59,768-byte valid MP3.
- STT on that audio (`translit`): **444 ms**, transcript
  `Ankita VS Code kholo aur workspace setup karo.`, detected `hi-IN`.
- STT on a short English clip: **193 ms**.
- A Devanagari-input clip came back in Devanagari; script follows the audio. Keep the
  keyterms list and test with the actual filming voice.

**Two findings from repeated runs — both changed the design:**

1. **Auto-detect language is not stable on Hinglish.** The same clip came back `hi-IN`
   (confidence 0.998) on one run, `hi-IN` 0.904, and `pa-IN` 0.453 on another. The
   *transcript* stayed correct every time; only the language label drifted. So the TTS
   language is **not** taken from detection alone: `chooseSarvamLanguage()` reads the
   reply's own script (Devanagari → `hi-IN`), then treats a detected `hi-*` as "speak
   Hindi", a detected `en-*` as "speak English", and anything else as the configured
   fallback. Speaking Hinglish with a Punjabi voice would have been the failure mode.
2. **The assistant's own name is sometimes misheard.** `Ankita` came back as `Anpeta`
   once, with `Ankita` already in `keyterms`. Keyterms bias, they do not guarantee. This
   is why the transcript is printed before anything runs, and why no demo take may show a
   mishearing. Command words (VS Code, workspace, folder names) were correct in every run
   across both scripts.

**Limits and cost** (Sarvam docs): STT REST is for clips under 30 s; 60 requests/min on
pay-as-you-go; TTS same 60/min. Free credits **₹100, never expiring**. STT ₹0.49/min,
TTS ₹1 per 1,000 chars on v4-flash.

**Data handling.** Audio leaves the machine only when the user explicitly speaks. Sarvam's
retention policy is not documented on the pages read for this plan — mark `verify` before
the submission text makes any privacy claim.

### 7.2 Baseten (planner)

- Base URL `https://inference.baseten.co/v1`, OpenAI-compatible Chat Completions.
- Model slug: **`meta-models/muse-spark-open-1026`**. Smoke tested live on 2026-10-27 with
  this machine's key: HTTP 200, ~1.0–1.2 s for short answers. The documented slug
  `meta-models/muse-spark-open` (no suffix) returns **HTTP 403
  `{"error":"please check the api-key you provided"}`** on the same key and same request
  shape — so this is a model-routing rejection, not a bad key. Treat `-1026` as the slug.
- Reasoning is **always on**: `reasoning_effort` accepts `low|medium|high|xhigh` (default
  `xhigh`). Use `low` for job turns; `xhigh` adds latency and tokens for no benefit here.
  Measured even at `low`: 110 reasoning tokens to answer "what is 2+2" (127 completion
  tokens total). Budget `max_tokens` at 400+ or the reply is cut off before any content.
- **Tool calling works**, verified end to end including a `role: "tool"` result round trip
  returning a normal assistant message. This is what the job design depends on.
- **No JSON mode and no structured outputs.** Do not build on a JSON plan.
- Do not send `n > 1`; it returns HTTP 400.
- Rate limits (Basic verified): 120 RPM / 500k TPM — far above this workload.
- Baseten states synchronous Model API requests are not stored (zero data retention).

The repo already supports any OpenAI-compatible endpoint (`src/core/provider.mjs:129`
`CompatibleClient`, `src/core/bootstrap.mjs:14` custom provider), so this is a small
preset plus a key, not a new client.

**Live smoke test, 2026-10-27 (this machine, real key):**

| Probe | Result |
|---|---|
| `meta-models/muse-spark-open-1026`, "reply ready", `max_tokens: 32` | 200, 2.2 s, but content truncated to `<|start|>assistant` — reasoning ate the budget |
| Same model, "what is 2+2", `max_tokens: 800`, `reasoning_effort: low` | 200, 1.04 s, content `"2+2 equals 4."`, 110 reasoning tokens |
| Tool call, `open_app({"app":"VS Code"})` | 200, 0.9 s, correct `tool_calls` array, `finish_reason: tool_calls` |
| Tool result round trip, then "say done in three words" | 200, 1.15 s, content `"VS Code is open"` |
| `meta-models/muse-spark-open` (no suffix) | **403**, `please check the api-key you provided` |

Practical consequence: a small `max_tokens` silently truncates into garbage. The provider
preset must send a floor (≥ 400) and never rely on a 32-token probe to judge health.

### 7.3 Fallbacks, in order

| Layer | Primary | Fallback 1 | Fallback 2 |
|---|---|---|---|
| Ears | Sarvam `saaras:v4` | Groq Whisper (existing) | typed prompt |
| Voice out | Sarvam `bulbul:v4-flash` | Edge TTS (keyless, existing) | print only |
| Planner | Baseten Spark Open | Groq GPT-OSS (existing, **not Meta**) | Kilo free (dev only) |

The last two planner fallbacks are development conveniences. **Neither may appear in the
filmed demo or the submission**, because the Meta fit is what Stage 1 checks.

## 8. The voice job

### 8.1 Record

```js
{
  id,                 // short, e.g. 4f2c
  transcript,         // exactly what STT returned
  language,           // hi-IN / en-IN / ...
  confidence,         // language_probability
  status,             // queued | running | waiting_for_approval | done | failed | cancelled
  steps: [{ index, label, tool, state }],
  startedAt, endedAt,
  summary,            // final report text
  error,              // message on failure
}
```

Persist under the existing config directory (`CONFIG_DIR`), one JSON file per job, so a
crashed terminal does not lose the record. Keep the last N (constant, e.g. 20) to avoid
unbounded growth.

### 8.2 Steps without a JSON plan

Because Spark Open has no JSON mode, the checklist comes from observed work:

- `onToolCall` → append a step, mark `running`, speak one short line.
- `onToolResult` → mark `done` or `failed` from the result.
- Final assistant message → job summary, status `done`.

Step labels use a deterministic verb map (`open`, `write`, `run`, `read`, `browse`) plus the
tool's display name. No extra model call, no parsing risk, no invented steps.

### 8.3 Speech policy

- Start: one short acknowledgement (≤ 4 words). Never a paragraph.
- Step: one line, at most every `VOICE_JOB_SPEAK_MIN_INTERVAL_MS` (proposal: 2500 ms,
  unit milliseconds) and only while no playback is active.
- Approval: "Permission chahiye" plus the tool name; the terminal prompt is authoritative.
- Final: the existing `summarizeForSpeech` output, with barge-in allowed as today.
- Step lines use plain playback (no barge-in mic), because a stray cough during a 1-second
  line should not queue a phantom turn.
- Every spoken line is also printed, so a missed audio never loses information.

### 8.4 Where it hooks in

- `src/core/cli.mjs:697` `runTurn`: add an optional job observer; do not fork the turn
  runner.
- `src/core/cli.mjs:1098` `voiceLoop`: route the transcript through the job, not straight
  into `runTurn`, then keep the existing final-report path.
- `src/core/cli.mjs:543` `confirm`: wrap for the duration of a job to set
  `waiting_for_approval` and speak the approval line.
- New `src/automation/voice-task.mjs`: the record, state machine, step labels, speech
  throttle. Pure functions where possible so tests need no mic.

**Concurrency, stated plainly.** The job runs inside one agent turn in the same process, so
the terminal is busy while it works; the user can switch applications but cannot start a
second Ankita request. That is the deliberate scope cut. True parallel chat needs the
daemon (`src/automation/daemon.mjs:315` `executeRoutine`) and doubles the risk. Say this in
the README; do not imply full concurrency.

## 9. Config additions

Names only; defaults preserve current behaviour. Values come from `.env` or the process
environment (`pick()` in `src/core/config.mjs` already checks both).

| Name | Default | Purpose |
|---|---|---|
| `BASETEN_API_KEY` | empty | Planner key; never committed |
| `BASETEN_BASE_URL` | `https://inference.baseten.co/v1` | Override for testing |
| `BASETEN_MODEL` | `meta-models/muse-spark-open-1026` | Planner slug (verified; no-suffix slug 403s) |
| `BASETEN_MAX_TOKENS` | `4096` | Generation room for file/tool arguments and reasoning; spoken replies stay brief |
| `BASETEN_REASONING_EFFORT` | `low` | `low|medium|high|xhigh` |
| `SARVAM_API_KEY` | empty | Read from env if already set |
| `STT_PROVIDER` | `groq` | `groq|sarvam` |
| `TTS_PROVIDER` | `edge` | extend with `sarvam` |
| `SARVAM_STT_MODEL` | `saaras:v4` | STT model |
| `SARVAM_STT_MODE` | `translit` | Output script |
| `SARVAM_TTS_MODEL` | `bulbul:v4-flash` | TTS model |
| `SARVAM_TTS_SPEAKER_HI` | `sanchita_hi_assistant` | Hindi voice |
| `SARVAM_TTS_SPEAKER_EN` | `sanchita_en_companion` | English voice |
| `VOICE_JOB_SPEAK_MIN_INTERVAL_MS` | `2500` | Speech throttle, milliseconds |
| `VOICE_JOB_KEYTERMS` | `Ankita,VS Code,workspace` | Comma list, max 50 |

Update `.env.example` with the same names and comments. No secret values anywhere in the
repo, the docs, or chat.

## 10. File-level change list

| File | Change | Size |
|---|---|---|
| `src/channels/voice.mjs` | `transcribeSarvam`, `synthesizeSarvam`, `transcribeAudio`, provider/stt resolution, `chooseSarvamLanguage` | ~200 lines — **done** |
| `src/core/config.mjs` | new keys, provider enums, defaults | ~30 lines — **done** |
| `src/core/provider.mjs` | `baseten` preset | ~10 lines |
| `src/core/cli.mjs` | provider-aware `voiceReady`/`transcribeWav`/`synthesizeSpeech`; job hooks in `runTurn` + `voiceLoop`; `/task` command | ~130 lines — **voice half done** |
| `src/automation/voice-task.mjs` | new: record, state machine, labels, throttle | ~250 lines |
| `src/tooling/job-ui.mjs` | render voice-task cards without touching process jobs | ~40 lines |
| `.env.example` | document new names | ~20 lines — **done** |
| `scripts/verify-sarvam-voice.mjs` | live round-trip check, repeatable | new — **done** |
| `README.md` | "new work" section, old vs new table | ~40 lines |
| `docs/guides/voice-delegation.md` | user-facing how-to | new |
| `test/channels/voice.test.mjs` | Sarvam request/response/error tests | ~170 lines — **done** |
| `test/automation/voice-task.test.mjs` | state machine, labels, throttle | ~120 lines |

Deliberately **not** touched: the desktop app, the scheduler, the Telegram channel, the
default provider behaviour.

## 11. Failure matrix

| Failure | Behaviour | Evidence to show |
|---|---|---|
| Sarvam key missing/expired | `voiceReady` explains exactly what to set, typed prompt still works | screenshot + log line |
| STT 429/5xx | one retry with backoff, then "didn't catch that" and a re-record prompt | log + retry |
| Mishearing | transcript prints **before** execution; this does not validate it or pause the turn. Ctrl+C stops work; action approval remains authoritative when auto-approve is off | video shot |
| TTS fails | report prints; job status still `done` | log |
| Baseten 401/402/404 | job fails fast with the exact status; no fake progress | log |
| Baseten 529/429 | bounded retry, then fail with a plain message | log |
| Approval required | status `waiting_for_approval`, spoken line, existing prompt | video shot |
| Ctrl+C during job | status `cancelled`, spoken "cancelled", partial steps kept | trace |
| Terminal crash | job JSON on disk shows where it stopped | file |

## 12. Day-by-day, with pass/fail gates

Weekdays: school until 13:30 IST, so build in the afternoon/evening. Saturday 31 Oct and
Sunday 1 Nov are full days. Features freeze 3 Nov.

| Day | Work | Gate (do not proceed otherwise) |
|---|---|---|
| **Tue 27 (tonight)** | ~~Put `BASETEN_API_KEY` in `.env`; smoke test~~ **DONE** — key present, `-1026` slug 200, tool calling verified, Sarvam round trip verified. Remaining: listen to one TTS clip | **Cleared**, except the by-ear voice check |
| **Wed 28** | ~~Sarvam STT/TTS in `voice.mjs`; provider-aware voice gate; unit tests~~ **DONE early on 27 Oct** (see §18). Remaining: the same through the mic in `/voice` | Live Hinglish utterance → correct transcript → spoken reply, three times |
| **Thu 29** | `voice-task.mjs`; job card; steps from tool calls; spoken final report | One spoken command opens VS Code, creates the folder/files, speaks the report |
| **Fri 30** | Spoken step updates, approval status, failure paths, `/task` list | Three deliberate failures do not break the demo |
| **Sat 31 (full)** | Hinglish demo flow ×3 in a row; English backup take; film rough shots | 3/3 clean runs |
| **Sun 1 (full)** | Desktop pass **only if** Saturday is green; otherwise bugfix only | Desktop: mic → Sarvam → job → island visible. Miss it, drop it |
| **Mon 2** | README old-vs-new, user guide, submission draft, rough cut | Submission text complete, not outlined |
| **Tue 3** | Final 3-minute video, submission page, office hours if blocked | Everything submittable, one day early |
| **Wed 4** | Submit evening IST; fixes only | Links re-checked from a logged-out view |

Cut order if time runs short: desktop pass → second flow (never built) → spoken step
updates (keep the final report) → **never** the core loop.

## 13. Demo video (3 minutes, new work only)

| Time | Shot | Audio / on screen |
|---|---|---|
| 0:00–0:15 | Desk, Ankita idle | "Setting up a workspace by hand is dead time. Watch." |
| 0:15–0:35 | Speak Hinglish | Transcript appears on screen before anything runs |
| 0:35–1:05 | Job card | id, status `running`, steps filling in; speaker turns to other work |
| 1:05–1:50 | VS Code | Folder and files appear; one spoken progress line; approval gate shown briefly if it fires |
| 1:50–2:20 | Report | Spoken summary; the same text on screen; status `done` |
| 2:20–2:50 | Old vs new | Five new items on screen; say plainly that voice capture/playback already existed |
| 2:50–3:00 | Repo | Public URL; optional 10 s island shot only if it is real |

Rules: re-shoot, never submit a mishearing; keep the transcript visible in every voice
shot; test the video link logged out.

## 14. Cost

Verified prices (Sarvam docs, 2026-10-27): STT ₹0.49/min; TTS ₹1 per 1,000 chars for
`bulbul:v4-flash`; ₹100 free credits that never expire.

One filmed take (6 s speech, three 50-char progress lines, 180-char report):

- STT: 6 s = 0.1 min × ₹0.49 = **₹0.049**
- TTS: 330 chars × ₹1/1000 = **₹0.33**
- Per take ≈ **₹0.38**; 60 takes ≈ **₹23**, well inside the free ₹100.

Baseten planner cost is not published on the pages read; mark `verify` and check the
workspace usage page after the first day. The hackathon credit pot is a PDF claim, not
verified here.

## 15. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Baseten key has no credit or wrong slug | Submission fails the Meta gate | **Cleared 2026-10-27**: `-1026` slug answers 200, tool calling works. Only the no-suffix slug 403s — never use it |
| Sarvam mishears on the filming mic | Bad take | Keyterms, transcript-first, re-record; keep `translit` |
| Voice sounds wrong for English words inside Hinglish | Demo quality | Listen before filming; try `ishita_enhi_companion` vs `sanchita_hi_assistant`; keep English backup take |
| Job looks fake because the terminal is busy | Judge doubt | State the scope cut in the README; show the job card and the actual tool calls |
| Desktop pass eats the weekend | Missed video | Hard gate Saturday evening; drop it without regret |
| Heartbeat work mixed into the diff | "New work" claim collapses | Branch precondition below |
| 18+ waiver | Prize ineligible | No false signature; ship the work, claim nothing |
| Credits do not land | Blocked build | Sarvam is already usable; Baseten is the only dependency |

## 16. Preconditions and branch hygiene

Current state (2026-10-27): branch `feat/heartbeat-proactivity`, **30 modified files**,
uncommitted. Do not start hackathon work on top of that.

1. Commit or stash the heartbeat work (owner's choice).
2. Cut `feat/voice-delegation` for this build, so the submission diff is exactly this
   week's work.
3. Keep `.env` untracked (already ignored); keys never enter git.
4. Tag the submission commit on 4 Nov and archive the demo video link.

## 17. Submission checklist

- [ ] Repo public; submission commit tagged; branch diff = hackathon work only
- [ ] 3-minute video, new work only, transcript visible, link tested logged out
- [ ] Submission filed on the CV platform; representative Krish, solo; members: Krish only
- [ ] Theme named once: **Build for Your World**; track: **Indie Developer**
- [ ] README states the five new items and that voice capture/playback predates the event
- [ ] README discloses Sarvam for speech and the Meta planner honestly
- [ ] Submitted by evening IST 4 Nov (hard deadline 5 Nov 07:30 IST)
- [ ] Checks the published rubric on the submission page — do not assume weights

## 18. Verified vs unverified

**Verified on 2026-10-27, on this machine**

- Sarvam key present and working; live STT/TTS round trip; latencies above.
- Sarvam endpoints, headers, model names, modes, speaker IDs, prices, free credits, limits.
- **Baseten key works.** `meta-models/muse-spark-open-1026` → 200; tool calling and
  tool-result round trip both work; short-answer latency ~1.0 s at `reasoning_effort: low`.
- The no-suffix slug `meta-models/muse-spark-open` → 403 on the same key.
- Baseten base URL, always-on reasoning and its token cost, no JSON mode, rate limits,
  zero data retention for synchronous requests.
- Kilo's keyless Meta models return `401 PAID_MODEL_AUTH_REQUIRED`.
- The repo's Groq key has no Meta Llama model.
- Repo touch points, config shape, provider preset mechanism, island ownership, ffmpeg and
  ffplay present.

**Unverified — must be settled before it is claimed**

- Baseten credit balance, remaining spend, and end-to-end planning latency inside a real
  job turn (only single-shot calls have been measured).
- Audio quality by ear; only transcript accuracy was measured.
- Sarvam data-retention terms.
- Desktop island integration effort; estimated, not measured.
- Hackathon rubric details; the PDF's tables were placeholders.
- Baseten pricing and the two credit pots; PDF claims only.

## 18a. Implementation status — Sarvam voice (2026-10-27)

Shipped on `feat/voice-delegation`:

| Piece | Where | State |
|---|---|---|
| Sarvam STT (`saaras:v4`, `translit`, keyterms) | `src/channels/voice.mjs` `transcribeSarvam` | done |
| Sarvam TTS (`bulbul:v4-flash`, MP3) | `src/channels/voice.mjs` `synthesizeSarvam` | done |
| Provider-agnostic transcription | `src/channels/voice.mjs` `transcribeAudio` | done |
| Language selection that survives jumpy detection | `src/channels/voice.mjs` `chooseSarvamLanguage` | done |
| Provider-aware voice gate (no longer Groq-only) | `src/core/cli.mjs` `voiceReady` | done |
| Config keys + `.env.example` documentation | `src/core/config.mjs`, `.env.example` | done |
| Repeatable live check | `scripts/verify-sarvam-voice.mjs` | done |

Verification actually run:

- `node --test test/channels/voice.test.mjs` → **41/41 pass** (13 new Sarvam tests:
  form fields and auth header, keyterms handling, 403 wording, one-retry-on-429, base64
  decode, chunking above the 2000-char cap, empty-audio error, provider/speaker/language
  resolution, config defaults).
- `node --test test/channels test/core` → **358/358 pass**.
- `node --test test/automation` → **106/106 pass** (the daemon imports the changed
  voice helpers).
- `node scripts/verify-sarvam-voice.mjs` → **2/2** real round trips through the real
  modules: MP3 → 16 kHz mono WAV (what `startRecording` writes) → transcript, then the
  reply direction in the chosen voice. Latest run: Hinglish 1.09 s TTS / 251 ms STT,
  `hi-IN` at 0.982; English 0.87 s TTS / 269 ms STT, `en-IN` at 1.0.
- `node chat.mjs --config` shows the new rows and never prints a key value.

Still open:

- The **mic** path (`/voice` with a real voice) has not been exercised — the module-level
  round trip is audio-equivalent, but a human has to speak. Gate for Wed: three clean
  runs, by ear.
- Nobody has listened to Bulbul's pronunciation of English words inside Hinglish. That is
  the one judgement only the owner's ears can make, and it decides
  `sanchita_hi_assistant` vs `ishita_enhi_companion`.
- `.env` now sets `STT_PROVIDER=sarvam` and `TTS_PROVIDER=sarvam` so the build runs on
  Sarvam; deleting those two lines restores Groq/Edge exactly.

## 18b. Voice latency continuation (2026-10-27)

- Inherited uncommitted latency work was checkpointed as `d36ded6` before further edits.
  This is a WIP checkpoint, not a completion claim.
- Voice-only provider resolution now happens after `/voice` reloads configuration.
  Invalid/missing planner credentials stop voice entry instead of silently switching away
  from Meta. Typed chat keeps its own provider and model.
- Voice turns pin the complete tool loop to the selected planner and restore the chat
  client, tool model and active-model fields even after an exception or cancellation.
- Baseten sends `reasoning_effort=low`, a default 1024 output-token budget, and a
  400-token floor even if a smaller explicit cap is requested. Other providers keep
  their existing request settings. Endpoint overrides now win over preset endpoints.
- Short acknowledgement clips are cached before listening, in Hindi and English;
  failed clips are skipped. Each acknowledgement is printed as well as played.
- Local ignored `.env` now selects `VOICE_PROVIDER=baseten`, the pinned voice model,
  and `VOICE_SILENCE_MS=800`. This last setting saves 400 ms relative to the previous
  1200 ms pause, but still needs the owner's mic test for premature cut-offs.
- New regressions: **5/5** failed before implementation, then **5/5** passed;
  combined provider/voice-session run **19/19** passed.
- Live request through the real `Agent` + voice-only client: **1121 ms to first text,
  1142 ms total**, answer `I am ready`, pinned Meta model. This measures model response,
  **not microphone-to-first-sound latency**. Historical timings in §7 used different
  prompts; they are not a controlled before/after comparison.
- The current checkout had a Baseten key but **no Sarvam key** at continuation time.
  Owner is restoring it locally. Speech checks and the real three-run mic gate remain
  open; no desktop/island work is authorized by this result.
- The previous conversation exposed a Baseten key. Owner was asked to rotate it;
  no secret values are printed by these checks or committed.

## 18c. Tracked terminal delegation continuation (2026-10-27)

Implemented after the latency checkpoint `542cf9c`:

- `src/automation/voice-task.mjs` stores bounded atomic records under
  `CONFIG_DIR/voice-tasks`, with transcript/language/confidence, actual tool steps,
  approval state, summary, error and start/end times. `/task [id]` reads them.
- The CLI supplies an observer to the existing turn runner. No JSON plan, second
  agent or parallel conversation is introduced. Process-job controls are unchanged.
- Progress speech is throttled and never queued. Approval/completion cancels stale
  progress playback; even synthesis that ignores cancellation cannot hold the task
  open. Its already-issued network request may still finish in the background.
- Approval callbacks capture the original task and abort signal, so a cancelled
  permission clip cannot reopen a question during a later turn. Existing action
  approvals remain authoritative. An explicit planner rejection stays a failed job;
  it does not refresh an unrelated chat token or switch away from Meta.
- The voice planner temporarily uses its own context budget and restores the typed
  budget afterward. The pinned Muse model uses the documented full window unless
  the owner supplies `VOICE_CONTEXT_WINDOW` or an explicit shared context limit.
  Source: [Meta's Baseten deployment guide](https://dev.meta.ai/docs/muse-spark-open/deploy).
  The original full-CLI reproduction wrote a file then failed with
  `The current request/tool schema exceeds the model context budget`; the new
  context-switch regression and full CLI success path now pass.
- Configured secrets and credential-shaped strings are redacted **before JSON
  encoding**. Raw tool arguments/results are excluded. Failed work cannot speak a
  planner-generated success claim as its whole report; core verification verdicts
  are also carried into step state.
- Sarvam synthesis errors now try the existing Edge engine, with a visible fallback
  message. If both fail, the saved/printed report remains. A simulated Sarvam outage
  through the real CLI confirms fallback and an unchanged successful task result.

Evidence from this continuation:

- `node --test --test-concurrency=1 test/automation/voice-task.test.mjs
  test/core/voice-session.test.mjs test/core/voice-cli.test.mjs` exercises durable
  state, parallel result correlation, denial, failure, cancellation, failed storage,
  stalled speech, secret-shaped text and restoration of typed chat. Latest individual
  runs: **17/17 task tests**, **5/5 voice-session tests**, **6/6 CLI tests**.
- The CLI tests run the actual terminal loop and real file tools against a local HTTP
  model fixture, with fake mic/synthesis/playback. They cover success, Sarvam failure,
  planner 403, cancellation and cancellation during delayed approval speech.
- Final affected-suite run:
  `node --test --test-concurrency=1 --test-reporter=spec "test/channels/*.test.mjs"
  "test/core/*.test.mjs" "test/automation/*.test.mjs"` → **493 tests, 493 pass,
  0 fail, 0 cancelled, 0 skipped**, **111927 ms**, exit 0. Full local trace:
  ignored `.voice-verification.log`. `node --check src/core/cli.mjs` and
  `git diff --check` also passed. The whole repository/packaged desktop suite was
  not run; these are the affected channel/core/automation suites.
- Real Sarvam check: **2/2** Hinglish/English round trips. Latest successful values:
  STT **277/789 ms**, report TTS **830/813 ms**. One earlier request was rejected as
  longer than 30 seconds; subsequent probed clips were short, and the original check
  passed on repetition. Its original cause is **unresolved**, not claimed fixed.
- `node scripts/verify-voice-delegation.mjs` completed **3/3 synthetic speech
  delegations** through real Sarvam, real pinned Meta planning, real `write_file` /
  `read_file`, actual approval callbacks, durable records and final report synthesis.
  Final transcripts all preserved `Workspace mein ek file banao aur usko padhkar batao.`
  Latest STT **309/268/292 ms**; task durations **3378/3408/3658 ms**; report synthesis
  **1376/1011/1000 ms**. Ack cache lookup **0.068/0.008/0.009 ms** is memory selection,
  **not audible onset**. Playback was not requested in that run. Short progress clips
  were cancelled at the approval/completion boundary; no live step audio is claimed.
- A real typed one-shot returned `ok: true`, model `reflection/beam-free`, text
  `Hey there, krish!`, **1629 ms**. The pre-existing configured StepFun route was
  unavailable, so the ordinary Kilo resolver chose that free model; voice did not
  alter the typed provider.
- An independent read-only review found stale approval, JSON redaction, misleading
  spoken success and stalled progress finalization issues. Each has a failing
  reproduction followed by a passing regression in this continuation.
- Literal review: endpoints/models/context sizes and retention/speech timing defaults
  are named constants or configuration. Tool verbs, statuses and command vocabulary
  are protocol/UI values. Fixture paths, fixed sample content and timings used for
  testing remain in tests/scripts. `.env` is ignored and no key values are staged.

Remaining gates and limitations:

- **Physical microphone gate: 0/3 observed here.** The owner is ready to try it.
  Actual headset routing, audible first-response latency, Hinglish pronunciation,
  physical Ctrl+C/barge-in, actual VS Code opening and three clean mic takes still
  need the owner. Generated-audio service runs do not clear this gate.
- The terminal remains occupied while work runs. No true concurrent chat or
  desktop/island bridge has been built. No packaged desktop verification is claimed.
- Node 24 on Windows hit a libuv assertion at forced process exit in the fixture's
  zero-duration fake-audio runs. The fixture captures the requested exit and lets
  sockets close naturally; production teardown was not changed. Physical terminal
  shutdown remains part of the owner check; this is not claimed fixed.
- Live Edge synthesis was attempted after the fallback routing test and returned
  `Edge TTS handshake failed: HTTP 403`. Fallback routing is stub-driven **6/6** CLI
  coverage; the existing Edge service is currently unavailable here. Sarvam live
  speech passes; if both speech engines fail, output remains printed/saved. No Edge
  service repair or claim of working live fallback is included in this scope.
- Transcript display is visibility, not validation. It does not stop auto-approved
  work. Use Ctrl+C on a mishearing and action approval prompts when needed. A draft
  test phrase `demo note` was misheard twice; the final verifier asserts its command
  nouns so those takes cannot pass silently.
- No controlled identical-prompt before/after microphone-to-sound benchmark has
  been performed. Sarvam retention terms and Baseten balance/pricing remain open
  from §18. The earlier exposed Baseten key still needs rotation by its owner.

## 18d. First-mic feedback: natural speech and clean boundaries (2026-10-27)

The owner ran real microphone conversation turns and a request to write a poem and
open it in Notepad. Feedback: the final voice sounded good and tool execution was
fast, but intermediate speech cut off and ran into the next sentence. The fixed
spoken labels were too robotic. This is a real delivery bug, not just presentation.
The three-clean-workspace-demo gate remains open.

Reproduction and fix:

- The prior `runVoiceTask` interrupted all progress at approval/completion. Regressions
  reproduced that a currently playing line was aborted and permission did not wait.
  Speech now distinguishes preparation from playback: stale preparation is cancelled,
  started playback finishes, and a configurable **300 ms gap** separates clips.
  Ctrl+C interrupts immediately. A named **15000 ms playback ceiling** handles a
  stuck progress player without an unlimited completion wait.
- Tool names are now record labels only. A separate compact request to the chosen
  voice model generates one short sentence from the transcript and observed action.
  It runs beside tool execution, receives no tool arguments/file contents or memory,
  makes no tool calls, and has a **3000 ms deadline**. Internal recall/discovery/todo
  work is not narrated. The cached acknowledgement remains an immediate receipt.
- Every **10000 ms** of active long work may generate a fresh waiting update.
  Timer/throttle settings are named config values. No reminders run while awaiting
  permission, and no fabricated finish time is allowed. No true concurrent chat or
  daemon has been introduced.
- Voice mode hides reasoning/raw tool dumps and repeated counters by default; full
  step records remain available through `/task`. `VOICE_VERBOSE=on` opts into traces.
  The final spoken text now comes from `Agent.send`'s returned final reply; earlier
  tool preambles cannot be concatenated into it, including on cancellation.
- A fresh review found cancellation during the new completion grace period could
  still save success. The regression first returned `done` instead of `cancelled`;
  finalization now rechecks the requesting turn after playback settles. The real CLI
  fixture also cancels during this gap and confirms there is no spoken success.
- Generic compatible providers now inherit only their own request defaults. A
  regression rejects accidental injection of Baseten-only reasoning settings.

Verification:

- Targeted scheduler/narrator/CLI checks cover ordered playback, spacing, hanging
  synthesis/player, proactive timers, approval, cancellation during completion,
  hidden reasoning and intermediate content, safe narration inputs and provider
  portability. Final affected-suite command:
  `node --test --test-concurrency=1 --test-reporter=spec "test/channels/*.test.mjs"
  "test/core/*.test.mjs" "test/automation/*.test.mjs"` → **502 tests, 502 pass,
  0 fail, 0 cancelled, 0 skipped**, **129019 ms**, exit 0. Ignored full trace:
  `.voice-polish-verification.log`. The actual CLI fixture subset passed **8/8**.
  Syntax checks for the CLI, task controller, narrator and verifier, plus
  `git diff --check`, passed.
- `node scripts/verify-voice-delegation.mjs --narration-only` → **3/3** real model
  updates and real Sarvam audio (playback skipped). Latest English step/wait model
  times **2499/1747 ms**; Hinglish **2682 ms**. Generated examples:
  `Writing your random poem and getting Notepad ready, I'll let you know when it's done.`
  and `Aapki kavita likhne ka kaam chal raha hai, pura hote hi yahin update karungi.`
  Audio sizes **84427/88189/63947 bytes**. One prior live probe returned no acceptable
  narration; optional updates can be skipped on deadline/length/provider failure.
  This does not fail the work or delay its final report.
- The generated `poem.txt` from the owner's test is kept untracked and untouched.
  No recordings, keys or local verification logs are staged. All prior source work
  was committed before this polish; no implementation is based on the poem artifact.

Still uncovered: by-ear/headset verification of the new sentence spacing and natural
updates after restarting the old process; a full physical workspace demo; packaged
desktop checks. The earlier Notepad request retried after a workspace-boundary error,
so its task remained failed even though a later write/launch succeeded. That strict
retry outcome and proof of a visible Notepad window are recorded findings, not fixed
or claimed verified by this speech polish. Existing Edge 403 and Sarvam retention /
Baseten balance questions remain as recorded above.

## 18e. Reply delay and brief voice answers (2026-10-27)

Owner feedback: speech boundaries improved, but final replies still had a 5–10 s
gap. Voice replies must be crisp: one or two short sentences, without repeated
greetings, recaps or extra offers. This continuation changes terminal voice only.

Cause and changes:

- The prior CLI synthesized the final audio, then scanned for the microphone again,
  then waited for interruption input startup. Real read-only discovery probes took
  **1040/537/665 ms**. `openVoiceInput` also has an existing **1000 ms** startup guard.
  These independent waits were on the final answer's serial path.
- Microphone discovery is now shared within each voice session, including capture,
  headset routing and interruption input. A failed device invalidates it so the
  next attempt discovers devices again. No device names or OS assumptions are added.
- Final speech synthesis and interruption-input startup now run together. Failure
  closes the attempted input; Ctrl+C during preparation drops the late audio and
  closes the input. Started progress sentences still finish with their existing gap.
- A scoped voice instruction asks for one or two short sentences and puts longer
  requested content in the artifact. Essential failures and permissions remain
  required. Existing instructions are preserved; typed turns restore their own
  style and provider. No second model call is added to shorten the answer.
- One live response still produced three sentences despite that instruction. Final
  TTS now also takes only the first two sentences, while the printed/saved report
  remains whole. The voice-specific boundary includes Hindi danda punctuation;
  failures retain their leading failure notice. No extra summary-note sentences
  are appended. `/say` and typed speech retain their existing settings.

Reproduction and evidence:

- The real CLI fixture first failed because `REPORT_SYNTH_READY` preceded
  `BARGE_OPEN`; discovery ran three times. It now opens input while speech is being
  prepared and discovers once per session. Additional cases cover disconnected
  input cleanup, forced rediscovery, cancellation before playback, provider request
  instructions and typed-chat isolation.
- A read-only review found retry rediscovery could throw outside the recording
  handler. A rejecting-detector regression first exited the CLI with code 1; retry
  discovery now uses that same handler and can recover on the next capture.
- `node scripts/verify-voice-latency.mjs` exercises the actual CLI, real Meta model,
  real Sarvam synthesis and real device discovery. It simulates the existing
  1000 ms microphone startup and skips audio playback/recording. It measures from
  the supplied transcript to final-player handoff, excluding STT, pause detection,
  audio-device startup and actual hearing. No keys, prompts or answers are logged.
- The same script against a disposable tracked snapshot of **b1b540a1** measured
  **4074/4694/3613 ms**. Latest updated run measured **3024/2164/2349 ms**, **3/3**,
  with **two sentences in each response** and **one device discovery** across all
  three turns. Median preparation fell from **4074 to 2349 ms** (about **42%**).
  Earlier updated runs included **2218/2157/2246 ms** and **2374/2697/2117 ms**; cloud
  timing varies. These measurements do not prove physical headset latency.
- Final affected suite:
  `node --test --test-concurrency=1 --test-reporter=spec "test/channels/*.test.mjs"
  "test/core/*.test.mjs" "test/automation/*.test.mjs"` → **510 tests, 510 pass,
  0 fail/cancelled/skipped**, **123412 ms**, exit 0. Full ignored trace:
  `.voice-latency-verification.log`. Focused CLI/session checks passed **21/21**.
  The cap regression first spoke the third sentence, then passed after the cap;
  Hindi punctuation likewise reproduced before its scoped boundary fix. A real
  Hindi Sarvam synthesis of the two-sentence result returned **39288 bytes**;
  playback was skipped. Syntax checks and `git diff --check` passed. Source literal
  review found only named voice policy constants, protocol/format values and
  test/script fixtures; no new inline provider/device/environment assumptions.
- The generated-speech/file verifier completed two real STT → file write/read →
  speech runs, then failed its command-noun check on take three. It is **2/3**, not
  a clean three-take pass. This existing recognition risk remains open; no STT model
  or keyword settings changed. The separate real planner/file check passed **3/3**,
  with actual write/read steps and approval, at **3439/3291/3139 ms** task time.

Remaining gaps: restart and listen on the physical headset; repeat the three clean
workspace demonstrations; loaded long conversation/MCP latency and packaged desktop
remain unmeasured. This comparison uses short conversation turns and simulated mic
input, not the owner's full active session. Existing Edge 403, recognition errors
and strict recovered-tool-failure reporting remain as recorded above. `poem.txt`
is preserved untouched and untracked.

## 18f. Save-findings requests exhausted the planner budget (2026-10-27)

Owner report: conversation, Wi-Fi lookup and research completed, but two requests
to save the findings to Markdown failed with `The planner returned no final report.`
Saved records `3f74c03f-deaf-49d0-a033-7c5991716f03` and
`7cc68683-bc6a-48a1-ab14-a3ded23e6e51` contain only completed recall steps, no
write step, empty summaries, and durations **6211/4785 ms**. No file write from those
requests is claimed. The research claims themselves were not audited in this fix.

Diagnosis:

- Replayed the saved conversation through the real planner without executing its
  proposals. With the prior **1024-token** budget, two of three streamed requests
  ended with `finish_reason: length`, **1024 completion tokens**, empty content and
  no tool calls, in **4543/4295 ms**. The remaining take produced a complete tool
  request at **960 tokens**. A nonstream 1024-token probe happened to fit, confirming
  this is output-length dependent, not a reliable endpoint/authentication failure.
- File content is part of the generated tool-call arguments. Limiting spoken reply
  length with a tiny generation budget therefore also prevented longer file saves.
  The parser previously treated any finish reason, including `length`, as ordinary
  completion, so the task tracker could only report the generic empty final reply.

Fix:

- Baseten's named default output budget is now **4096 tokens**. Explicit token
  settings remain respected. The existing voice instruction and final two-sentence
  speech cap remain in place; a larger allowance does not request a longer reply.
- Both streaming and JSON responses reject `length` completion with
  `provider_output_limit` and a clear explanation. No partial proposal is executed,
  even if its JSON happens to be valid. The same capped request is not retried as
  a network failure; earlier completed tools are not rerun.
- Billed usage is retained, including an SSE usage-only trailer after the finish
  frame. A review caught the initial early throw losing that trailer; its regression
  first observed **0 instead of 1024** completion tokens, then passed after deferring
  rejection until the trailer is read. A stream failure after a known length stop
  retains the output-limit classification rather than triggering a network retry.
- `.env.example` and setup guidance show the new default. No key or owner file was
  changed; `poem.txt` remains untracked and untouched.

Live verification:

- Replayed the same saved conversation with the new **4096-token** setting, without
  executing proposals: **3/3** complete, valid `write_file` requests in
  **4391/4340/3965 ms**. Completion counts **2203/3716/1807 tokens**, argument lengths
  **3898/3764/3307 characters**. These requests would exceed the old allowance.
- `node scripts/verify-voice-delegation.mjs --planner-only --long-report` → **3/3**
  real write/read/approval runs. Each saved **5502 characters** to a temporary
  Markdown file, compared its entire content, then returned a short final report.
  Task times **5833/5439/5830 ms**. The fixture is explicitly synthetic, not a
  security advisory; temporary workspaces are removed.
- `node scripts/verify-voice-latency.mjs` → **3/3**, two sentences each, final-player
  handoffs **2512/2247/2327 ms** with real model/TTS/discovery and simulated input.
  No recording or playback; the physical demonstration gate remains open.
- Final affected-suite command:
  `node --test --test-concurrency=1 --test-reporter=spec "test/channels/*.test.mjs"
  "test/core/*.test.mjs" "test/automation/*.test.mjs"` → **518 tests, 518 pass,
  0 fail/cancelled/skipped**, **160078 ms**, exit 0. Ignored trace:
  `.voice-report-verification.log`. The focused stream/session checks passed
  **25/25**; the real CLI fixture includes the clear output-limit error, no file
  write, no identical retry and unaffected typed chat. All six transport/proposal
  regressions first failed before the guard; the request-budget regression first
  observed **1024 instead of 4096**. Syntax checks, literal review and
  `git diff --check` passed. No new environment, endpoint or device assumptions.

Remaining limits: reports exceeding the configured output budget can still fail,
but now identify the cause and cannot execute their cut-off proposal. Full original
MCP connections and physical headset interaction were not replayed. This fix does
not audit the security advice, recover the user's missing file automatically, or
claim the original failed requests succeeded.

## 18g. Desktop voice panel and island (2026-10-27–28)

Built in an isolated `feat/desktop-voice-orb` worktree from committed PR #70.
The owner approved a blue/lilac fluid orb, animated short captions, a full app
panel and the same session in the floating island. On 28 October they rejected
the first orb and liquid-looking contour study, then explicitly chose smooth dark
pearl with a soft silver edge. The final original shader has no mesh or liquid
folds. Mic level drives listening, recognition/work get distinct moving rim lights,
speaking pulses gently, and a completed task gets a single confirmation ring.
Reduced motion stays still and CSS supplies a static fallback; hidden cues pause.
No supplied reference bitmap is bundled. This is new hackathon work;
existing desktop layout, capture/playback, permissions and agent tools are reused.
The independently reviewed desktop commits are added to PR #70 under the owner's
instruction to include all pending changes. The original committed terminal,
heartbeat and phone-pairing baseline remains identifiable at `b88b1f5d`.

One main-process coordinator owns audio and the conversation. Real ffmpeg RMS
drives input motion. Existing desktop turns provide model/tool/approval/history
receipts; voice temporarily uses the configured Baseten Meta planner and concise
style, then restores the typed model. No new dependency or CSP exception was added.
The public cross-window state is bounded and excludes credentials/tool payloads.

End voice closes audio while already delegated work continues on the original
thread. Stop work cancels it. Switching threads ends voice; permission UI retains
priority, and restoring from the island selects its owner. Silent capture deadlines
do not send audio to STT. Late transcription/synthesis cannot enter a new session.
Settings add private local Sarvam/Baseten key entry and microphone discovery.
ChatGPT Browser voice is explicitly unsupported in this pass.

Evidence:

- New lifecycle, engine, shared-state, audio and UI checks passed. Each new behavior
  was exercised red before implementation; final focused counts are recorded below.
- Desktop typecheck and Vite build passed. Browser fixture:
  `node scripts/verify-desktop-voice-ui.mjs` → `DESKTOP_VOICE_UI_OK`, **0 page errors**,
  covering main/island, permission priority, owner restoration, short/narrow windows,
  Hindi text, reduced motion, WebGL fallback, pause/resume and end/cancel controls.
- A shorter-window caption check first measured **84 px text in a 57.078125 px box**.
  Reserving caption space and reducing the orb at short heights made it pass.
- `node scripts/verify-desktop-voice.mjs --env <local-env>` →
  `DESKTOP_VOICE_NATIVE_OK`: real Sarvam generated speech → STT → Meta
  `meta-models/muse-spark-open-1026` → actual write/read tools → **269-character
  kavita.txt**, **2 real MP3 handoffs**, **13507 ms** including UI/native evidence,
  **0 page errors**. Typed model restored to the separate fixture model. Actual
  Electron main and late-subscriber island screenshots were inspected. The real
  island became focusable and Tab/Space ended voice through its button.
- The independent review found five important recovery issues: main remount,
  inactive island errors, pausing during input startup, native island focus and
  swallowed player failures. Each has a red-to-green regression. The final focused
  channel/desktop/settings/native-control set passed **98/98** with no skips.
  Strict player error reporting is opt-in for desktop; intentional cancellation
  and existing best-effort callers retain their behavior.
- The first desktop-branch full suite ran **1628 tests: 1619 pass, 8 fail, 1 skip**.
  Seven failures came from applying an absent optional voice snapshot in existing
  UI bridges; one came from delaying native-control cancellation behind audio
  shutdown. Both were reproduced and fixed. All seven affected UI fixtures passed
  in a focused rerun; native-control/voice-engine checks passed **15/15**. The final
  all-source serial rerun after the combined fixes reported **1635 tests: 1633
  pass, 1 fail, 1 skip**. The only failure was an `EPERM` after-hook removing an
  unchanged browser-observations temporary directory on Windows. Both actual
  observations passed; the same file rerun passed **2/2**. No all-suite-green
  claim is made and no unrelated cleanup code was changed.
- The first broad test command discovered 25 failures in ignored generated launch
  website fixtures; those files are outside the tracked app change. A tracked-source
  run passed 1600 tests, with one process-ancestry fixture failure after its launcher
  exited; the same process suite passed **2/2** under a live launcher. The final
  desktop-branch serial suite is recorded above.
- Final dark-pearl desktop build passed; the browser fixture returned
  `DESKTOP_VOICE_UI_OK`, **0 page errors**, including successful shader compilation
  in both surfaces, distinct state cues, success-only motion, hidden fallback cues
  and identical reduced-motion frames. Actual wide-panel and compact-island
  screenshots were inspected after the owner's final material choice.
- The final focused voice/channel/core/automation/desktop/provider/settings set
  passed **168/168** with no skips after the material/state-animation revision.

Limits: native input/VAD are generated fixtures and speaker handoffs are captured,
not a physical headset test. One generated Hinglish take misheard “Markdown” as
“mark count”; the successful request asked for a generic saved poem and does not
claim that technical noun passed. Physical barge-in, the owner's three-clean-workspace
gate, packaged distribution and current GPU-driver coverage remain open. Browser
fallback/motion fixtures do not close those gates. A minor deferred polish issue is
the collapsed island's ordinary status text; the expanded voice view is accurate.
The app starts a fresh voice session; the island continues or retries that session.
PR #70 remains draft. No default-branch merge, tag or release performed.

## 18h. Accurate progress and simultaneous completion (28 October)

Owner report: the voice described writing/opening vaguely and could repeat an
obsolete action. Reproduction failed three regressions: a write preparation was
not aborted when the write finished, there was no latest-update coalescing, and
the narrator had neither completed-file facts nor the launch executable context.

The observer now supplies bounded, ephemeral file/program basenames and actual
step states. Raw file contents, command arguments/results and full paths are not
sent to narration or persisted as task metadata. A live command which yields a
background job is only `submitted`, including an implicit foreground-to-background
yield. The narrator distinguishes disk saves from app typing and launch requests
from a visible app opening. It receives the previous actually played update.

Newer steps/results replace unplayed preparation. Only one newest pending update
survives while a sentence plays; approval/final reports drop that queue. Finished
sentences retain their gap. The terminal prints an update only when playback
actually begins. Fast steps can be silent rather than describe stale work.
Optional narration uses a separate compact output budget and still fails silently
at its three-second deadline rather than holding up a result.

Evidence: three failing-before regressions became green; the focused voice/core/
automation/desktop/provider/settings set passed **175/175** with no skips. A real
Meta/Sarvam narration check first passed **4/4** English/Hinglish cases, including
“Poem saved, now opening it in Notepad” and “Kavita file save ho gayi hai, Notepad
mein kholna abhi baaki hai.” A repeated run skipped its final optional line at the
three-second deadline; that is recorded as a timeout, not an all-pass result.

A same-tick two-task completion regression preserved both task IDs/reports and
allowed only the current session to speak; the ended session remained silent.
Separate conversations still have no general shared-file/app lock. The owner was
asked about overlap and explicitly requested parallel voice execution rather than
either serial option. That supersedes the earlier concurrency deferral; build
isolated workers, a single speaker and shared-resource guards as a separate
follow-up. Until it passes, no concurrency/file-lock guarantee or physical
microphone acceptance is claimed. Optional narration also encountered a skipped
empty response in a compact-budget probe; keep enough allowance for mandatory
reasoning and retain the deadline/skip behavior.

## 18i. Parallel voice execution (28 October)

The owner's explicit parallel-voice instruction supersedes the earlier deferred
concurrency and proposed serial queue/busy policy. New voice requests now run in
fresh Agents with separate history, abort signals, captured workspaces and normal
permissions. Typed/scheduled turns keep their existing execution policy. Private
`voice_jobs` controls expose live same-owner status/results/dependencies and
individual/all cancellation only to voice workers. Four ordinary workers by
default (configurable 1–8) retain one reserved control-only turn at capacity.

Canonical path leases protect participating voice read/modify/write sequences;
disjoint native files overlap. Shared browser/native UI and opaque MCP interactions
serialize, including screenshots. Opaque shell/patch writes hold the workspace
conservatively. Cyclic waits fail clearly and release the affected worker. A live
tracked shell child retains its leases after the report until confirmed closed or
stopped. Detached/untracked external processes and unmodified typed/scheduled work
are outside these guards; there is no OS-wide file lock or rollback promise.

Desktop and terminal capture accept another utterance without awaiting its job.
One shared speech queue gives reports priority and coalesces obsolete progress.
Actual-start observations happen after resource access and permission; a requested
action cannot be narrated as already executing while waiting. Full panel and island
share bounded job rows, individual Stop and explicit Stop all. The approved pearl
and state motion remain. IPC contract is 10; app version remains unchanged.

Completed reports append passive atomic request/report pairs only when the owning
typed conversation is idle, without an extra model call or mixed tool protocols.
Ending audio keeps work; owner deletion/shutdown cancels owned workers. Terminal
permissions temporarily pause capture and accept serialized typed answers. Clearing
or loading a chat preserves older work in its saved original conversation.

Evidence so far:

- Task 2 worker/resource/host/permission set: **116/116** serial, no skips, including
  an actual temporary file write and a real tracked shell child confirmed stopped.
- Task 3 desktop set: **40/40** serial, no skips. Controlled same-session capture
  proves B speaks before blocked A finishes. Original typed model/history stay
  separate. Public snapshots strip private worker fields; invalid cancel IPC fails.
- Task 4 terminal/core/channel/automation set: **126/126**, no skips. Real CLI
  fixtures exercise overlap, live status and individual cancellation, approval and
  interruption cases, End voice during work and clear-chat result ownership.
- `verify-parallel-voice.mjs --env <local-env>` → `PARALLEL_VOICE_LIVE_OK`: **3 real
  Meta/file jobs**, independent completion before deliberately held A is released,
  an observed same-file wait and preserved poem, real Sarvam STT, **3 real TTS MP3
  handoffs**, **peak players 1**. Generated input has explicit fixture filenames
  added after transcription; no physical microphone/speaker was used.
- Native desktop rerun → `DESKTOP_VOICE_NATIVE_OK`: **240-character kavita.txt**,
  real Sarvam/Meta, **2 MP3 handoffs**, **13376 ms** including native checks, typed
  model unchanged, keyboard End and **0 page errors**. Browser fixture covers new
  individual/all job payloads as well as prior main/island motion/recovery checks.

Screenshot (1784) follow-up: saved records showed a completed web search and one
page read, followed by a failed second page read; that job had a 1300-character
report, so it was not an empty planner or proven worker collision. An older
separate job had a truly empty final reply. No raw source response was retained,
so the historical page-read failure cannot honestly be called an API collision
or assigned a specific HTTP cause. New read-only failures with useful findings
become partial results, keeping failed steps visible; failed writes/permissions
remain failed. Voice retries an empty successful model response once; after any
tool call that recovery is report-only, with tools disabled. Three controlled real
CLI HTTP cases passed, including two empty replies remaining failed and no
repeated write. The 1366×768 renderer reproduction measured a **−71.046875 px**
work-line/job-list gap before the fix; its after check now passes with separate
space, wrapped request titles, status badges and expandable per-job results.
The user's separate pending speed edits in the original checkout are untouched.

The first broad affected run reported **910 tests: 906 pass, 4 fail, 0 skip**.
All four were the new optional runtime-tool lookup assuming a context in existing
context-budget fixtures. Focused reproduction showed the TypeError; optional
lookup fixed it, with **11/11** relevant checks passing. The pre-review rerun
passed **918/918** with no skips.

Final affected serial run: `node scripts/verify-voice-suite.mjs` → **928 tests,
928 pass, 0 fail/cancelled/skipped**, **271581.7456 ms**, exit 0, `VOICE_SUITE_OK`.
Desktop typecheck/Vite build passed (403 modules). Browser check returned
`DESKTOP_VOICE_UI_OK`, **0 page errors**, including long parallel requests at
1366×768, keyboard-expanded partial results, six reachable active jobs and exact
permission ownership/resolution in both app and island. The post-review live
parallel check again returned `PARALLEL_VOICE_LIVE_OK`: three real Meta/file jobs,
real Sarvam STT and three TTS handoffs, same-file wait, preserved poem and one
captured player. It does not prove microphone/speaker duplex.

One fresh review found seven Important defects, each reproduced RED→GREEN in one
fix pass: enclosing-repository Git/generated-file lease gaps; competing typed/voice
permission prompts; another completion clearing a live permission; cancellation
leaving a stale island prompt; ignored owner Always grants; reports stranded behind
routine delivery; and older active jobs hidden by recent results. Ten regressions
cover them, and the focused fix set passed **89/89**, no skips. The complete affected
set above passed after all fixes. No re-review or new dependencies.

Execution decisions and costs, in decision order:

1. Fresh existing Agent per utterance, no classifier hop: lower overhead; requires
   bounded private controls and completed-history snapshots.
2. Coordinate participating voice jobs only: preserves typed/scheduled behavior;
   external writers remain outside these guards.
3. Four ordinary workers (configurable 1–8), one control-only slot at capacity:
   status/stop stays available; extra new work must wait for room.
4. Tracked live commands retain file/UI access after reporting: ongoing effects
   stay protected; long-lived shell-launched apps can hold later jobs up.
5. Disable automatic recall/nested delegation per worker, retain explicit recall,
   and serialize opaque connected interactions: avoids hidden worker state;
   conservative waiting and detached-process limits remain.
6. Append passive request/report pairs at owner idle, without another model call:
   typed tool protocols stay coherent; detailed steps live in the task audit.
7. One typed/voice permission prompt owner pauses capture: prevents mixed answers;
   permission responses require the keyboard.
8. Useful findings plus failed read-only sources are partial: results survive;
   source gaps remain visible and need follow-up.
9. Retry one empty successful response, report-only after observed tool calls:
   avoids repeated writes; rare extra request and unfinished-action limits remain.
10. Physical microphone/headset/speaker behavior stays an owner gate: generated
    input/captured output proves service flow; echo/barge-in still needs a real take.
11. Packaged behavior/general cloud timing remain limited: live configured services
    ran; package/GPU acceptance and variable timing prevent an instant guarantee.
12. Detached external processes and unchanged typed/scheduled collisions remain
    outside voice coordination: no OS-wide collision or rollback guarantee.
13. Pre-existing skipped-tool accounting at execution limits is unchanged: separate
    from this feature; existing execution-limit reporting semantics remain.

Deferred minor: collapsed island ordinary status text; expanded voice view shows
actual captions/jobs. No new minor findings from the final parallel review.

The previous full-suite Windows cleanup failure and physical/headset/package gates
in §18g remain visible. This is new 28 October hackathon work, built on the separately
identifiable inherited baseline. Same draft PR #70; no merge/release. Unrelated
pending edits and user-authored files in both checkouts are preserved.

## 18j. Empty intermediate voice decisions (28 October)

Owner reported that the second request could return no planner report. The saved
older empty record has zero actions and no raw HTTP response, so its precise
upstream cause is unavailable. The newest screenshot pair is a different captured
state: poem job `3b0e7124` has a 428-character report and retained command resources;
research job `bf5d9976` has completed search/page-read steps and is waiting on a
retrying file write. That does not disprove the separate empty-reply report. Do not
assign an HTTP cause to either without a response trace, or call the open-command
wait fixed by this change.

Reproduction found a concrete flaw in our previous recovery: if a valid blank
model response arrived between actions, `runVoiceWorker` restarted `Agent.send`
with tools disabled. A second request could save its draft, then report without
finishing the requested final save. Controlled real HTTP reproductions failed in
both JSON and SSE transports: the requested final file did not exist. The previous
retry also appended an empty assistant message to the next request.

The one-retry budget now belongs to the model decision loop, enabled only in fresh
voice workers. A blank successful decision is retried before it enters history or
executes anything, with existing receipts and tools intact. It never restarts the
Agent turn or resets action limits/counters. One retry total per request; a second
blank produces `provider_empty_response`. Authentication/quota/length errors and
ordinary typed requests keep their own policies. The two old fake-Agent tests
asserted the flawed report-only behavior; real HTTP/file regressions replace them.

Evidence:

- JSON/SSE intermediate blank reproductions: RED missing final file → GREEN both
  files saved exactly once, no empty assistant history, both concurrent reports.
- Two blanks: exactly two provider requests, no file action, explicit provider-empty
  failure. Ordinary typed blank: one request, unchanged policy.
- Focused stream/worker/terminal set: **50/50**, no skips, **42670.9331 ms**.
- `verify-voice-second-request.mjs --env <local-env>`: real concurrent Meta poem and
  AI-research jobs both returned reports and saved/read their separate files. All
  model requests returned HTTP 200 with real text or tool decisions; this sample
  did not reproduce an upstream Baseten blank.
- Same real-service script with `--inject-empty`: one controlled blank after the
  research save, followed by successful model continuation/read-back. Both files
  existed and both reports survived. One separate web source failed, so research
  correctly remained partial. The trace explicitly marks injection; it does not
  falsely attribute that blank to the cloud provider.
- Desktop typecheck/Vite build passed (403 modules). Full project `npm test`
  (`node --test --test-concurrency=1`) → **1703 tests: 1702 pass, 0 fail,
  0 cancelled, 1 skip**, **725895.3614 ms**, exit 0. The skipped case is
  POSIX executable-permission/mode changes on Windows, not a passing result. Literal review
  and `git diff --check` passed. No credentials, generated reports or trace logs
  are included in the commit.

Remaining limits: no physical audio or editor launch in this planner-isolation
check; intermittent upstream behavior is not guaranteed away. Existing long-lived
command/file-access waiting is a separate observed path, unchanged in this fix.
No action result or real HTTP error is relabelled successful. Original checkout
speed edits and user-authored documents are preserved. Update draft PR #70 only;
no merge, app version bump, tag or release.

## 19. Sources

- Local PDF `meta-hackathon-voice-plan.pdf` (participant guide claims, schedule, deadlines).
- Sarvam: `/api-reference/speech-to-text/transcribe`, `/api-reference/text-to-speech/convert`,
  `/api/api-guides-tutorials/text-to-speech/voices`, `/api-reference-docs/pricing`,
  `/api/getting-started/ratelimits`.
- Baseten: `/inference/model-apis`, `/inference/model-apis/audio`,
  `/inference/model-apis/reasoning`, `/inference/model-apis/pricing-and-limits`.
- Kilo gateway catalogue and a live keyless call (401).
- Repo: `src/channels/voice.mjs`, `src/core/cli.mjs`, `src/core/config.mjs`,
  `src/core/provider.mjs`, `src/automation/*`, `desktop/electron/island.mjs`,
  `docs/plans/desktop-background-jobs-plan.md`.
- Prior art: `ShashwatJain29/hermes-sarvam-voice` (Sarvam provider plugin),
  `DINAKAR-S/voice-agent-starter-kit` (LiveKit + Sarvam streaming).


## 18k. Context-aware report interruption (28–29 October)

New hackathon work: the shared single-player queue now parks an interrupted
report rather than automatically replaying it. Sentence clips retain completed
speech and prefetch only one sentence. The existing Meta worker receives bounded,
untrusted delivery context and a private `voice_reports` control; it interprets
intent without a trigger-phrase list or separate classifier. Older turn/session
controls cannot act on a newer interruption. A substantive tool start releases
other ready reports during long work; successful speech-only selections suppress
redundant confirmation, while mixed work and failed controls still speak a result.

Terminal and desktop/island pass the same per-utterance token. Blank transcription
restores only the unfinished sentence; real requests keep old speech suspended.
Manual mic pause and End remain separate from work cancellation. Original checkout
speed edits and four untracked user documents remain untouched.

Evidence so far:
- Host checks: **46/46**, no failures/skips, real CLI child process + local HTTP,
  desktop controlled recorder/player; genuine/false interruptions, mixed controls,
  late completion, tentative interruption plus manual pause, permission and End.
- `verify-voice-interruption.mjs`: **6/6 real Sarvam/Meta cases**, including Hinglish
  next, English resume/repeat/dismiss, new question and contextual “okay, then what?”.
  The ambiguous case chose resume; no claim that every use of that phrase should.
  Completed first sentence played once except explicit repeat; peak one player.
- Desktop build: **403 modules**, exit zero. Full suite, renderer/native checks
  and fresh final review recorded below when complete.

Rulings: sentence-boundary resume can replay the unfinished sentence because MP3
has no word timing. Existing VAD plus contextual planning avoids a new provider,
with no prosody/loudness-based intent claim. The speech hold releases when real
external work starts so long tasks cannot silence other finished reports; those
reports may speak while the external tool runs. Physical headset/Hinglish duplex
and packaged installer acceptance remain unverified.

29 October final-review pass: three Important findings were directly reproduced
and fixed without a second review dispatch. Resuming/repeating an originally
queued report keeps its original completion promise (including session close).
Cancellation is checked inside both awaited player boundaries before changing
selection. The planner now explicitly states `answerRequired` in its existing
speech-control call; pure status/discovery no longer forces duplicate confirmation,
and dismissal plus a direct conversational answer cannot silence that answer.
An omitted decision keeps the answer audible. Unrelated reports wait while that
answer is still owed; a deliberately selected report can still play. New real
Agent/HTTP regressions cover the read-only routing, mixed conversation, mixed file
work and cancellation cases. Focused queue/control/worker checks: **45/45**.

The final live repeats also exposed two external limits: one genuine Meta reply
was empty after the existing recovery attempt, and one generated Hinglish phrase
was recognized as a different request. Both failed checks were retained in the
execution record. A clearer code-switched fixture changes only verification data;
production does not match phrases. The 7-case final run and full-suite totals are
recorded below after completion. Physical microphone/speaker and packaged installer
acceptance remain separate from these generated/captured checks.


Decisions retained from the implementation/review ledger:
1. Resume at a sentence boundary, because the existing MP3 player has no word
   timing. Cost: the unfinished sentence can repeat; completed sentences cannot.
2. Reuse the current speech detector and contextual Meta planner, with no new
   provider/classifier. Cost: intent waits for transcription/planning, and real
   Hinglish headset acceptance remains necessary.
3. Release the speech hold when substantive external work starts, so long tasks
   do not silence unrelated ready reports. Cost: those reports may speak while a
   new task's external tool runs.
4. Run the full serial project suite as the final task command instead of repeating
   the overlapping voice-suite wrapper. It includes the wrapper's roots plus the
   remaining browser/tool fixtures. Cost: no separate wrapper invocation receipt.
5. The reviewer set exact-word resume and physical/package behavior aside; retain
   the approved sentence policy and explicit acceptance gaps. Cost: unfinished
   sentence replay or headset/installer problems require a real device take.
6. The reviewer set long-work report sharing and the initial cached receipt aside;
   preserve those approved behaviors. Cost: unrelated completions may speak during
   external work, and the initial short receipt remains.

No new Minor findings were deferred by the interruption review. The earlier
collapsed-island status polish item remains outside this follow-up.

Final fix-pass hardening: a later unavailable selection also keeps its explanation
audible after an earlier selection succeeded. Its direct regression was RED then
GREEN; the full focused queue/control/worker set is now **46/46**. This is part of
the same owed-answer fix, with no additional classifier or model request.

Latest cloud repetition after the final availability guard: first request was
transcribed correctly as Ab next report sunao please, but Meta chose resume and
the expected-next assertion failed. The earlier full7-case final-prompt sample
passed, including mixed direct answer before other reports. Preserve both facts:
queue/control/owed-answer behavior is covered by deterministic regressions, while
natural-language intent can still be selected incorrectly by the planner. Do not
claim universal phrase understanding or hide this behind a green earlier sample.


Final verification receipt (29 October):
- Final serial affected voice set: **127/127 pass**,0fail/skip/cancelled,
 43967.0981ms; shared queue/session/control/worker/task plus actual CLI child/HTTP
 and controlled desktop recorder/player tests.
- Full final-code run: **1736 tests,1734pass,1fail,1skip**,683103.7784ms.
 The sole failure was unchanged `test/tools/git-process.test.mjs`, “kill refuses a
 new owner on an approved port”, with “Cannot verify process PID15884” from the
 process-identity safety guard. A current isolated rerun initially had9/10 with
 the same identity error in another process test. An archived86ffe977 baseline
 passed10/10, and the final current isolated rerun passed10/10. These three process
 files are unchanged. Keep the full failed result visible; do not call the whole
 project suite green or change an unrelated safety guard for this voice task.
 The skipped case requires executable POSIX permission modes on Windows.
- Real-service sample: a complete **7/7** generated-Sarvam/Meta run passed before
 the availability-only guard. A later repetition on the final guard failed its
 first next-report assertion despite correct transcription (Meta selected resume).
 Previous repeats also exposed one empty provider response and one mishearing.
 These are sampled external reliability limits, not hidden behind the passing run.
- Native Electron real speech/file check and main/island renderer fixture passed;
 build403modules. Inputs generated/VAD simulated, outputs capturedMP3. Physical
 headset/echo and installed-package acceptance remain open.
- One fresh review; all three Important findings and the follow-up owed-answer
 case have RED→GREEN regressions. No new Minor findings deferred.

Final ruling: preserve the full-run failure and keep PR70 in draft, with the
127/127 affected set as the final task gate. The owner requested a reviewable draft;
repository rules say to report existing failures and avoid unrelated expansion.
Cost: no all-green project-suite claim; intermittent process fixture, model/speech
reliability and physical/package acceptance remain open. No merge or release.
The earlier interrupted helper left an obsolete child-run receipt; it was excluded.
Final receipts above are from the completed current-code run and fresh affected set.
No raw logs, generated media, keys or personal documents are committed.


## 18l. Owner acceptance and integration (29 October)

The owner reported the voice flow working and explicitly requested merging PR70,
with changelog and documentation updates. This supersedes the earlier draft-only
integration instruction. Both changelogs now describe the delivered voice,
heartbeat and phone-pairing scope; README no longer says desktop voice or parallel
requests are absent. The source guide records owner acceptance while preserving
sampled planner/recognition failures, unfinished-sentence replay and the unmeasured
physical-headset/three-workspace/installed-package checks.

This integration keeps package.json at 2.7.1 and does not request a new release.
The existing v2.7.1 release already contains latest.yml; the unchanged release
workflow therefore skips republishing that version after its normal checks.
Fresh pre-merge checks are recorded below; PR #70 is the remote merge receipt.


Fresh pre-merge verification (29 October):
- Full serial run: **1737 tests, 1735 pass, 1 fail, 1 skip**, 0 cancelled,
  786467.1384ms. The real Chrome prompt operation passed with one write; its
  unchanged file-level cleanup hook then failed with Windows EPERM removing the
  temporary browser profile. The same file rerun alone passed **1/1**,
  10117.8079ms, including real Chrome and cleanup. The file is identical to the
  default branch. This is an intermittent fixture cleanup failure; the complete
  project run is not reported as green. The skip requires POSIX permission modes.
- Desktop version checks: **7/7 pass**, 422.904ms. Desktop source build succeeded
  with **403 modules**. Relative documentation links: **71 resolved**.
- `git diff --check` passed. This final update changes only five documentation
  files; package version, application code and release workflow are unchanged.
- PR70 was mergeable with no required status checks or review gate reported.
  Owner approval authorizes integration with the explicitly recorded fixture and
  external speech/model limitations; no unrelated safety or browser code changed.
