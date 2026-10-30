# Edit Ankita's personality

Open **Settings / Personality** after restarting the desktop dev session.
The default is self-assured, sassy, caring and respectful, inspired by the
owner's phrase "thik te karle na". The model writes each reply from the
conversation; there is no phrase-to-response table or extra personality call.

## Edit the card

- **Character:** describe the character and how she speaks.
- **Attitude:** gentle, balanced or bold.
- **Teasing:** off, light or playful. The default allows occasional teasing.
- **Speaking language:** follow the conversation, Hinglish or English.
- **Care and respect:** explain when to listen, soften or keep things serious.
- **Example exchanges:** up to four short examples of rhythm and tone.
- **Use this personality:** include or omit the card in new user-facing prompts.

Choose **Save personality** to apply changes. **Restore default** changes the
draft; save it to persist. Current typed/channel replies must finish before a
save. An already captured voice job keeps its original card; later requests get
the new one. Voice progress uses the currently saved card.

The same local card is loaded by desktop and terminal configuration. Restart a
running terminal session after editing it elsewhere. Individual teammate
instructions still provide their role and task guidance.

## Local file and limits

The card is `personality.json` in the detected config directory (`CONFIG_DIR`
when set). It is separate from credentials and personal memories. A first launch
uses built-in defaults without writing a file; explicit saving creates it.

The envelope is `{"version":1,"profile":{...}}`. Profile fields are `enabled`,
`description`, `attitude`, `teasing`, `language`, `care` and `examples`.
An example is `{"user":"a message","assistant":"a style example"}`.
Allowed strings for language are `match-user`, `hinglish`, and `english`.

Description and care fields allow 600 and 500 characters. At most four examples
are accepted, with 200 characters per message and 240 per reply. Invalid saves
leave the prior card intact. Malformed/unsupported disk cards fall back to the
default with a Settings notice and remain unchanged until explicitly saved.

## Scope and honest limits

The card shapes API-backed user-facing chat, voice workers and channel agents.
A linked ChatGPT Browser conversation keeps its own instructions; this change
does not inject native API system prompts into that separate conversation.
Scheduled/internal and delegated workers retain task-focused prompts.

Tool evidence, permissions and required output contracts take precedence. Under
context pressure, the runtime removes examples first, then omits optional style
if necessary to preserve callable tool schemas. It does not reduce the tool
catalog just to keep personality text.

Tone is probabilistic. The live planner sometimes writes longer raw drafts;
the existing voice report queue limits spoken playback to two sentences.
This is not a guarantee that every raw answer is two sentences or that clipping
always preserves every useful point. The live evaluator records both raw and
spoken text plus length diagnostics. Use actual conversations to refine the
card rather than treating four samples as a personality benchmark.

Run focused tests and `node scripts/verify-personality.mjs` for a four-case live
planner check. This uses temporary local files and the configured voice model;
it does not open a microphone or play speech. See the
[verification record](../verification/personality.md).
