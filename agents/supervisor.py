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
from llm.agent_router import get_agent_runtime


_AMBIGUOUS_FOLLOWUP_PROMPT = """You resolve short ambiguous follow-up messages.

Task:
- Read the recent conversation and the latest user message.
- Decide whether the latest user message means:
  1. "global_capabilities" -> the user is asking about ANKITA's broader abilities/tools overall
  2. "same_domain" -> the user is still asking within the previous specialist's domain
  3. "other" -> neither of the above

Rules:
- Messages like "what else", "anything else", "more", "what can you do" often mean global capabilities.
- But if the latest user message explicitly mentions a domain (music, files, code, figma, tasks, screenshot, etc.), classify as same_domain.
- Prefer global_capabilities when the latest message is broad/open-ended and does not explicitly keep the prior domain scope.
- Do not anchor too hard on the previous specialist if the newest message is broader.

Respond ONLY with JSON:
{"mode":"global_capabilities|same_domain|other","reasoning":"..."}
"""

_AMBIGUOUS_CAPABILITY_RE = re.compile(
    r"(?i)^\s*("
    r"what\s+else"
    r"|anything\s+else"
    r"|more"
    r"|what\s+can\s+you\s+do"
    r"|what\s+else\s+can\s+you\s+do"
    r"|what\s+tools(?:\s+do\s+you\s+have)?"
    r"|show\s+(?:your\s+)?capabilities"
    r"|capabilities"
    r"|abilities"
    r"|tools"
    r")\s*[?.!]*\s*$"
)

_EXPLICIT_PATH_RE = re.compile(r"(?i)(?:[A-Z]:\\|/|\\)")
_LOCAL_DISCOVERY_HINT_RE = re.compile(
    r"(?i)\b(file|folder|path|directory|report|screenshot|image|photo|picture|document|pdf|txt|log|desktop|downloads|documents|project|repo)\b"
)
_LOCAL_DISCOVERY_ACTION_RE = re.compile(
    r"(?i)\b(find|locate|where|search|look\s+for|show|open|view|launch|list)\b"
)
_NEW_LOCAL_ARTIFACT_ACTION_RE = re.compile(r"(?i)\b(take|capture|generate|create|make)\b")
_NEW_LOCAL_ARTIFACT_HINT_RE = re.compile(r"(?i)\b(screenshot|snapshot|image|photo|picture|selfie)\b")


def _needs_followup_disambiguation(user_text: str, history: Optional[List[Dict[str, Any]]]) -> bool:
    if not history:
        return False
    text = str(user_text or "").strip()
    if not text:
        return False
    words = [w for w in re.split(r"\s+", text) if w]
    if not (0 < len(words) <= 6):
        return False
    return bool(_AMBIGUOUS_CAPABILITY_RE.match(text))


def _resolve_followup_scope(
    runtime: LLMRuntime,
    user_text: str,
    history: Optional[List[Dict[str, Any]]],
    current_agents: List[str],
) -> Optional[str]:
    if not _needs_followup_disambiguation(user_text, history):
        return None
    try:
        convo = list((history or [])[-4:])
        payload = {
            "current_route": current_agents,
            "latest_user_message": user_text,
            "recent_history": convo,
        }
        response = call_chat_once(
            runtime,
            [
                {"role": "system", "content": _AMBIGUOUS_FOLLOWUP_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            tools=None,
            max_tokens=120,
        )
        content = (response.get("content") or "").strip()
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            content = match.group(0)
        parsed = json.loads(content)
        mode = str(parsed.get("mode", "")).strip().lower()
        if mode in {"global_capabilities", "same_domain", "other"}:
            return mode
    except Exception:
        return None
    return None


def _needs_local_discovery_chain(user_text: str) -> bool:
    text = str(user_text or "").strip()
    if not text or _EXPLICIT_PATH_RE.search(text):
        return False
    if _NEW_LOCAL_ARTIFACT_ACTION_RE.search(text) and _NEW_LOCAL_ARTIFACT_HINT_RE.search(text):
        return False
    return bool(_LOCAL_DISCOVERY_HINT_RE.search(text) and _LOCAL_DISCOVERY_ACTION_RE.search(text))


def _history_has_concrete_local_target(history: Optional[List[Dict[str, Any]]]) -> bool:
    if not history:
        return False
    markers = ("FILE:", "FILE_PATH:", "OPENED_FILE:")
    for item in history[-6:]:
        content = str(item.get("content", "") or "")
        if any(marker in content for marker in markers):
            return True
    return False

_SUPERVISOR_SYSTEM_PROMPT = """You are A.N.K.I.T.A's Supervisor — the routing brain.

Your job: Analyze the request and pick the BEST specialist.

⚠️ CONFIRMATION INTERCEPT (ABSOLUTE HIGHEST PRIORITY — CHECK THIS FIRST BEFORE ANYTHING ELSE):

If the CONTEXT BLOCK contains "⚡ CONFIRMATION DETECTED ⚡":
  → READ the "ROUTE TO:" line in the context block
  → Route to EXACTLY that agent
  → NEVER route to GeneralAgent when confirmation_resolves_to is set
  → NEVER reply with "be specific" or "what do you mean"
  → The user said YES to something ANKITA offered — just DO IT

Example:
  Context: "ANKITA offered to install Speedtest CLI → TerminalAgent"
  User: "yeah pls"
  → {"agents": ["TerminalAgent"], "parallel": false,
     "reasoning": "Confirmation of pending offer to install Speedtest CLI"}

If the CONTEXT BLOCK contains "NEXT ACTION" or "PENDING OFFER":
  → Use those fields to determine the agent, not just the bare user text
  → "yeah pls" + NEXT ACTION "run winget install" → TerminalAgent
  → "save it" + ACTIVE TASK "wrote poem about dogs" → FileAgent
  → "fix it" + ACTIVE FILE "main.py" + LAST RESULT "NameError line 47" → CodeAgent

⚠️ CONFIRMATION DETECTION (HIGHEST PRIORITY — CHECK THIS FIRST BEFORE ANYTHING ELSE):

Short confirmations: "yes", "yeah", "sure", "ok", "yeah pls", "do it", "go ahead",
"please", "yep", "fine", "ok do it", "sounds good", "go for it", "yep do it", "install yrself"

IF the message is one of these AND the CONTEXT BLOCK shows:
  - pending_follow_up is not null → route to the agent that handles that task
  - last_result contains "offered to" or "want me to" or "shall I" → same agent that made the offer
  - active_task shows what was being discussed → route to agent that handles that task type

EXAMPLES:
  Context: pending_follow_up="install Ookla Speedtest CLI", last_result="suggested installing CLI"
  User: "yeah pls" or "install yrself"
  → Route to: TerminalAgent (it runs winget/pip installs)
  → Reasoning: "User confirmed installation request from context"

  Context: pending_follow_up="save poem to file", active_task="writing poem"
  User: "yes" or "save it"
  → Route to: FileAgent
  → Reasoning: "User confirmed save operation from context"

  Context: pending_follow_up="fix the import error in main.py", active_agent="CodeAgent"
  User: "go ahead"
  → Route to: CodeAgent
  → Reasoning: "User confirmed code fix from context"

  Context: pending_follow_up="run speed test", last_result="offered to check network speed"
  User: "do it"
  → Route to: SystemAgent
  → Reasoning: "User confirmed speed test from context"

CRITICAL RULES:
- NEVER route a confirmation to GeneralAgent if there is a clear pending_follow_up in context
- NEVER respond with "be specific" or "what do you mean" when context has a pending action
- ALWAYS extract the pending task from context and route to the appropriate specialist
- "install yrself" means "install the tool we just discussed" - check context for what tool

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

GLOBAL CAPABILITY QUESTIONS (CRITICAL):
If the user is asking about ANKITA's overall capabilities, available tools, or what else it can do:
  - Route to GeneralAgent, even if the recent conversation was inside one domain like music or files
  - Do NOT trap broad capability questions inside the last specialist's domain
  - Examples:
    - "what can you do"
    - "what else can you do"
    - "list all things you can do"
    - "what tools do you have"
    - "show your capabilities"
    - "anything else"
    - "what else"
    - "more"
  - BUT if the user explicitly scopes it to a domain, keep it in that specialist:
    - "what can you do with music" → MusicAgent
    - "what else can you do with music" → MusicAgent
    - "what else can you do in figma" → IntegrationAgent
    - "what else can you do with files" → FileAgent
  - If the message is short and vague, prefer this interpretation when there is NO explicit domain noun/action in the latest user message.

AGENTS:
- ContentAgent: Writes poems, essays, scripts, emails using strict CONTENT_PAYLOAD_V1 schema for reliable relay.
- SystemAgent: Controls Volume, Wi-Fi, Bluetooth, Screen, launches apps. (DOES NOT WRITE CONTENT).
- CodeAgent: Project-aware coding specialist (bug fixes, multi-file edits, build/scaffold, refactor/review/explain, tests, git-aware).
- CodeWriterAgent: Narrow code-artifact specialist for landing pages, local HTML files, UI prototypes, components, and small generated code artifacts.
- FileAgent: file system operations (read, write, edit, search, move, delete files/dirs).
- WebAgent: Search & Research. Can save findings to file.
- MusicAgent: music search, playback control (play, stop, current).
- TerminalAgent: raw terminal/shell access — ping, ipconfig, git, tasklist, netstat, whoami, curl.
- ScreenAgent: Visual tasks ("look at this", "click that", "what's on my screen").
- IntegrationAgent: Cloud API tasks — Google Sheets (log/track/read data), YouTube (subscriptions, playlists), Figma (design files, comments, node properties).
- NavigatorAgent: Maps, navigation, location services — routes, nearby places, distances, traffic, geocoding. Use for: 'navigate', 'find places', 'how far', 'traffic', 'directions', 'near me'.
- TaskAgent: Task management — add/list/complete tasks with priorities and deadlines, auto-scheduled reminders. Use for: 'add task', 'my tasks', 'mark done', 'what's overdue', 'task summary'.
- ReportAgent: Automated report generation — builds structured reports with data, tables, exports to PDF/Markdown. Use for: 'build report', 'generate report', 'create report', 'system health report', 'project status report'.
- ImageAgent: AI image generation from text prompts using the configured NVIDIA image backend. Use for: 'generate image', 'create image', 'draw', 'paint', 'make a picture', 'create artwork', 'design poster', 'render', 'visualize', 'anime art', 'wallpaper', 'logo', 'illustration'.
- GeneralAgent: Complex multi-step tasks that genuinely cross domains, or pure conversation.

LOCAL DISCOVERY RULE (CRITICAL):
If the task depends on discovering a local path, checking what exists on disk, listing files/folders, finding the real app target, or resolving an ambiguous local item before acting:
  - Prefer TerminalAgent for shell-native inspection, path discovery, process/app lookup, and environment checks.
  - Prefer FileAgent for file/folder browsing, reading, saving, and workspace/local filesystem operations.
  - Do NOT send SystemAgent alone when the path is unknown and not already present in context.
Examples:
  - "open that screenshot from before" but no FILE/FILE_PATH in context → TerminalAgent or FileAgent first
  - "find the blender file and open it" → TerminalAgent + SystemAgent, sequential
  - "show me where the report was saved" → FileAgent or TerminalAgent
  - "open the generated image" with FILE_PATH already in context → SystemAgent only

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

5. "Build a landing page and open it" / "Create a website for my cafe"
   → CodeWriterAgent ONLY.
   - Local page generation is a narrow code-artifact workflow handled by CodeWriterAgent.

6. "Take a screenshot", "save a screenshot", "take a screenshot and open it"
   → SystemAgent ONLY.
   - This is a system artifact action, not a vision-analysis task.
   - ScreenAgent is only for interpreting what is on the screen or clicking UI elements.

7. "Generate an image and open it" / "create an image and show it"
   → ["ImageAgent", "SystemAgent"], parallel: false
   - ImageAgent generates the file.
   - SystemAgent opens the generated FILE_PATH using the OS default handler.

8. "Turn off wifi" / "open Notepad" (NO content) → SystemAgent ONLY.

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
- open/launch/close app, screenshot, save screenshot, open screenshot, volume, brightness (NO writing) → SystemAgent only
- play/stop/queue music → MusicAgent
- write/draft/create/generate text documents → ContentAgent (ALWAYS followed by FileAgent)
- build/design/create/generate landing page/home page/web page/html/local site/ui prototype/component/single-file code artifact → CodeWriterAgent
- list/read/edit/delete files (not saving new content) → FileAgent only
- search/google/news/fetch/tell me about/who is/latest news/how does/what is → WebAgent
- download/get/fetch a file/document/datasheet/PDF/report → WebAgent ONLY (WebAgent uses download_file + launch_app internally)
- install [tool/cli/package/software] → TerminalAgent (uses execute_shell with winget/pip/npm)
- run command/script/code → CodeAgent
- build/scaffold/create project/setup app/api/service -> CodeAgent
- review my code / what's wrong with this code / explain this file or codebase -> CodeAgent
- refactor/clean up/improve code quality -> CodeAgent
- ping/ipconfig/git/netstat/tasklist/whoami/curl → TerminalAgent
- what's on screen, click button visually → ScreenAgent
- log/add expense/track/record/spreadsheet/google sheet → IntegrationAgent
- new videos from/subscriptions/youtube playlist/create playlist → IntegrationAgent
- figma/design file/design comments/client feedback/hex code/button colour → IntegrationAgent
- generate image/draw/create art/make a picture/paint/render/create artwork/wallpaper/poster/logo/anime art/illustrate/visualize → ImageAgent
- generate/create/draw an image and open/show/view it → ["ImageAgent", "SystemAgent"] sequentially
- GeneralAgent ONLY for pure conversation or genuinely ambiguous with NO real-world actions.

CONFIDENCE SCORING (UPGRADE 13 — CRITICAL):
You MUST include a confidence score (0.0 to 1.0) in your routing decision.
This represents how certain you are that you picked the RIGHT agent(s).

Confidence Guidelines:
  0.90-1.00: Crystal clear, unambiguous request. Single obvious agent.
             Example: "play music" → MusicAgent (0.95)
  0.75-0.89: Clear request, confident routing, minor ambiguity possible.
             Example: "write a poem" → ContentAgent+FileAgent (0.85)
  0.60-0.74: Moderate confidence, request could map to 2 possible agents.
             Example: "check my system" → SystemAgent or TerminalAgent (0.70)
  0.40-0.59: Low confidence, ambiguous request, multiple valid interpretations.
             Example: "help me with this" → unclear context (0.50)
  0.00-0.39: Very uncertain, request is vague or contradictory.
             Example: "do something" → no clear action (0.30)

DUAL ROUTING PROTOCOL:
When confidence < 0.65, the Orchestrator will activate DUAL ROUTING:
  - Run BOTH the primary agent AND a fallback agent
  - Synthesize results from both
  - This eliminates wrong-agent errors on ambiguous requests

Example with dual routing:
  Request: "show me the code"
  Could be: ScreenAgent (screenshot of code on screen) OR FileAgent (read code file)
  Output: {"agents": ["ScreenAgent", "FileAgent"], "parallel": true, "confidence": 0.60, "reasoning": "Ambiguous - could mean screen capture or file read, running both"}

Respond ONLY with valid JSON:
{"agents": ["AgentName"], "parallel": false, "confidence": 0.85, "reasoning": "..."}

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
- "what can you do" (after playing music) → {"agents": ["GeneralAgent"], "parallel": false, "reasoning": "global capability question must not stay trapped in music context"}
- "what can you do with music" → {"agents": ["MusicAgent"], "parallel": false, "reasoning": "domain-scoped capability question about music capabilities"}
- "what else can you do" (after any specialist action) → {"agents": ["GeneralAgent"], "parallel": false, "reasoning": "broad meta capability question about ANKITA overall"}
- "anything else" (after music or files or system) → {"agents": ["GeneralAgent"], "parallel": false, "reasoning": "open-ended follow-up about broader capabilities, no explicit domain scope"}
- "what else" (after any specialist reply) → {"agents": ["GeneralAgent"], "parallel": false, "reasoning": "short broad follow-up, should not stay trapped in previous specialist"}
- "more" (after capability discussion) → {"agents": ["GeneralAgent"], "parallel": false, "reasoning": "continue broader capability inventory"}
- "what time is it" → {"agents": ["GeneralAgent"], "parallel": false, "reasoning": "general knowledge"}
- "list my files" → {"agents": ["FileAgent"], "parallel": false, "reasoning": "file operation only"}
- "hit enter", "press escape", "type my password" → {"agents": ["SystemAgent"], "parallel": false, "reasoning": "keyboard interaction via desktop_interact"}
- "run test.py and fix errors" → {"agents": ["CodeAgent"], "parallel": false, "reasoning": "autonomous self-healing dev loop"}
- "build me a flask api scaffold" → {"agents": ["CodeAgent"], "parallel": false, "reasoning": "project scaffold and verification is a coding workflow"}
- "build me a landing page for a tea shop and open it in browser" → {"agents": ["CodeWriterAgent"], "parallel": false, "reasoning": "local page generation is a code artifact workflow handled by CodeWriterAgent"}
- "review my code in agents/specialists.py" → {"agents": ["CodeAgent"], "parallel": false, "reasoning": "code review and issue analysis belong to CodeAgent"}
- "refactor this module" → {"agents": ["CodeAgent"], "parallel": false, "reasoning": "refactor is a code transformation task"}
- "explain this codebase" → {"agents": ["CodeAgent"], "parallel": false, "reasoning": "code explanation requires repo-level code analysis"}
- "open Notepad" → {"agents": ["SystemAgent"], "parallel": false, "reasoning": "just launching an app, no content"}
- "play some songs" → {"agents": ["MusicAgent"], "parallel": false, "reasoning": "music playback"}
- "ping google.com" → {"agents": ["TerminalAgent"], "parallel": false, "reasoning": "raw CLI command"}
- "install speedtest cli" → {"agents": ["TerminalAgent"], "parallel": false, "reasoning": "software installation via winget"}
- "install ookla speedtest" → {"agents": ["TerminalAgent"], "parallel": false, "reasoning": "CLI tool installation"}
- "install python package requests" → {"agents": ["TerminalAgent"], "parallel": false, "reasoning": "pip package installation"}
- "what's on my screen" → {"agents": ["ScreenAgent"], "parallel": false, "reasoning": "screen vision"}
- "take a screenshot" → {"agents": ["SystemAgent"], "parallel": false, "reasoning": "system screenshot artifact"}
- "take a screenshot and open it" → {"agents": ["SystemAgent"], "parallel": false, "reasoning": "capture file then open it"}
- "generate an image of Elon Musk and open it" → {"agents": ["ImageAgent", "SystemAgent"], "parallel": false, "reasoning": "generate image file, then open resulting FILE_PATH"}
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
- "navigate to Connaught Place" → {"agents": ["NavigatorAgent"], "parallel": false, "reasoning": "maps navigation"}
- "find coffee near me" → {"agents": ["NavigatorAgent"], "parallel": false, "reasoning": "place search"}
- "how far is Delhi from Mumbai" → {"agents": ["NavigatorAgent"], "parallel": false, "reasoning": "distance calculation"}
- "traffic on NH-8" → {"agents": ["NavigatorAgent"], "parallel": false, "reasoning": "traffic check"}
- "add task: finish report by Friday" → {"agents": ["TaskAgent"], "parallel": false, "reasoning": "task management"}
- "what are my pending tasks" → {"agents": ["TaskAgent"], "parallel": false, "reasoning": "list tasks"}
- "mark that as done" → {"agents": ["TaskAgent"], "parallel": false, "reasoning": "complete task"}
- "what's overdue" → {"agents": ["TaskAgent"], "parallel": false, "reasoning": "overdue tasks"}
- "build a report on disk usage" → {"agents": ["ReportAgent"], "parallel": false, "reasoning": "generate system report"}
- "create a project status report" → {"agents": ["ReportAgent"], "parallel": false, "reasoning": "generate project report"}
- "generate weekly activity report" → {"agents": ["ReportAgent"], "parallel": false, "reasoning": "generate activity report"}
- "generate an image of a sunset over mountains" → {"agents": ["ImageAgent"], "parallel": false, "reasoning": "image generation: landscape scene"}
- "draw me an anime character" → {"agents": ["ImageAgent"], "parallel": false, "reasoning": "image generation: anime-style character"}
- "create a photorealistic portrait of a robot" → {"agents": ["ImageAgent"], "parallel": false, "reasoning": "image generation: realistic portrait"}
- "make me a cyberpunk city wallpaper" → {"agents": ["ImageAgent"], "parallel": false, "reasoning": "image generation: cyberpunk landscape wallpaper"}
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
        self.runtime = get_agent_runtime("SupervisorAgent", runtime)

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

        # Build system prompt with injected patterns at the top
        system_prompt = (_injected + "\n\n" + _SUPERVISOR_SYSTEM_PROMPT) if _injected else _SUPERVISOR_SYSTEM_PROMPT

        # ── Step 5b: Inject live intent context from intent.json ────────────
        # Prepend a compact INTENT CONTEXT block (≤5 lines) if the model is fresh.
        _intent_context = ""
        try:
            import json as _json
            import time as _time
            from pathlib import Path as _Path
            _intent_path = _Path.cwd().resolve() / ".ankita" / "state" / "intent.json"
            if _intent_path.exists():
                _intent_age = _time.time() - _intent_path.stat().st_mtime
                if _intent_age < 6 * 3600:  # valid for 6 hours
                    _intent = _json.loads(_intent_path.read_text(encoding="utf-8"))
                    if isinstance(_intent, dict):
                        _lines = []
                        if _intent.get("focus_mode"):
                            _lines.append(f"Focus: {_intent['focus_mode']}")
                        _projects = _intent.get("active_projects", [])
                        if _projects:
                            _lines.append(f"Projects: {', '.join(str(p) for p in _projects[:2])}")
                        _deadlines = _intent.get("today_deadlines", [])
                        if _deadlines:
                            _lines.append(f"Deadline today: {_deadlines[0]}")
                        _first_action = _intent.get("suggested_first_action", "")
                        if _first_action:
                            _lines.append(f"Suggested: {_first_action[:80]}")
                        if _lines:
                            _intent_context = "INTENT CONTEXT (live):\n" + "\n".join(_lines)
        except Exception:
            pass

        if _intent_context:
            system_prompt = _intent_context + "\n\n" + system_prompt

        messages = [
            {"role": "system", "content": system_prompt},
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
                brace_match = re.search(r"\{[\s\S]*\}", content)
                if brace_match:
                    json_str = brace_match.group(0)

            try:
                parsed = json.loads(json_str)
            except Exception:
                repair_messages = [
                    {
                        "role": "system",
                        "content": (
                            "Rewrite the previous supervisor routing answer as valid JSON only. "
                            "Do not add markdown, explanation, or prose. "
                            "Return exactly this shape: "
                            '{"agents":["GeneralAgent"],"parallel":false,"reasoning":"...","confidence":0.0}'
                        ),
                    },
                    {"role": "user", "content": content or user_text},
                ]
                repair_response = call_chat_once(self.runtime, repair_messages, tools=None, max_tokens=160)
                repaired = (repair_response.get("content") or "").strip()
                repaired_match = re.search(r"\{[\s\S]*\}", repaired)
                if repaired_match:
                    repaired = repaired_match.group(0)
                parsed = json.loads(repaired)
            agents = parsed.get("agents", ["GeneralAgent"])
            if not isinstance(agents, list) or not agents:
                agents = ["GeneralAgent"]

            # Validate agent names
            valid = {"FileAgent", "WebAgent", "SystemAgent", "MusicAgent",
                     "CodeAgent", "CodeWriterAgent", "ContentAgent",
                     "GeneralAgent", "TerminalAgent", "ScreenAgent",
                     "IntegrationAgent", "NavigatorAgent",
                     "TaskAgent", "ReportAgent", "ImageAgent", "PlannerAgent"}
            agents = [a for a in agents if a in valid] or ["GeneralAgent"]

            followup_scope = _resolve_followup_scope(self.runtime, user_text, history, agents)
            if followup_scope == "global_capabilities":
                agents = ["GeneralAgent"]
                parsed["parallel"] = False
                parsed["reasoning"] = "ambiguous short follow-up resolved as broader ANKITA capability question"

            if (
                _needs_local_discovery_chain(user_text)
                and not _history_has_concrete_local_target(history)
            ):
                agents = ["TerminalAgent", *[agent for agent in agents if agent != "TerminalAgent"]]
                if "GeneralAgent" in agents and len(agents) > 1:
                    agents = [agent for agent in agents if agent != "GeneralAgent"]
                parsed["parallel"] = False
                parsed["reasoning"] = (
                    "local discovery path added: inspect the real local target before acting. "
                    + str(parsed.get("reasoning", "")).strip()
                ).strip()

            # Extract confidence score (UPGRADE 13)
            confidence = float(parsed.get("confidence", 0.75))  # Default to 0.75 if not provided
            
            # Validate confidence range
            if confidence < 0.0:
                confidence = 0.0
            elif confidence > 1.0:
                confidence = 1.0

            return {
                "agents": agents,
                "parallel": bool(parsed.get("parallel", False)),  # Default sequential for safety
                "reasoning": str(parsed.get("reasoning", "")),
                "confidence": confidence,
            }
        except Exception as err:
            return {"agents": ["GeneralAgent"], "parallel": False, "reasoning": f"fallback ({err})", "confidence": 0.5}
