# Editable personality implementation plan

> For agentic workers: use superpowers:executing-plans inline, as requested by the user.

**Goal:** Give Ankita an easily edited, caring and sassy personality, shared by chat and voice, and test four real model situations.

**Architecture:** A bounded structured card is stored separately from personal memories and credentials. A pure compiler adds style to existing generation prompts; no extra model call or hardcoded response router. A Settings editor updates future turns while active turns keep their snapshot.

**Tech Stack:** Existing Node, React, Vite and Sarvam/Baseten pipeline; no new dependency.

**Spec:** User requests attitude plus care, respect for feelings, natural teasing, self-assurance, and the example "thik te karle na". Editable fields are description, attitude, teasing, language, care guidance and example exchanges. Use a separate personality.json in the detected config directory; edits affect chat, voice and channel agents using shared config. Background/internal workers stay task-focused.

## Global constraints
- Tool permissions, action evidence and voice brevity take precedence over personality.
- No guessing emotions, fabricated memories, fixed catchphrase replies or extra personality-model requests.
- A broken personality file must leave Settings reachable and remain untouched until explicitly saved.
- Existing dark Settings tokens, fields and buttons; no added dependencies.
- Focused serial checks and a live four-prompt run; do not run the entire suite unless necessary.

## Review focus
- Invalid/oversized cards: reject saves; retain prior settings.
- Corrupt disk content: use defaults with an actionable notice, without rewriting.
- Personality off: omit all style and examples.
- Edits while working: future turns get edits, captured active voice work keeps its own copy.
- Browser provider: disclose any unsupported personality injection rather than pretending native API prompts control a separate ChatGPT conversation.

## Task 1: Card, store and prompt integration
Files: src/core/personality.mjs, personality.d.mts, personality-store.mjs; config.mjs, agent.mjs, voice-narrator.mjs and desktop/CLI narrator call sites.
Interfaces: normalizePersonality(input, base), personalityPrompt(profile, {compact}), PersonalityStore(file).load()/save(profile), store.view() returning {profile, notice}.
- [x] Write failing tests for validation, disk round trip/corruption, prompt omission and shared voice style.
- [x] Observe RED, implement pure card/compiler and private atomic storage, wire config/system/narrator.
- [x] Run focused checks and commit.

## Task 2: Settings editor and live updates
Files: desktop/electron/engine.mjs, main.mjs, shared personality actions/types, SettingsDialog.tsx and PersonalitySettings.tsx.
Interfaces: getPersonality/savePersonality IPC; save updates config and cached agents for future turns without changing current captured workers.
- [x] Test engine persistence/live config and browser UI edit/save/reset/errors/keyboard.
- [x] Observe RED, add one Personality Settings tab with existing theme/form styles and example editing.
- [x] Build desktop; run focused tests and native startup/editor round trip.

## Task 3: Live four-case evaluation and docs
Files: scripts/verify-personality.mjs, docs/guides/personality.md, docs/verification/personality.md, changelogs.
- [x] Run existing configured voice model on banter, distress, own mistake and a real temporary file task.
- [x] Record actual replies and honest qualitative findings; no exact-text model assertions.
- [x] Record evidence, source links, untested paths and literal/whitespace review.
- [x] Commit owned files, preserving personal untracked artifacts; no merge or release.

Execution evidence and acceptance limits: [verification](../../verification/personality.md).
The final change is committed together after the integrated checks; no merge or release.
