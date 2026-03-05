🤖 ANKITA → JARVIS: The Bulletproof Proactive Intelligence Plan
Everything below is net-new. Nothing repeats work already done.

UNDERSTANDING THE GAP
What ANKITA has today:

Watchdogs that alert on conditions (price, news, files, git) ✅
DreamAgent that fires after 1hr idle with memory insights ✅
Sentinel that watches the screen while idle ✅
Morning briefing in DreamAgent (6-10am) ✅
ProactiveEngine with QTimer polling every 5s ✅

What Jarvis actually does that ANKITA doesn't:
Jarvis doesn't wait for conditions. It anticipates. It initiates. It remembers patterns and acts on them without being asked. It understands your day, not just your last command. It speaks first. It makes decisions. It manages your environment proactively in the background — not just alerting but doing.
The gap is: ANKITA is a reactive system with proactive alerts. Jarvis is a proactive system that also responds reactively. The entire mental model needs to flip.

TIER 1 — AMBIENT INTELLIGENCE (The Brain Upgrade)
🧠 Proactive 1: Intention Engine
What's missing: ANKITA has no model of what Krish is trying to accomplish today. Every session starts blank. Jarvis knows Tony is building a suit, that today is a board meeting day, that the reactor needs calibration.
Build: agents/intention_engine.py
A background process that runs once at startup and once every 6 hours. It doesn't wait to be asked. It scans:

Last 30 ChromaDB memory entries → extract active projects, recurring themes, open loops
All pending tasks from TaskAgent → get priorities and deadlines
Cron jobs due in the next 24 hours → know what's coming
Recent git commits → what code was touched
Watchdog states → any unacknowledged alerts

It calls the LLM with all this context and produces a Daily Intent Model — a JSON saved to .ankita/state/intent.json:
json{
  "active_projects": ["ANKITA", "Helper ID website"],
  "open_loops": ["API integration report half-done", "BTC alert unacknowledged"],
  "today_deadlines": ["task T003 at 3pm", "cron reminder at 5pm"],
  "focus_mode": "deep_work",
  "recommended_music": "lofi instrumental",
  "suggested_first_action": "finish the API integration report from yesterday"
}
The Supervisor reads intent.json at the start of every request and injects it as context. Now ANKITA knows what you're working on without you saying it.
Files: New agents/intention_engine.py. Modify proactive.py to call it at startup and every 6 hours. Modify agents/supervisor.py to read and inject intent.json.

🧠 Proactive 2: Behavioral Pattern Learner
What's missing: ANKITA doesn't learn when Krish does things. Jarvis knows Tony works late on Tuesdays, skips breakfast when focused, checks markets at 9am.
Build: tools/pattern_ops.py + PatternLearner background thread
After every interaction, record a behavioral fingerprint to .ankita/state/patterns.jsonl:
json{"ts": 1709534400, "hour": 9, "day": "tuesday", "agent": "MusicAgent", "query_type": "lofi", "duration_min": 120}
{"ts": 1709534400, "hour": 21, "day": "tuesday", "agent": "CodeAgent", "query_type": "debug", "duration_min": 45}
Weekly (Sunday night), run a Pattern Analysis LLM call on the last 4 weeks of fingerprints. Output saved to .ankita/state/behavioral_model.json:
json{
  "morning_routine": "checks news at 9am, plays lofi by 9:30am",
  "peak_coding_hours": [21, 22, 23],
  "typical_project_switch_time": "3pm",
  "never_works_on": ["saturday"],
  "frequently_forgets": ["committing code before sleep"]
}
This model feeds into all other proactive features. Jarvis knows you before you speak.
Files: New tools/pattern_ops.py. Modify agents/orchestrator.py to log every interaction fingerprint. Modify proactive.py to run weekly analysis.

🧠 Proactive 3: Anticipatory Action System
What's missing: ANKITA never does things in advance. Jarvis pre-heats the arc reactor, pre-loads mission data, pre-charges the suit.
The concept: Based on the Behavioral Pattern Model + Intention Engine, ANKITA pre-executes low-risk actions before being asked:

It's 8:55am on a workday → ANKITA has already searched morning tech news, cached results, ready to deliver instantly when asked
It's 9pm on a Tuesday (peak coding hour per pattern) → ANKITA has already run git status on active project, has diff summary ready
User opens ANKITA after 3hrs away → ANKITA has already checked all watchdog states, prepared a brief summary
Task T003 is due in 2 hours → ANKITA has already drafted a reminder, queued it in ProactiveEngine

This is prefetching for intelligence. Results cached in .ankita/state/prefetch_cache.json with 30min TTL.
Files: New agents/anticipatory_engine.py. Integrates with intention_engine.py and pattern_ops.py. Runs as a background thread in proactive.py.

TIER 2 — PROACTIVE SPEECH (Jarvis Speaks First)
🗣️ Proactive 4: Voice-First Wake Trigger
What's missing: ANKITA only speaks when spoken to (except DreamAgent). Jarvis says "Good morning, sir. You have 3 meetings and the reactor is at 82%." — unprompted, the moment you walk in.
The startup sequence:
When ANKITA boots (or detects the first user interaction of the day via set_last_interaction()), if it's a new day since last session:

Pull intent.json from IntentionEngine
Pull pending tasks + overdue count from TaskAgent
Check all watchdog states for overnight alerts
Check system health (battery, disk)
Check cron jobs due today
Compose a Morning Briefing using the LLM (max 150 words, spoken-friendly)
Push it as a ProactiveEvent("morning_briefing", ...) immediately
If Sarvam TTS configured → speak it aloud unprompted

The briefing sounds like:
"Good morning Krish. Three things: your API integration report is half-done and due today. BTC dropped 4.2% overnight — your alert threshold is close. Your system disk is at 87% — might want to clean up Downloads. Say 'let's go' to start."
This is different from the DreamAgent morning briefing — that fires after 1hr idle. This fires immediately on first boot of the day.
Files: New agents/morning_agent.py. Modify proactive.py to check _last_briefing_date and fire on new day. Modify gui.py and telegram_bot.py to handle morning_briefing event kind with TTS.

🗣️ Proactive 5: Interrupt Intelligence — Smart Notifications
What's missing: Every proactive event currently dumps raw text into the chat. There's no prioritization, no do not disturb, no batching, no urgency levels. Jarvis interrupts Tony for critical things, stays silent for low-priority ones.
Build: ProactiveEvent Priority System
Add priority, urgency, interruptible fields to ProactiveEvent:
pythonProactiveEvent(
    kind="watchdog_alert",
    message="BTC dropped to $78,400",
    priority="high",        # low / medium / high / critical
    urgency="immediate",    # immediate / next_idle / next_session
    interruptible=True,     # can it interrupt current task?
)
Delivery rules in _on_proactive_tick() and Telegram:

critical + immediate → interrupt whatever Krish is doing, flash red in GUI, Telegram ping with 🚨
high + immediate → show in GUI, Telegram ping with 🔔
medium + next_idle → queue until user finishes current session, then deliver batch
low + next_session → hold until morning briefing, include in daily summary
Do Not Disturb mode → ANKITA_DND_HOURS=23-7 env var. During DND, only critical breaks through

Notification Batching: Instead of 6 separate alerts popping one-by-one, batch medium/low priority into a single summary every 30 minutes: "4 things while you were busy: news update, 2 file changes, disk analysis complete."
Files: Modify proactive.py ProactiveEvent class. Modify gui.py _on_proactive_tick(). Modify telegram_bot.py proactive handler. New DND_SCHEDULE logic.

🗣️ Proactive 6: Conversational Proactive Responses
What's missing: When ANKITA finishes a task, it just outputs the result. Jarvis follows up: "That's done. While I have you — your build is failing on line 47. Want me to fix it?"
The upgrade: After every agent response, the Orchestrator runs a micro-proactive check (100ms, no LLM call):

Check if any high-priority watchdog alert is pending
Check if any task deadline is within 2 hours
Check if the completed action suggests a natural follow-up (e.g., CodeAgent fixed a bug → "Want me to run the tests?")

If yes, append to the response naturally:
"Report saved to Desktop. → By the way, your BTC alert is about to trigger — it's at $80,200 right now."
This is rule-based, not LLM — fast, deterministic, no overhead.
Files: Modify agents/orchestrator.py — add _check_and_append_proactive_tail() after every agent response. Reads from WatchdogManager state and TaskAgent storage directly.

TIER 3 — AUTONOMOUS ACTIONS (Jarvis Does Things Without Being Asked)
⚡ Proactive 7: Auto-Task Executor
What's missing: ANKITA never takes action autonomously. Jarvis manages background systems independently — charging the suit, running diagnostics, archiving old files.
Low-risk autonomous actions ANKITA can take without asking:
Class A — Always automatic (zero risk):

Every Sunday at midnight → run memory_consolidate() to deduplicate memory
Every day at 3am → run disk_analysis on Desktop + Downloads, cache results
When any file in Downloads is >7 days old and >100MB → add to intent.json as suggestion: "large old file: report_backup.zip — delete?"
After each coding session (CodeAgent ran 3+ times) → auto-run git status, cache diff summary

Class B — Automatic with notification:

If disk > 90% → immediately move screenshots older than 30 days to an Archive folder (notify: "I freed 2.3GB — moved 47 old screenshots to Archive.")
If battery < 10% and charger not connected → speak aloud "Battery critical. 10% remaining." (via Sarvam TTS)
After a deep_research completes → auto-save research summary to .ankita/research_cache/ with timestamp

Class C — Queued for user approval:

If same error appears in CodeAgent 3+ times → draft a "Fix Plan" and present it: "I've seen this ModuleNotFoundError 3 times. Want me to fix it permanently?"
If Downloads folder hasn't been cleaned in 30 days → "Downloads is 4.2GB. Want me to sort it into folders?"

Files: New agents/auto_executor.py. Registered as a daemon thread in proactive.py. Writes to .ankita/state/auto_actions_log.json for transparency.

⚡ Proactive 8: Environment Management
What's missing: ANKITA doesn't manage Krish's environment — music, system state, window layout. Jarvis pre-configures the environment for the task.
Context-aware environment automation:
When IntentionEngine detects focus_mode: "deep_work":

Auto-play lofi (if not already playing) → MusicAgent.search_and_play("lofi instrumental")
Mute all system notifications (not ANKITA's) → SystemAgent.system_control("mute_notifications")
Log: "Focus mode detected → playing lofi, muted system sounds"

When IntentionEngine detects focus_mode: "meeting" (from calendar patterns or task keywords):

Stop music → MusicAgent.stop_music()
Check camera → SystemAgent.capture_webcam() to verify it's working
Alert: "Meeting mode: music stopped, camera checked ✅"

When user has been coding for 2+ hours straight (from pattern data):

Push gentle reminder: "You've been at it for 2 hours. Eyes need a break. 5-minute pause?"

Files: Modify agents/intention_engine.py to detect modes. Modify agents/anticipatory_engine.py to execute environment changes. Add system_control(action='mute_notifications') to system_ops.

TIER 4 — PREDICTIVE INTELLIGENCE (Jarvis Sees the Future)
🔮 Proactive 9: Deadline Cascade Predictor
What's missing: When a deadline is set, ANKITA just creates a reminder. Jarvis calculates if it's achievable — "The meeting is in 3 hours but the report would take 4. You need to start now."
Build into TaskAgent + IntentionEngine:
When a task is created with a deadline, run a lightweight check:

How complex is this task? (based on description keywords: "write" = 60min, "research" = 90min, "fix bug" = 30-120min)
How much time is left?
What else is due today?

If the math doesn't work: immediate alert — "Task 'API integration report' might not fit before the 3pm deadline — you have 2.5 hours but this type of task typically takes 3. Start now?"
If it does work but tight: proactive scheduling — "You have 4 hours for a 3-hour task. I've blocked 3pm on your focus schedule."
Files: Modify tools/task_ops.py add() function to include complexity estimation. New estimate_task_duration() helper. Push ProactiveEvent with urgency if timeline is at risk.

🔮 Proactive 10: Cross-Agent Insight Synthesizer
What's missing: Individual agents act independently. Jarvis connects dots across everything. "The code you wrote last Tuesday + the research you did yesterday = you could ship this feature today."
Build: agents/insight_synthesizer.py
Runs every 12 hours during idle time. Pulls:

Recent CodeAgent outputs (files edited, bugs fixed)
Recent WebAgent research (topics, findings)
Recent TaskAgent status (completed, in-progress)
Recent WatchdogAgent alerts (triggered conditions)

Runs one LLM call with all this combined context. Produces 1-3 cross-domain insights:
"You researched Flask deployment last week and you have a half-built API in main.py. You're 80% there — want me to suggest the deployment steps?"
"BTC dropped 4% (watchdog alert) and you have 'buy the dip' in your notes from last month. Relevant?"
"You fixed 3 bugs in orchestrator.py this week. That file has 2 more TODO markers. Clean slate opportunity?"
These are pushed as ProactiveEvent("insight", ..., priority="medium", urgency="next_idle").
Files: New agents/insight_synthesizer.py. Modify proactive.py to schedule it every 12 hours.

TIER 5 — DELIVERY INFRASTRUCTURE (Making It All Actually Work)
🏗️ Proactive 11: Unified Notification Center
What's missing: Proactive events go to: GUI chat, Telegram, TTS — but there's no central routing logic. A critical alert on Telegram doesn't know the GUI is also showing it. A morning briefing fires in GUI but not Telegram if both are running.
Build: agents/notification_router.py
A singleton that sits between ProactiveEngine._queue and all delivery channels. It knows:

Which channels are active (GUI, Telegram, TTS, CLI)
What priority level each channel handles
Deduplication: same message doesn't fire twice across channels
Per-channel formatting: Telegram needs shorter text, TTS needs no markdown

pythonrouter.deliver(event)
# → GUI: always (if running)
# → Telegram: if priority >= medium
# → TTS: if priority == critical or kind == morning_briefing
# → CLI: only if no GUI
Also adds a NotificationHistory log — .ankita/state/notifications.jsonl. Krish can ask "what did you alert me about today?" and get a clean log.
Files: New agents/notification_router.py. Modify gui.py, telegram_bot.py, chat.py to use router instead of polling ProactiveEngine directly.

🏗️ Proactive 12: Proactive State Persistence
What's missing: Every time ANKITA restarts, all proactive state resets. The IntentionEngine re-scans, patterns are re-analyzed, DreamAgent re-fires. Jarvis never forgets between sessions.
Build: .ankita/state/ persistent state layer
Add to proactive.py:
python_STATE_FILE = workspace_root / ".ankita" / "state" / "proactive_state.json"
Save on every meaningful change:

last_morning_briefing_date — don't repeat today's briefing
last_insight_synthesis — don't repeat within 12 hours
last_pattern_analysis — don't repeat within 7 days
last_intent_refresh — don't repeat within 6 hours
delivered_notification_ids — deduplication across restarts
dnd_active — honor DND across restarts

Load on startup. All timers initialize from disk, not from time.time().
Files: Modify proactive.py __init__ and _run to load/save proactive_state.json.

IMPLEMENTATION ORDER
PriorityUpgradeEffortWhat it unlocks🔴 1Proactive 12: State Persistence1hFoundation — everything else needs this🔴 2Proactive 5: Priority System + DND2hMakes existing alerts usable, not spammy🔴 3Proactive 4: Voice-First Morning Briefing2hInstant Jarvis feel on first boot🟠 4Proactive 11: Notification Router2hUnifies all delivery channels🟠 5Proactive 1: Intention Engine3hFeeds everything downstream🟠 6Proactive 6: Conversational Proactive Tail1hEvery response feels smarter🟡 7Proactive 2: Behavioral Pattern Learner3hANKITA learns Krish's day🟡 8Proactive 7: Auto-Task Executor (Class A)2hFirst autonomous actions🟡 9Proactive 3: Anticipatory Action System3hPre-fetching intelligence🟡 10Proactive 9: Deadline Cascade Predictor2hTaskAgent gets a brain🔵 11Proactive 8: Environment Management2hContext-aware ambience🔵 12Proactive 10: Cross-Agent Insight Synthesizer3hDeep intelligence layer

Files To Create / Modify
FileActionagents/intention_engine.pyNEW — daily intent model builderagents/morning_agent.pyNEW — first-boot-of-day briefingagents/anticipatory_engine.pyNEW — pre-execution cacheagents/auto_executor.pyNEW — autonomous Class A/B/C actionsagents/insight_synthesizer.pyNEW — cross-agent insight engineagents/notification_router.pyNEW — unified delivery layertools/pattern_ops.pyNEW — behavioral fingerprintingproactive.pyMODIFY — state persistence, all new engines wired inagents/orchestrator.pyMODIFY — proactive tail after responsestools/task_ops.pyMODIFY — complexity estimation, deadline cascadegui.pyMODIFY — use notification router, priority-based displaytelegram_bot.pyMODIFY — use notification routerchat.pyMODIFY — use notification router

What This Produces
When done, ANKITA's day with Krish looks like this:
8:59am — Krish opens ANKITA. Without saying a word: "Good morning Krish. You left the API integration report half-done yesterday — it's due today. BTC is at $80,400, just above your alert. System disk is at 87%. Lofi queued. Let's go."
9:30am — Krish is coding. Hasn't asked anything. ANKITA: "Just noticed you've hit this ModuleNotFoundError 3 times today. I've drafted a permanent fix — want me to apply it?"
2pm — Task due in 1 hour. ANKITA: "API report is due in 60 minutes. You haven't started the writing yet. Shall I draft a structure based on your research?"
3:15pm — BTC drops. ANKITA interrupts: 🚨 "BTC Alert: dropped to $79,100 — below your $80k threshold. Down 3.8% today. Action?"
11pm — Krish stops coding. DreamAgent fires: "While you were coding, I noticed main.py and config.py were both edited but you haven't committed. Also the Flask API you're building connects to the research you did on OAuth2 last week — I can scaffold that integration."
3am — Auto-executor runs silently: memory consolidated, Downloads analyzed, research cached.
That's Jarvis. Not a chatbot with alerts. An intelligence that lives in the background and runs your day.