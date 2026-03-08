---
inclusion: always
---

# Persistent Context for Kiro

## About This Project
This is A.N.K.I.T.A - an AI assistant with multi-agent orchestration, voice interaction, and scheduled task management.

**Migration to Google ADK:** The project is being migrated to use Google's Agent Development Kit (ADK) for agent orchestration and tool management.

## Key Information
- Project uses Python with PyQt6 for GUI
- Main entry point: `gui.py`
- Agent system in `agents/` folder with orchestrator and specialists
- LLM client wrapper in `llm/client.py`
- Scheduled tasks managed by `corn/` (cron-like system)
- Tools for various operations in `tools/` folder

## Your Preferences
- Keep code minimal and focused
- Avoid verbose implementations
- Use existing tools and patterns in the codebase
- NEVER create markdown files unless explicitly requested by the user

## Important Notes
- All requests are handled directly by the orchestrator
- Session history is managed by session_manager.py

## Memory System (OpenClaw-inspired) ✅ COMPLETE
**Architecture:** Write-Ahead Log (WAL) Protocol - Write BEFORE responding

**Core Components:**
- **Daily Logs**: `memory/daily/YYYY-MM-DD.jsonl` - Auto-logged conversations
- **Long-term Memory**: `memory/MEMORY.md` - Curated knowledge by category
- **Preferences**: `memory/preferences.md` - User preferences
- **SESSION-STATE.md**: Hot working memory for current task (like RAM)
- **Auto-extractor**: Regex-based backup extraction (enhancement over OpenClaw)

**How It Works (OpenClaw WAL Protocol):**
1. User provides concrete detail (name, preference, correction)
2. Agent detects it and calls `remember` tool BEFORE responding
3. Memory written to disk (Write-Ahead Log)
4. Then agent responds normally
5. **Key:** Trigger = USER INPUT (reliable), not agent memory (unreliable)

**OpenClaw Approach:**
- Uses LLM to detect what's important
- But enforces WAL: "If user gives detail → write BEFORE responding"
- Rule fires on user input, not agent memory
- Agent instructed to check for concrete details automatically

**Our Enhancement:**
- Regex patterns as backup (faster, no LLM call needed)
- Automatic extraction for common patterns
- Falls back to LLM-based detection for complex cases

## ADK Migration Status
**Phase 1: Setup & Installation** ✅ COMPLETE
- google-adk installed (v1.26.0)
- GOOGLE_API_KEY configured in .env
- Basic ADK agent structure created in agents/adk_agent.py

**Phase 2: Agent Migration** ✅ COMPLETE
- Created adk_tools.py adapter to wrap existing ANKITA tools for ADK
- Reduced to 3 essential tools (search_web, read_file, write_file) to minimize token usage
- Updated AnkitaADKAgent to use google.genai client directly with function calling
- Full GUI integration: AskWorker, VoiceCallWorker, and _ContentRequestWorker all support ADK
- Added visual indicators (window title and startup message) to show active agent
- Both systems work side-by-side for gradual migration

**Implementation Details:**
- ADK agent uses `google.genai.Client` with automatic function calling
- Tools are wrapped from existing ANKITA tools via adk_tools.py adapter
- Agent bypasses complex ADK Runner/InvocationContext for simpler direct API calls
- Works with gemini-2.0-flash model

**How to Use ADK:**
- Set `ANKITA_USE_ADK=true` in .env to enable ADK agent (currently disabled due to API quota)
- Set `ANKITA_USE_ADK=false` to use original orchestrator (current setting)
- Window title shows which agent is active: "A.N.K.I.T.A - ADK (Gemini)" or "A.N.K.I.T.A - Orchestrator"
- Startup message displays: "Agent: Google ADK (Gemini 2.0)" or "Agent: Multi-Agent Orchestrator"

**Testing:**
- Run `python test_adk_simple.py` to verify ADK agent (note: may hit API quota limits)
- Run `python gui.py` to test in GUI mode
- All 40+ ANKITA tools are available through the adapter

**Known Issues:**
- Google API free tier has strict rate limits (limit: 0 tokens/min on free tier) - requires paid tier for actual use
- Current quota exhausted from testing - need to wait ~50 seconds between requests
- ADK's native Runner/InvocationContext API is complex - current implementation uses direct genai client instead
- Reduced to 3 tools to minimize token usage and avoid quota issues

## Skills System (OpenClaw-inspired) ✅ COMPLETE
**Architecture:** Self-expanding agent with hot-reload skills

**Core Components:**
- **Skill System**: `skills/skill_system.py` - Manages skills (pre-built workflows)
- **Three-tier directories**: workspace > user > bundled (priority order)
- **SKILL.md format**: YAML frontmatter + Steps + Rules sections
- **Hot-reload**: Scans on every prompt (sub-millisecond) - no restart needed
- **Meta-skill**: skill-creator can create new skills on demand

**How It Works (OpenClaw Pattern):**
1. Agent scans skill directories on EVERY prompt (hot-reload)
2. Injects compact skills summary into system prompt (<skills> XML)
3. Matches user message to skill triggers (keyword-based)
4. If matched, loads full skill instructions into context
5. Agent follows skill steps to execute workflow

**Skill Directories:**
- `.kiro/skills/` - Workspace skills (project-specific, highest priority)
- `~/.kiro/skills/` - User skills (personal, shared across projects)
- `skills/bundled/` - Bundled skills (defaults, lowest priority)

**Bundled Skills:**
- `skill-creator` - Meta-skill that creates new skills (self-expansion)
- `web-search` - Search web and synthesize structured summaries
- `web-fetch` - Fetch and read full content from specific URLs
- `terminal-run` - Execute terminal commands safely with error handling

**Usage:**
- `/skills` command lists available skills
- "create skill for X" triggers skill-creator meta-skill
- Skills auto-activate based on trigger keywords
- New skills available immediately (hot-reload)

**Testing:**
- Run `python test_skills.py` to verify skills system
- Run `python chatbot.py` to test in CLI mode with skills

**Token Cost:**
- Base overhead: 195 chars when skills exist
- Per skill: 97 chars (name + description only)
- Full instructions only load when skill is triggered

## Web Search System (2026 Benchmark) ✅ COMPLETE
**Architecture:** Three-tier AI-native search with intelligent caching

**Core Components:**
- **Tier 1 - Fast Facts**: Brave Search API (669ms avg, Agent Score 14.89)
- **Tier 2 - Deep Content**: Firecrawl API (~1,300ms, full page extraction)
- **Tier 3 - Fallback**: Tavily API (998ms avg, Agent Score 13.67)
- **Caching Layer**: File-based cache with TTL by search type

**Implementation:**
- `tools/web_search_tool.py` - AI-optimized search with caching
- `tools/web_fetch_tool.py` - Deep content extraction
- `skills/bundled/web-search/` - Search skill with synthesis
- `skills/bundled/web-fetch/` - Fetch skill for full page reads

**How It Works:**
1. Check cache first (under 5ms if hit)
2. Try Brave Search API (669ms avg if miss)
3. Fallback to Tavily if Brave unavailable
4. Apply source quality filtering (block low-quality domains)
5. Prioritize preferred sources (Wikipedia, official docs, etc.)
6. Cache results with TTL: news=5min, general=1hr, reference=24hr

**Latency Budget:**
- Cache hit: <5ms
- Cache miss (Brave): ~700ms total (669ms search + 31ms processing)
- Parallel searches: 3 searches = ~700ms (not 2,100ms)
- Deep fetch: ~1,300ms for full page

**API Keys (Free Tiers):**
- BRAVE_API_KEY: 2,000 queries/month - https://brave.com/search/api/
- TAVILY_API_KEY: 1,000 credits/month - https://tavily.com
- FIRECRAWL_API_KEY: For deep content - https://firecrawl.dev

**Features:**
- Source quality filtering (blocks Reddit, Quora, social media)
- Preferred source prioritization (Wikipedia, GitHub, Stack Overflow)
- Dense excerpts (token-efficient, query-relevant content)
- Clean JSON output (no HTML parsing needed)
- Automatic caching with smart TTL
- Parallel search support

**Testing:**
- Run `python test_web_search.py` to verify search system
- Tests cache hit/miss, latency measurement, and API integration

**Usage in Skills:**
- `search_web` tool for finding information
- `fetch_webpage` tool for reading full articles
- Skills automatically use these tools when triggered
- Meta-skill uses search before creating new skills

## Knowledge Gap Handling (OpenClaw-inspired) ✅ COMPLETE
**Architecture:** Proactive web search for unknown information

**How It Works:**
1. Agent detects knowledge gap (unfamiliar term, current event, specific fact)
2. Automatically calls `search_web` tool BEFORE responding
3. Synthesizes search results into natural response
4. Never says "I don't know" without attempting search first

**System Prompt Instructions:**
- "If you don't know something or lack current information, use 'search_web' tool FIRST"
- "Never say 'I don't know' without attempting to search"
- "Search for: current events, recent updates, unfamiliar terms, specific facts"
- "After searching, synthesize the information in your response"

**Example Flow:**
- User: "What is OpenClaw?"
- Agent: [Detects unfamiliar term] → Calls search_web("OpenClaw")
- Agent: [Receives results] → "OpenClaw is a free and open-source autonomous AI agent..."

**Benefits:**
- More helpful and informative responses
- Reduces "I don't know" dead-ends
- Leverages web search as knowledge extension
- Matches OpenClaw's proactive behavior
