# Project Agent Instructions

- Dont use regex.
- Dont hardcode things.
- Dont add keywords.
- We are building agi not chatbot.
- For tools, edit the manifest or prompt txt/json files first; do not change the chat loop for normal tool registration.
- Do not ship or claim done until tests cover the actual user-facing behavior, not only isolated helpers.
- For terminal/local-state behavior, test the live Jarvis CLI path before finalizing.
- Jaarvis should not claim local facts without tool evidence.
