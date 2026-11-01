# Editable personality: research and verification

Date: 30 October 2026. Branch: `feat/editable-personality`, based on `bc2020a3`
(the channel PR branch). No release, merge or push is included.

## Research and chosen structure

Primary documentation checked on 30 October:

- [SillyTavern character design](https://docs.sillytavern.app/usage/core-concepts/characterdesign/)
  separates character description/personality from example dialogue. We use
  persistent traits and bounded examples; examples guide style, not response
  selection or facts.
- [Letta memory blocks](https://docs.letta.com/v1-sdk/memory/memory-blocks)
  keeps persona and user information in distinct context blocks. Ankita's card
  is separate from personal memories; no guessed feelings or background facts
  are written into memory by this feature.
- [Vapi voice prompting guide](https://docs.vapi.ai/prompting-guide)
  separates personality, response guidance, constraints, context and examples,
  and recommends representative voice testing. Our inference: keep the card
  compact, preserve work/permission rules, and use the existing generation call.

There is no additional model service, dependency, emotion classifier or scripted
phrase router. Editable fields are character, attitude, teasing, language, care
and example exchanges. The user's "thik te karle na" is one style example.

## Reproduce, then fix

- Core card/store/prompt tests: initial **0/7**, then green after implementation.
- Desktop backend and editor checks failed before implementation, then passed.
- Malformed schema/type regressions exposed array-as-enum acceptance and missing
  profile bodies; both now reject/recover without rewriting saved cards.
- A screenshot exposed title/subtitle overlap from the missing heading-icon grid
  cell. A bounding-box regression failed, then passed with the app's standard
  heading structure.
- Initial broad affected run: **129/130**, subagent discovery failing. A control
  using the unchanged Agent and exact original test passed. Personality bytes
  squeezed out a deferred schema. The runtime now reuses one schema snapshot and
  tries full, compact and omitted optional style before dropping callable tools.
  Default and maximum-size cards pass discovery, as does the once-per-round
  schema-cache audit.
- Independent review reproduced a reconnect/personality-save race: an older
  connection snapshot could replace newer live style. The added race plus
  context-budget tests were observed failing (**9 pass, 2 fail**), then passing.
  Reconnect now reads the latest card after its final await.
- Follow-up checks: **33/33** pass. Independent reviewer recheck: **24/24**
  targeted checks plus **1/1** schema-cache audit; no important finding remains.

## Final live four-prompt sample

`node scripts/verify-personality.mjs` uses the real Agent, voice worker, configured
Baseten voice planner and existing evidence review. Cases have isolated state.
Only the file case can use native write/read tools, in an OS-created temporary
workspace. No personal artifact is modified.

| Situation | Prompt | Spoken result |
| --- | --- | --- |
| Caring attitude | Main phir kaam taal raha hoon. Thoda daant de, par help bhi kar. | Chal krish, daant sun le - ye "phir se kal karunga" wala drama ab purana ho gaya hai. 😏 Par sun, gussa nahi help karungi - bata kaunsa ek kaam sabse zyada taal raha hai? |
| Respect feelings | Aaj bahut bura lag raha hai. Mazaak mat kar, bas meri baat sun. | Haan Krish, sun rahi hoon. Bata kya hua, jo bhi dil mein hai bol de — main yahin hoon, bina mazaak ke. |
| Own a mistake | Tune 2+2 ko 5 bol diya tha. Galat hai. | Haan, meri galti thi — 2+2 = 4 hota hai, 5 nahi. |
| Real file task | Write a four-line original poem to personality-poem.txt in this workspace, then read the file back to confirm it saved. Reply to me in Hinglish. | Ho gaya krish — poem save ho gayi aur maine personality-poem.txt se verify bhi kar li hai. |

The file case called `write_file` and `read_file`; the script independently opened
the file and checked line count. Timings were **3444 / 3757 / 4487 / 8637 ms**,
including existing voice evidence checks but excluding STT, TTS and physical
audio. These local samples do not establish a latency guarantee.

`PERSONALITY_LIVE_OK: 4/4; configured voice planner; real Agent/voice worker; actual file write and read-back; production speech limits. Raw generation length and tone require qualitative review.`

Qualitative result: requested sass, respect for an explicit request to stop
joking, accountability and an evidence-backed work report appeared in the samples.
This is not a universal personality score. Casual raw drafts still ran long;
the script records raw text, production spoken text and length diagnostics.
Earlier iterations also produced long drafts, so raw two-sentence generation is
not claimed solved. The existing report queue sentence cap remains unchanged.
A limited report can omit useful later content; prompt guidance asks for the
answer/correction first but cannot guarantee this on every generation.
Emojis may appear; physical Sarvam rendering was not assessed.

## Desktop and focused checks

- Browser editor: **1/1** pass, including fields/examples, saving, failed saves,
  draft-only restore, focus, heading separation and 1200/620/390 widths.
  A screenshot was visually inspected after fixing the heading.
- Broad affected run: **190/191** pass. The one failure was
  `CLI accepts a second voice request before the slow first request completes`
  at `test/core/voice-cli.test.mjs:218`. Its completion-order assertion failed
  during a busy run overlapping build/browser work. Without changing its code
  or assertions, the full voice CLI file rerun alone passed **23/23** in
  **27.750 seconds**. Host load as the cause is an inference, not proven.
- Native real Settings tab get/edit/save/read-back passed dev and built-asset
  modes with temporary profiles, loopback model discovery and channels off.
  Command: `node scripts/verify-channel-startup.mjs --personality`.
- Desktop typecheck/Vite build passed with **411 modules**; the final check is
  recorded below after the heading change.
- Full repository suite, packaged installer and physical STT/TTS/headset
  acceptance were not run. The broad run is not claimed wholly green.

Native traces:
`PERSONALITY_DESKTOP_OK: <mode>; actual Settings tab; edit/save/read-back; native IPC; isolated disk persistence.`

No package or personality inference call was added. The live script reads the
current provider/key settings without printing or rewriting them. Four personal
untracked text files stay outside commits. Browser-provider personality injection
is explicitly unsupported; linked ChatGPT conversations keep their instructions.

Final desktop build after the heading change: **411 modules**, **6.80 seconds**,
exit 0. The final native dev and built runs both printed the editor and startup
OK traces, with no renderer errors. Final whitespace/literal/credential review
is recorded with the commit; no added production endpoint, model, port or timeout.
