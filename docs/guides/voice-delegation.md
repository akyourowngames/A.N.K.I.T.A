# Voice in and out (Sarvam)

Ankita can listen and answer out loud in Hindi, Hinglish or English. Speech-to-text
and text-to-speech run through **Sarvam AI**, which handles code-switched Hinglish far
better than an English-first recogniser.

Voice capture, pause detection, barge-in and playback already existed. What changed for
the hackathon is the engine behind them, plus a fix to the startup gate that used to
demand a Groq key even when voice ran elsewhere. The old engines are still installed:

| Layer | Default (unchanged) | This build | Back to old |
|---|---|---|---|
| Ears | Groq Whisper | Sarvam `saaras:v4` | `STT_PROVIDER=groq` |
| Voice | Edge TTS (keyless) | Sarvam `bulbul:v4-flash` | `TTS_PROVIDER=edge` |

## One-time setup

Two keys go in `.env`, never in chat and never in git:

```
SARVAM_API_KEY=...        # dashboard.sarvam.ai — ₹100 of free credit, never expires
STT_PROVIDER=sarvam
TTS_PROVIDER=sarvam
```

Check what the app actually resolved:

```bash
node chat.mjs --config
```

You want `STT_PROVIDER sarvam`, `TTS_PROVIDER sarvam`, and `SARVAM_API_KEY (set)`.
That screen prints only whether a key exists, never the value.

## Test 1 — no microphone (30 seconds)

### Faster voice-only replies

Keep your usual typed-chat settings and add these local settings:

```dotenv
VOICE_PROVIDER=baseten
VOICE_MODEL=meta-models/muse-spark-open-1026
BASETEN_API_KEY=...
VOICE_SILENCE_MS=800
```

The voice planner uses low reasoning effort. It reserves enough output tokens for
reasoning before the spoken answer. A short acknowledgement is prepared when voice
mode starts, then played from memory while the planner works. It means "I heard you",
not "the work is done". The answer still takes time to plan and speak.

The 800 ms pause is local to this demo setup; the shipped default stays 1200 ms.
If it cuts off a natural pause, increase it again. Missing Baseten credentials stop
voice mode with a message; they do not silently select a non-Meta planner.

If a key was exposed in chat, rotate it in the provider dashboard and replace it
locally. Never paste it into a conversation.

### Speech round trip

```bash
node scripts/verify-sarvam-voice.mjs
```

This speaks a Hinglish line, converts the audio to exactly the 16 kHz mono WAV the
microphone recorder writes, transcribes it back, then speaks a reply in the chosen
voice. It prints a table of timings, the transcript and the chosen reply language, and
exits non-zero if the words did not survive.

Use it after any change to the voice code, and once before filming.

## Test 2 — with your microphone (the real gate)

```bash
npm start
```

Then, inside the app:

1. `/voice` — starts hands-free listening.
2. Say: **"Ankita, VS Code kholo aur mera workspace set up karo."** Pause. The pause
   sends the turn; you do not press Enter.
3. The transcript prints as `yourname › Ankita, VS Code kholo...` **before** anything
   runs. Read it. If it is wrong, say `exit` and start over.
4. Ankita answers, and the reply is spoken.
5. Say `exit` to leave voice mode, or talk over the reply to interrupt it (barge-in).

Three clean runs in a row is the gate before any filming. A take that shows a misheard
word is never usable, however good the rest looks.

### Other voice commands

| Command | What it does |
|---|---|
| `/voice` | Hands-free loop: pause to send, barge-in, spoken replies |
| `/say <text>` | Speak one line aloud — the fastest way to judge the voice |
| `/speak on` / `/speak off` | Read every typed reply aloud |
| `--voice` | Start straight into the voice loop |

`/say` is the quickest sound check: it skips transcription entirely, so if it sounds
wrong the problem is the voice, not the ears.

## What "working" looks like

- Transcript appears within about a second, and the command words (VS Code, workspace,
  folder names) are right.
- The reply is spoken in a natural Indian voice, and Hindi replies use the Hindi voice.
- Nothing hangs: every failure prints a line and leaves you in the app.

Times measured on this machine, per call: speech out **0.8–1.5 s**, text back
**0.25–0.5 s**. A demo take costs about ₹0.40; 60 takes stay inside the free ₹100.

## When it goes wrong

| What you see | Meaning | Fix |
|---|---|---|
| `voice needs SARVAM_API_KEY ...` | No key for the selected engine | Add the key, run `/voice` again — no restart needed |
| `Sarvam STT 403: key rejected` | Key deleted, rotated or wrong | New key in `.env` |
| `Sarvam STT 429` | More than 60 requests a minute | Wait a moment; it retries once on its own |
| `no microphone found` | Windows cannot see a mic | Check Settings → Privacy → Microphone, or set `MIC_DEVICE` |
| Transcript is right but silent | Speaker or Bluetooth routing | Unplug the headset, or try `/say hello` |
| Wrong word, again and again | Recognition, not the code | Speak a bit slower; add the word to `SARVAM_KEYTERMS` |

## Known limits, stated plainly

- **The assistant's name is sometimes misheard.** "Ankita" came back as "Anpeta" once
  even though the name was in the keyword hints. Command words were correct every time.
  The transcript is shown first for exactly this reason.
- **The detected language label drifts** on Hinglish — the same clip was labelled Hindi,
  Hindi, then Punjabi. The words were always right. The spoken reply therefore follows
  the reply's own writing, not the label.
- **Audio leaves the machine** when you speak. Sarvam's retention terms are not
  documented on the pages consulted, so do not claim otherwise in public material.
- **Recording over 30 seconds** is outside the documented limit for the REST
  endpoint; the app sends one utterance at a time, so this only matters if the pause
  detection is disabled.
