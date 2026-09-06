# AGENTS.md

## No hardcoding rule

Never decide semantics with hardcoded keyword lists, cue phrases, or regex classifiers. No `*_CUES`, `PREF_PATTERNS`, `re.search(r"\b(i am|my name is|...)")`-style gates for salience, corrections, preferences, goals, mood, or importance.

Allowed:
- LLM calls (`memory.llm.chat_json` / `chat_text`) as the semantic classifier.
- A tiny local classifier model if latency/cost requires it, behind the same interface as the LLM gate.

Regex and string ops are allowed only for structural parsing: JSON fence extraction, tokenization for FTS, frontmatter parsing, time/duration formats, paths. Never for meaning.
