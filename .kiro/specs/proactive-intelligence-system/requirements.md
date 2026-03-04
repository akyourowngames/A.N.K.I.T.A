# Requirements Document: Proactive Intelligence System

## Introduction

The Proactive Intelligence System transforms ANKITA from a reactive assistant with proactive alerts into a truly proactive AI assistant that anticipates needs, initiates actions, and manages the user's environment autonomously. The system will flip the mental model from "reactive with proactive alerts" to "proactive with reactive capabilities" - similar to Jarvis from Iron Man.

## Glossary

- **ANKITA**: The AI assistant system being enhanced
- **ProactiveEngine**: The existing background process that polls every 5 seconds
- **IntentionEngine**: New component that analyzes user context to build a daily intent model
- **BehavioralPatternLearner**: Component that learns user patterns over time
- **AnticipatoryActionSystem**: Component that pre-executes low-risk actions based on predictions
- **NotificationRouter**: Central routing system for all proactive notifications
- **ChromaDB**: Vector database storing user memory entries
- **Watchdog**: Existing alert system that monitors conditions (price, news, files, git)
- **DreamAgent**: Existing agent that fires after 1hr idle with memory insights
- **Sentinel**: Existing component that watches the screen while idle
- **LLM**: Large Language Model used for AI reasoning
- **Class_A_Action**: Automatic action that always executes without user approval
- **Class_B_Action**: Automatic action that executes with notification
- **Class_C_Action**: Action queued for user approval before execution
- **DND_Mode**: Do Not Disturb mode that suppresses non-critical notifications
- **ProactiveEvent**: Data structure representing a proactive notification or action
- **IntentModel**: Daily model containing active projects, deadlines, focus mode, and recommendations
- **BehavioralModel**: Weekly model containing user patterns like morning routine and peak hours

## Requirements

### Requirement 1: State Persistence Foundation

**User Story:** As a system administrator, I want ANKITA to persist its proactive state across restarts, so that the system maintains continuity and doesn't lose context.

#### Acceptance Criteria

1. THE ProactiveEngine SHALL maintain a persistent state file at .ankita/state/proactive_state.json
2. WHEN the system starts, THE ProactiveEngine SHALL load the persistent state from disk
3. WHEN meaningful state changes occur, THE ProactiveEngine SHALL save the state to disk immediately
4. THE persistent state SHALL include last_morning_briefing_date, last_insight_synthesis, last_pattern_analysis, last_intent_refresh, delivered_notification_ids, and dnd_active fields
5. IF the state file is corrupted or missing, THEN THE ProactiveEngine SHALL initialize with default values and log a warning

### Requirement 2: Intention Engine

**User Story:** As a user, I want ANKITA to understand my daily intentions and context, so that it can provide relevant proactive assistance.

#### Acceptance Criteria

1. THE IntentionEngine SHALL run at system startup and every 6 hours thereafter
2. WHEN the IntentionEngine runs, THE system SHALL scan the last 30 ChromaDB memory entries, pending tasks, cron jobs for the next 24 hours, recent git commits, and watchdog states
3. THE IntentionEngine SHALL produce a Daily Intent Model and save it to .ankita/state/intent.json
4. THE Intent Model SHALL include active_projects, open_loops, today_deadlines, focus_mode, recommended_music, and suggested_first_action fields
5. WHEN any agent processes a request, THE Supervisor SHALL read intent.json and inject it as context
6. IF the IntentionEngine fails to generate an intent model, THEN THE system SHALL use the previous intent model and log an error

### Requirement 3: Behavioral Pattern Learning

**User Story:** As a user, I want ANKITA to learn my behavioral patterns over time, so that it can anticipate my needs based on my habits.

#### Acceptance Criteria

1. WHEN any interaction completes, THE system SHALL record a behavioral fingerprint to .ankita/state/patterns.jsonl
2. THE behavioral fingerprint SHALL include timestamp, interaction_type, duration, tools_used, and context fields
3. WHEN Sunday night arrives (between 22:00-23:00), THE BehavioralPatternLearner SHALL analyze the last 4 weeks of patterns
4. THE BehavioralPatternLearner SHALL produce a behavioral_model.json file with morning_routine, peak_coding_hours, typical_project_switch_time, never_works_on, and frequently_forgets fields
5. THE pattern analysis SHALL use a single LLM call to synthesize patterns from the raw fingerprint data

### Requirement 4: Anticipatory Action System

**User Story:** As a user, I want ANKITA to pre-execute low-risk actions based on my patterns, so that information is ready when I need it.

#### Acceptance Criteria

1. THE AnticipatoryActionSystem SHALL pre-execute actions based on the Behavioral Model and Intent Model
2. WHEN the Behavioral Model indicates morning news reading at 8:55am, THE system SHALL pre-search morning news at 8:50am
3. WHEN the Behavioral Model indicates peak coding hours, THE system SHALL pre-run git status checks
4. WHEN the user has been away for 3 hours, THE system SHALL prepare a watchdog summary
5. THE system SHALL cache anticipatory results in .ankita/state/prefetch_cache.json with a 30-minute TTL
6. THE system SHALL only pre-execute actions classified as low-risk (no writes, no external API calls with side effects)

### Requirement 5: Voice-First Morning Briefing

**User Story:** As a user, I want ANKITA to greet me with a morning briefing unprompted, so that I start my day informed without asking.

#### Acceptance Criteria

1. WHEN the system boots for the first time each day (between 6:00-10:00am), THE MorningAgent SHALL compose and deliver a morning briefing unprompted
2. THE morning briefing SHALL pull data from intent.json, pending tasks, watchdog states, system health, and cron jobs
3. THE morning briefing SHALL be maximum 150 words and spoken-friendly
4. WHERE Sarvam TTS is configured, THE system SHALL speak the briefing aloud
5. THE system SHALL deliver the briefing through all active channels (GUI, Telegram, CLI if open)
6. THE system SHALL record the briefing delivery date in proactive_state.json to prevent duplicate briefings

### Requirement 6: Priority-Based Notification System

**User Story:** As a user, I want ANKITA to intelligently manage notification priority and timing, so that I'm not interrupted unnecessarily.

#### Acceptance Criteria

1. THE ProactiveEvent data structure SHALL include priority (low/medium/high/critical), urgency (immediate/next_idle/next_session), and interruptible fields
2. WHEN a critical priority event occurs, THE system SHALL deliver it immediately regardless of user state
3. WHEN a high priority event occurs during active work, THE system SHALL deliver it at the next idle moment
4. WHEN medium or low priority events occur, THE system SHALL batch them and deliver during natural breaks
5. WHERE DND mode is active (configured via ANKITA_DND_HOURS environment variable), THE system SHALL suppress all non-critical notifications
6. THE system SHALL respect per-event interruptible flags when determining delivery timing

### Requirement 7: Conversational Proactive Responses

**User Story:** As a user, I want ANKITA to naturally append relevant proactive information to its responses, so that I receive contextual assistance without additional prompts.

#### Acceptance Criteria

1. WHEN any agent completes a response, THE Orchestrator SHALL run a micro-proactive check within 100ms
2. THE micro-proactive check SHALL NOT use LLM calls to maintain performance
3. THE micro-proactive check SHALL examine pending high-priority watchdog alerts, task deadlines within 2 hours, and natural follow-ups
4. WHEN relevant proactive information is found, THE system SHALL append it naturally to the response
5. THE appended information SHALL be contextually relevant to the user's current request

### Requirement 8: Autonomous Task Execution

**User Story:** As a user, I want ANKITA to automatically execute routine maintenance tasks, so that my system stays healthy without manual intervention.

#### Acceptance Criteria

1. THE AutoExecutor SHALL classify actions into Class A (always automatic), Class B (automatic with notification), and Class C (queued for approval)
2. THE system SHALL automatically execute Class A actions: memory consolidation, disk analysis, file cleanup suggestions, and auto git status
3. THE system SHALL automatically execute Class B actions with notification: disk cleanup at >90%, battery critical alerts, and auto-save research
4. THE system SHALL queue Class C actions for approval: fix plans for repeated errors and folder organization suggestions
5. THE AutoExecutor SHALL run as a daemon registered with the ProactiveEngine
6. WHEN a Class C action is queued, THE system SHALL present it to the user with a clear approve/reject interface

### Requirement 9: Context-Aware Environment Management

**User Story:** As a user, I want ANKITA to manage my environment based on my current focus mode, so that my workspace adapts to my needs automatically.

#### Acceptance Criteria

1. WHEN the IntentionEngine sets focus_mode to "deep_work", THE system SHALL auto-play lofi music and mute non-critical notifications
2. WHEN the IntentionEngine sets focus_mode to "meeting", THE system SHALL stop music and check camera availability
3. WHEN the user has been in a coding session for 90 minutes, THE system SHALL provide a gentle break reminder
4. THE environment management actions SHALL be configurable via user preferences
5. THE system SHALL restore previous environment state when focus mode changes

### Requirement 10: Deadline Cascade Prediction

**User Story:** As a user, I want ANKITA to predict if my task deadlines are achievable, so that I can adjust my plans proactively.

#### Acceptance Criteria

1. WHEN a task is created with a deadline, THE system SHALL estimate the task complexity based on description and historical data
2. THE system SHALL check if the deadline is achievable given current workload and behavioral patterns
3. IF the timeline is at risk, THEN THE system SHALL alert the user with specific concerns
4. IF the timeline is tight but doable, THEN THE system SHALL suggest a proactive schedule
5. THE complexity estimation SHALL consider similar past tasks from the behavioral model

### Requirement 11: Cross-Agent Insight Synthesis

**User Story:** As a user, I want ANKITA to synthesize insights across different agents, so that I receive holistic intelligence about my work.

#### Acceptance Criteria

1. THE InsightSynthesizer SHALL run every 12 hours during idle periods
2. WHEN the InsightSynthesizer runs, THE system SHALL pull recent outputs from CodeAgent, WebAgent, TaskAgent, and WatchdogAgent
3. THE InsightSynthesizer SHALL use one LLM call to produce 1-3 cross-domain insights
4. THE insights SHALL identify patterns, connections, or opportunities across different work domains
5. THE system SHALL deliver synthesized insights through the NotificationRouter with medium priority

### Requirement 12: Unified Notification Routing

**User Story:** As a system administrator, I want all proactive notifications to flow through a central router, so that delivery is consistent and manageable.

#### Acceptance Criteria

1. THE NotificationRouter SHALL serve as the central routing logic between ProactiveEngine._queue and all delivery channels
2. THE NotificationRouter SHALL know which channels are active (GUI, Telegram, CLI)
3. THE NotificationRouter SHALL handle priority-based routing, deduplication, and per-channel formatting
4. THE NotificationRouter SHALL log all notifications to .ankita/state/notifications.jsonl
5. WHEN a notification is delivered through multiple channels, THE system SHALL deduplicate based on notification ID
6. THE NotificationRouter SHALL format notifications appropriately for each channel (rich text for GUI, plain text for Telegram, etc.)
