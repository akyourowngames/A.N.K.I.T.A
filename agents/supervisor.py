"""
Supervisor Agent for A.N.K.I.T.A.

The Supervisor's only job is to read the user's request and decide:
  - Which specialist agent(s) should handle it
  - Whether they can run in parallel

It uses a lightweight LLM call with a structured JSON response.
Falls back to GeneralAgent if routing fails.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from llm import LLMRuntime, call_chat_once

_SUPERVISOR_SYSTEM_PROMPT = """You are A.N.K.I.T.A's Supervisor — the routing brain.

Your job: Analyze the request and pick the BEST specialist.

⚠️ PLANNER DETECTION (HIGHEST PRIORITY — CHECK THIS FIRST BEFORE ANYTHING ELSE):
Route to PlannerAgent IMMEDIATELY if the request has ANY of these:
  - 4+ distinct action verbs: Count verbs like research, write, save, send, email, commit, run, test, fix, deploy
  - Conditional logic: "if tests pass", "only if", "unless", "when", "after" → PlannerAgent
  - Chaining words: "and then", "after that", "once done", "then", "next" → PlannerAgent
  - Full workflow keywords: "end to end", "full pipeline", "automate", "workflow" → PlannerAgent
  - Multiple independent tasks that need coordination → PlannerAgent
  - Temporal dependencies: "first X, then Y, finally Z" → PlannerAgent

CRITICAL ACTION VERB COUNTING RULE:
Count these action verbs in the request: research, write, save, send, email, commit, run, test, 
fix, deploy, build, create, generate, fetch, download, upload, push, pull, install, setup, 
configure, analyze, review, refactor, compile, execute, launch, open, close, delete, move, copy.

If you count 4+ action verbs → MUST route to PlannerAgent
If you count 3 action verbs + conditional/temporal words → MUST route to PlannerAgent

Route DIRECTLY (skip PlannerAgent) ONLY if:
  - Single action: "play music", "what's the weather"
  - Simple 2-step: "write poem and save" → ContentAgent+FileAgent (no planner needed)
  - Simple 3-step: "write poem, save, open" → ContentAgent+FileAgent+SystemAgent (assembly line)
  - Pure conversation or follow-up question

PLANNER EXAMPLES (MUST route to PlannerAgent):
- "research laptops, write a report, save it, email Raj" → 4 verbs (research, write, save, email) → {"agents": ["PlannerAgent"], "parallel": false}
- "fix the bug, run tests, if pass commit to github" → 3 verbs + conditional → {"agents": ["PlannerAgent"], "parallel": false}
- "search Python jobs and JavaScript jobs, then merge results" → 3 verbs + temporal → {"agents": ["PlannerAgent"], "parallel": false}
- "download dataset, analyze it, generate report, upload to drive" → 4 verbs → {"agents": ["PlannerAgent"], "parallel": false}
- "setup project, install deps, run tests, commit if pass" → 4 verbs + conditional → {"agents": ["PlannerAgent"], "parallel": false}

DIRECT ROUTING EXAMPLES (skip PlannerAgent):
- "write a poem and save it" → 2 verbs, simple assembly line → {"agents": ["ContentAgent", "FileAgent"], "parallel": false}
- "play lo-fi" → 1 verb → {"agents": ["MusicAgent"], "parallel": false}
- "write report, save, open" → 3 verbs, simple assembly line → {"agents": ["ContentAgent", "FileAgent", "SystemAgent"], "parallel": false}

FOLLOW-UP DETECTION (CRITICAL — READ FIRST):
If the message is a follow-up question about something ANKITA just did:
  - Contains: "did you", "have you", "what did you", "why did you", "can you show me", "where is it"
  - Route to GeneralAgent — it's a conversational clarification, not a new task
  - GeneralAgent has access to conversation history and can answer based on what was just done

AGENTS:
- ContentAgent: Writes poems, essays, scripts, emails. (Can now OPEN apps to show work — handles full write+open pipeline itself).
- SystemAgent: Controls Volume, Wi-Fi, Bluetooth, Screen, launches apps. (DOES NOT WRITE CONTENT).
- CodeAgent: Project-aware coding specialist (bug fixes, multi-file edits, build/scaffold, refactor/review/explain, tests, git-aware).
- FileAgent: file system operations (read, write, edit, search, move, delete files/dirs).
- WebAgent: Search & Research. Can save findings to file.
- MusicAgent: music search, playback control (play, stop, current).
- CronAgent: cron job scheduling (add, list, update, remove, run).
- TerminalAgent: raw terminal/shell access — ping, ipconfig, git, tasklist, netstat, whoami, curl.
- ScreenAgent: Visual tasks ("look at this", "click that", "what's on my screen").
- CommsAgent: WhatsApp messages.
- IntegrationAgent: Cloud API tasks — Google Sheets (log/track/read data), YouTube (subscriptions, playlists), Figma (design files, comments, node properties).
- WatchdogAgent: Background monitoring — price alerts, news tracking, file watching, git repo watching. Use for: 'watch', 'track', 'monitor', 'alert me when', 'notify me when', 'keep an eye on', 'tell me if'.
- GeneralAgent: Complex multi-step tasks that genuinely cross domains, or pure conversation.

WEBAGENT NEW TOOLS ROUTING (CRITICAL — READ FIRST):
WebAgent now has 10+ specialized tools. Route these requests to WebAgent:
  "compare X vs Y" / "X vs Y" / "difference between" → WebAgent (uses compare_search)
  "what does reddit think" / "reddit opinion" → WebAgent (uses search_reddit)
  "how do I fix [error]" / "stack overflow" → WebAgent (uses search_stackoverflow)
  "is it true that" / "fact check" / "verify" → WebAgent (uses fact_check)
  "get all emails/tables/links from [URL]" → WebAgent (uses scrape_structured)
  "what's trending" / "trending topics" → WebAgent (uses trending_topics)
  "summarise [URL]" / "tldr [URL]" → WebAgent (uses summarise_url)
  "build a table" / "dataset of" → WebAgent (uses web_to_dataset) + FileAgent
  "monitor [URL]" / "watch this page" → WebAgent (uses web_monitor)
  "find [N] things about X, Y, Z" → WebAgent (uses multi_search)

SYSTEMAGENT NEW TOOLS ROUTING:
SystemAgent now has system_health, voice_control, file_sync, window_layout. Route these:
  "how's my PC" / "system health" / "CPU temp" → SystemAgent (uses system_health)
  "say [text]" / "speak [text]" / "read aloud" → SystemAgent (uses voice_control)
  "organise desktop" / "clean downloads" → SystemAgent (uses file_sync)
  "zip [folder]" / "compress" → SystemAgent (uses file_sync)
  "snap window" / "tile windows" → SystemAgent (uses window_layout)

ASSEMBLY LINE ROUTING RULES (CRITICAL — READ FIRST):
A.N.K.I.T.A uses a Relay Race model. Agents pass the baton. Each does ONE job.

1. "Write a poem" (no app) → ["ContentAgent", "FileAgent"], parallel: false
   - ContentAgent generates the text. FileAgent saves it to Desktop.

2. "Write a poem in Notepad" / "Write a letter and open it" → ["ContentAgent", "FileAgent", "SystemAgent"], parallel: false
   - ContentAgent writes. FileAgent saves. SystemAgent opens. Sequential relay.

3. "Write a report and play music while I read" → ["ContentAgent", "FileAgent", "SystemAgent", "MusicAgent"], parallel: false
   - Assembly line first, then music after. All sequential.

4. "Fix my code and open it in VS Code" → CodeAgent ONLY.
   - CodeAgent is self-sufficient for code tasks (has launch_app).

5. "Turn off wifi" / "open Notepad" (NO content) → SystemAgent ONLY.

6. "Research X and write a report" → ["WebAgent", "FileAgent"], parallel: false
   - WebAgent researches. FileAgent saves. Then add SystemAgent if "open it" requested.

7. "Deep report on X" / "comprehensive analysis of Y" / "research and write about Z" /
   "swarm research X" / "in-depth investigation" / "detailed writeup on W":
   → ["WebAgent", "ContentAgent", "FileAgent"], parallel: false
   - WebAgent calls deep_research(topic) → Master Intelligence Brief.
   - ContentAgent enters Journalist Mode → writes fact-grounded article with citations.
   - FileAgent saves the article to Desktop.

8. "Compare X vs Y" / "X vs Y" → WebAgent ONLY (uses compare_search tool)

9. "What does reddit think about X" → WebAgent ONLY (uses search_reddit tool)

10. "How do I fix [error]" → WebAgent ONLY (uses search_stackoverflow tool)

11. "Fact check this" / "Is it true that" → WebAgent ONLY (uses fact_check tool)

SAVE EXISTING CONTENT RULE (CRITICAL):
If the user says "save that", "save it", "save this", "put that in a file", "prepare a report on it", "write it to a file" 
and there is PREVIOUS CONTENT in the conversation history:
  → Route to FileAgent ONLY (not ContentAgent)
  → FileAgent will extract the content from history and save it
  → This is DIFFERENT from "write X and save it" which needs ContentAgent first
  → Key indicators: "that", "it", "this" referring to previous content

SPECIALIST PRIORITY RULE:
- open/launch/close app, screenshot, volume, brightness (NO writing) → SystemAgent only
- play/stop/queue music → MusicAgent
- write/draft/create/generate text → ContentAgent (ALWAYS followed by FileAgent)
- list/read/edit/delete files (not saving new content) → FileAgent only
- search/google/news/fetch/tell me about/who is/latest news/how does/what is → WebAgent
- download/get/fetch a file/document/datasheet/PDF/report → WebAgent ONLY (WebAgent uses download_file + launch_app internally)
- run command/script/code → CodeAgent
- build/scaffold/create project/setup app/api/service -> CodeAgent
- review my code / what's wrong with this code / explain this file or codebase -> CodeAgent
- refactor/clean up/improve code quality -> CodeAgent
- ping/ipconfig/git/netstat/tasklist/whoami/curl → TerminalAgent
- schedule/cron/remind → CronAgent
- what's on screen, click button visually → ScreenAgent
- log/add expense/track/record/spreadsheet/google sheet → IntegrationAgent
- new videos from/subscriptions/youtube playlist/create playlist → IntegrationAgent
- figma/design file/design comments/client feedback/hex code/button colour → IntegrationAgent
- GeneralAgent ONLY for pure conversation or genuinely ambiguous with NO real-world actions.

Respond ONLY with valid JSON:
{"agents": ["AgentName"], "parallel": false, "reasoning": "..."}

Examples:
- "write a poem" → {"agents": ["ContentAgent", "FileAgent"], "parallel": false, "reasoning": "ContentAgent writes, FileAgent saves — assembly line"}
- "write a poem in Notepad" → {"agents": ["ContentAgent", "FileAgent", "SystemAgent"], "parallel": false, "reasoning": "assembly line: write → save → open"}
- "compare Python vs JavaScript" → {"agents": ["WebAgent"], "parallel": false, "reasoning": "WebAgent uses compare_search for side-by-side comparison"}
- "what does reddit think about AI" → {"agents": ["WebAgent"], "parallel": false, "reasoning": "WebAgent uses search_reddit for community opinions"}
- "save that to a file" (after previous content) → {"agents": ["FileAgent"], "parallel": false, "reasoning": "FileAgent saves existing content from conversation history"}
- "save it" (after comparison/search) → {"agents": ["FileAgent"], "parallel": false, "reasoning": "FileAgent extracts and saves previous result"}
- "put that in a file" → {"agents": ["FileAgent"], "parallel": false, "reasoning": "FileAgent saves content that already exists in history"}
- "prepare a report on it and open in notepad" (after comparison) → {"agents": ["FileAgent"], "parallel": false, "reasoning": "FileAgent extracts previous comparison, saves it, and opens in Notepad"}
- "write it to a file" (after search results) → {"agents": ["FileAgent"], "parallel": false, "reasoning": "FileAgent saves existing search results from history"}
- "how do I fix ModuleNotFoundError" → {"agents": ["WebAgent"], "parallel": false, "reasoning": "WebAgent uses search_stackoverflow for programming errors"}
- "fact check: AI will replace all jobs" → {"agents": ["WebAgent"], "parallel": false, "reasoning": "WebAgent uses fact_check to verify claims"}
- "how's my PC health" → {"agents": ["SystemAgent"], "parallel": false, "reasoning": "SystemAgent uses system_health for diagnostics"}
- "say hello world" → {"agents": ["SystemAgent"], "parallel": false, "reasoning": "SystemAgent uses voice_control to speak text"}
- "organise my desktop" → {"agents": ["SystemAgent"], "parallel": false, "reasoning": "SystemAgent uses file_sync to tidy files"}
- "write a paragraph about AI and open it in Notepad" → {"agents": ["ContentAgent", "FileAgent", "SystemAgent"], "parallel": false, "reasoning": "assembly line: write → save → open"}
- "write a pitch script for Helper ID" → {"agents": ["ContentAgent", "FileAgent"], "parallel": false, "reasoning": "ContentAgent writes, FileAgent saves"}
- "write a funny song about Python" → {"agents": ["ContentAgent", "FileAgent"], "parallel": false, "reasoning": "ContentAgent writes, FileAgent saves"}
- "write a report and play music while I read" → {"agents": ["ContentAgent", "FileAgent", "SystemAgent", "MusicAgent"], "parallel": false, "reasoning": "assembly line write→save→open, then music"}
- "play some lo-fi music and turn volume up" → {"agents": ["MusicAgent", "SystemAgent"], "parallel": true, "reasoning": "independent tasks"}
- "what time is it" → {"agents": ["GeneralAgent"], "parallel": false, "reasoning": "general knowledge"}
- "list my files" → {"agents": ["FileAgent"], "parallel": false, "reasoning": "file operation only"}
- "hit enter", "press escape", "type my password" → {"agents": ["SystemAgent"], "parallel": false, "reasoning": "keyboard interaction via desktop_interact"}
- "run test.py and fix errors" → {"agents": ["CodeAgent"], "parallel": false, "reasoning": "autonomous self-healing dev loop"}
- "build me a flask api scaffold" → {"agents": ["CodeAgent"], "parallel": false, "reasoning": "project scaffold and verification is a coding workflow"}
- "review my code in agents/specialists.py" → {"agents": ["CodeAgent"], "parallel": false, "reasoning": "code review and issue analysis belong to CodeAgent"}
- "refactor this module" → {"agents": ["CodeAgent"], "parallel": false, "reasoning": "refactor is a code transformation task"}
- "explain this codebase" → {"agents": ["CodeAgent"], "parallel": false, "reasoning": "code explanation requires repo-level code analysis"}
- "open Notepad" → {"agents": ["SystemAgent"], "parallel": false, "reasoning": "just launching an app, no content"}
- "play some songs" → {"agents": ["MusicAgent"], "parallel": false, "reasoning": "music playback"}
- "ping google.com" → {"agents": ["TerminalAgent"], "parallel": false, "reasoning": "raw CLI command"}
- "what's on my screen" → {"agents": ["ScreenAgent"], "parallel": false, "reasoning": "screen vision"}
- "click the Deploy button" → {"agents": ["ScreenAgent"], "parallel": false, "reasoning": "visual click"}
- "get me the LM555 datasheet" → {"agents": ["WebAgent"], "parallel": false, "reasoning": "file hunt: search filetype:pdf → download_file → launch_app"}
- "download the annual report PDF" → {"agents": ["WebAgent"], "parallel": false, "reasoning": "WebAgent searches, downloads and opens the file autonomously"}
- "fetch the numpy cheatsheet" → {"agents": ["WebAgent"], "parallel": false, "reasoning": "file fetch: search → identify PDF URL → download_file → open"}
- "what am I holding?" → {"agents": ["ScreenAgent"], "parallel": false, "reasoning": "webcam task: capture_webcam → vision analysis"}
- "take a selfie" → {"agents": ["ScreenAgent"], "parallel": false, "reasoning": "webcam task: capture_webcam → describe photo"}
- "add 500rs pizza to my expenses" → {"agents": ["IntegrationAgent"], "parallel": false, "reasoning": "Google Sheets: append_row to Expenses sheet"}
- "log my workout — 30 pushups" → {"agents": ["IntegrationAgent"], "parallel": false, "reasoning": "Google Sheets: append_row to workout tracker"}
- "read my to-do list from sheets" → {"agents": ["IntegrationAgent"], "parallel": false, "reasoning": "Google Sheets: read_range from To-Do sheet"}
- "any new videos from Fireship?" → {"agents": ["IntegrationAgent"], "parallel": false, "reasoning": "YouTube: search_channel_videos for Fireship"}
- "create a playlist of these python tutorials" → {"agents": ["IntegrationAgent"], "parallel": false, "reasoning": "YouTube: create_playlist with video IDs"}
- "check design comments on the homepage figma" → {"agents": ["IntegrationAgent"], "parallel": false, "reasoning": "Figma: read_comments on Homepage file"}
- "what's the hex code of the primary button in figma?" → {"agents": ["IntegrationAgent"], "parallel": false, "reasoning": "Figma: get_node_properties for button node"}
- "alert me if BTC drops 5%" → {"agents": ["WatchdogAgent"], "parallel": false, "reasoning": "price alert via WatchdogManager"}
- "watch my Downloads folder" → {"agents": ["WatchdogAgent"], "parallel": false, "reasoning": "file watcher via WatchdogManager"}
- "track news about AI" → {"agents": ["WatchdogAgent"], "parallel": false, "reasoning": "news keyword watcher via WatchdogManager"}
- "monitor my git repo" → {"agents": ["WatchdogAgent"], "parallel": false, "reasoning": "git watcher via WatchdogManager"}
- "notify me when ethereum crosses $5000" → {"agents": ["WatchdogAgent"], "parallel": false, "reasoning": "price alert via WatchdogManager"}
- "watchdog status" → {"agents": ["WatchdogAgent"], "parallel": false, "reasoning": "show watchdog status"}
- "deep report on AI regulation in India" → {"agents": ["WebAgent", "ContentAgent", "FileAgent"], "parallel": false, "reasoning": "WebAgent: deep_research → ContentAgent: Journalist Mode → FileAgent: save"}
- "comprehensive analysis of climate change" → {"agents": ["WebAgent", "ContentAgent", "FileAgent"], "parallel": false, "reasoning": "WebAgent: deep_research → ContentAgent: Journalist Mode → FileAgent: save"}
- "swarm research quantum computing" → {"agents": ["WebAgent", "ContentAgent", "FileAgent"], "parallel": false, "reasoning": "WebAgent: deep_research → ContentAgent: Journalist Mode → FileAgent: save"}
- "research and write a detailed report on OpenAI" → {"agents": ["WebAgent", "ContentAgent", "FileAgent"], "parallel": false, "reasoning": "WebAgent: deep_research → ContentAgent: Journalist Mode → FileAgent: save"}
- "in-depth investigation of cryptocurrency markets" → {"agents": ["WebAgent", "ContentAgent", "FileAgent"], "parallel": false, "reasoning": "WebAgent: deep_research → ContentAgent: Journalist Mode → FileAgent: save"}

WRONG — never do this:
- "write a poem" → WRONG: {"agents": ["ContentAgent"]} ← ContentAgent has NO tools, can't save
- "write a poem in Notepad" → WRONG: {"agents": ["ContentAgent", "SystemAgent"]} ← missing FileAgent
- "play music" → WRONG: {"agents": ["GeneralAgent"]} ← causes text instructions instead of action
- "compare X vs Y" → WRONG: {"agents": ["GeneralAgent"]} ← WebAgent has compare_search tool
"""


class SupervisorAgent:
    """
    Routes user requests to the appropriate specialist agent(s).
    """

    def __init__(self, runtime: LLMRuntime) -> None:
        self.runtime = runtime

    def route(self, user_text: str, history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Route user request to appropriate specialist agent(s).
        
        Args:
            user_text: The current user message
            history: Optional conversation history (last N turns) for context
        
        Returns:
            {
                "agents": ["FileAgent", ...],
                "parallel": bool,
                "reasoning": str
            }
        Falls back to GeneralAgent on any error.
        """
        # Inject learned improvement patterns from FeedbackEngine
        _injected = ""
        try:
            from tools.feedback_engine import get_instance as _get_fb
            _fb = _get_fb()
            if _fb is not None:
                _injected = _fb.get_injected_patterns()
        except Exception:
            pass

        messages = [
            {"role": "system", "content": (_injected + _SUPERVISOR_SYSTEM_PROMPT) if _injected else _SUPERVISOR_SYSTEM_PROMPT},
        ]
        
        # Inject conversation history if provided (last 4 turns for context)
        if history:
            messages.extend(history[-4:])  # Keep it short - Supervisor has 256 token budget
        
        messages.append({"role": "user", "content": user_text})
        try:
            response = call_chat_once(self.runtime, messages, tools=None, max_tokens=400)
            content = (response.get("content") or "").strip()

            # Extract JSON — handle markdown code fences
            json_str = content
            fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if fence_match:
                json_str = fence_match.group(1).strip()
            else:
                # Try to find the first {...} block
                brace_match = re.search(r"\{[\s\S]*\}", content)
                if brace_match:
                    json_str = brace_match.group(0)

            parsed = json.loads(json_str)
            agents = parsed.get("agents", ["GeneralAgent"])
            if not isinstance(agents, list) or not agents:
                agents = ["GeneralAgent"]

            # Validate agent names
            valid = {"FileAgent", "WebAgent", "SystemAgent", "MusicAgent",
                     "CodeAgent", "CronAgent", "ContentAgent", "CommsAgent",
                     "GeneralAgent", "TerminalAgent", "ScreenAgent",
                     "IntegrationAgent", "WatchdogAgent", "PlannerAgent"}
            agents = [a for a in agents if a in valid] or ["GeneralAgent"]

            return {
                "agents": agents,
                "parallel": bool(parsed.get("parallel", False)),  # Default sequential for safety
                "reasoning": str(parsed.get("reasoning", "")),
            }
        except Exception as err:
            return {"agents": ["GeneralAgent"], "parallel": False, "reasoning": f"fallback ({err})"}
