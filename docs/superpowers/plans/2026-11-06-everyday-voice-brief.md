# Voice implementation brief

Part of the approved everyday-assistant goal. Read the design's Natural voice
section in ../specs/2026-11-06-everyday-assistant-design.md. Implement useful
controls in the existing active voice experience, not a detached new demo.

## Owned files

desktop/shared/voice.mjs and .d.mts; desktop/electron/voice.mjs and voice-actions.mjs;
desktop/renderer/src/components/voice/*; relevant focused voice tests and a new
verification script if needed. Do not edit engine.mjs, main.mjs, wire.ts, App.tsx,
src/core/agent.mjs, src/core/tool-host.mjs or src/core/voice-worker.mjs: coordinator
owns integration there. New shared action identifiers must stay in voice.mjs;
main already dispatches Object.values(VOICE_ACTIONS) through runVoiceAction.

## Required behavior

- Narrow deterministic spoken status, continue/repeat/skip report, stop speaking,
  pause listening controls run before planner delegation. Preserve ordinary mixed
  requests and genuine work; do not turn "pause Spotify" into mic pause.
- Status uses actual current jobs/results, with zero planner calls. Report controls
  use the existing speech queue and reject stale targets. Ending speech does not
  cancel jobs. A paused mic cannot hear resume: provide clear working UI controls.
- Expose Stop speaking and report Continue/Repeat/Skip where relevant in the real
  main/island voice panel; show actual barge-in availability and speaker fallback.
- Keep echo safety and session/turn identity, pending approvals and cancellation.
- Test first, execute focused regressions and a renderer/service-boundary round
  trip, update a concise report with exact outputs and remaining limitations.
- Do not install dependencies, read/print credentials, launch live account actions
  or claim physical microphone verification. Use existing injected boundaries.

## Report

Write docs/findings/everyday-voice-controls.md with changed paths, tests/traces,
known limitations and any coordinator integration instructions. No commits or
subagents. The broader streaming voice work remains in the coordinator's plan;
this brief is a useful independent portion of that feature, not the whole goal.
