# Design Document: Proactive Intelligence System

## Overview

The Proactive Intelligence System transforms ANKITA from a reactive assistant with proactive alerts into a truly proactive AI that anticipates needs, initiates actions, and manages the user's environment autonomously. The system implements a mental model shift from "reactive with proactive alerts" to "proactive with reactive capabilities."

The design follows a tiered architecture with 12 interconnected components organized into 5 tiers:
- Tier 1: Ambient Intelligence (the brain upgrade)
- Tier 2: Proactive Speech (Jarvis speaks first)
- Tier 3: Autonomous Actions (Jarvis does things without being asked)
- Tier 4: Predictive Intelligence (Jarvis sees the future)
- Tier 5: Delivery Infrastructure (making it all work)

## Architecture

### System Context

The Proactive Intelligence System integrates with ANKITA's existing architecture:

```
┌─────────────────────────────────────────────────────────────┐
│                    User Interfaces                          │
│         (GUI, Telegram Bot, CLI Chat, Voice)                │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│              Orchestrator + Supervisor                      │
│         (Routes requests to specialist agents)              │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│          PROACTIVE INTELLIGENCE SYSTEM                      │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Tier 1: Ambient Intelligence                        │  │
│  │  - IntentionEngine (every 6hrs)                      │  │
│  │  - BehavioralPatternLearner (weekly)                 │  │
│  │  - AnticipatoryActionSystem (continuous)             │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Tier 2: Proactive Speech                            │  │
│  │  - MorningAgent (6-10am daily)                       │  │
│  │  - InterruptIntelligence (priority routing)          │  │
│  │  - ConversationalProactive (micro-checks)            │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Tier 3: Autonomous Actions                          │  │
│  │  - AutoExecutor (Class A/B/C actions)                │  │
│  │  - EnvironmentManager (context-aware automation)     │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Tier 4: Predictive Intelligence                     │  │
│  │  - DeadlineCascadePredictor (task analysis)          │  │
│  │  - CrossAgentInsightSynthesizer (every 12hrs)        │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Tier 5: Delivery Infrastructure                     │  │
│  │  - NotificationRouter (central routing)              │  │
│  │  - ProactiveStatePersistence (state management)      │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│              Existing ANKITA Components                     │
│  - ChromaDB (memory storage)                                │
│  - Watchdogs (price, news, file, git)                       │
│  - DreamAgent (idle insights)                               │
│  - Sentinel (screen watching)                               │
│  - Specialist Agents (File, Web, System, etc.)              │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Ambient Intelligence Loop** (background, continuous):
   - IntentionEngine scans context every 6 hours → produces intent.json
   - BehavioralPatternLearner records fingerprints → weekly analysis → behavioral_model.json
   - AnticipatoryActionSystem reads both models → pre-executes actions → caches results

2. **Proactive Event Generation**:
   - MorningAgent triggers at first boot (6-10am) → composes briefing → pushes to queue
   - Watchdogs fire alerts → InterruptIntelligence assigns priority → routes to NotificationRouter
   - ConversationalProactive appends context to agent responses → natural follow-ups

3. **Autonomous Execution**:
   - AutoExecutor daemon polls for Class A/B/C actions → executes or queues
   - EnvironmentManager reads focus_mode from intent.json → adjusts environment

4. **Predictive Analysis**:
   - DeadlineCascadePredictor hooks into task creation → estimates complexity → alerts if at risk
   - CrossAgentInsightSynthesizer pulls agent outputs every 12hrs → synthesizes insights

5. **Delivery**:
   - All proactive events flow through NotificationRouter
   - Router checks priority, DND mode, active channels → formats and delivers
   - ProactiveStatePersistence tracks delivery history → prevents duplicates

## Components and Interfaces

### Tier 1: Ambient Intelligence

#### 1.1 IntentionEngine

**Purpose**: Builds a daily intent model by analyzing user context.

**Inputs**:
- Last 30 ChromaDB memory entries
- Pending tasks from task_ops
- Cron jobs for next 24 hours from corn/store
- Recent git commits (last 10)
- Watchdog states from watchdog_manager

**Outputs**:
- `.ankita/state/intent.json`:
  ```json
  {
    "timestamp": "2024-01-15T08:00:00",
    "active_projects": ["ankita-proactive", "helper-id"],
    "open_loops": ["finish report", "review PR #42"],
    "today_deadlines": ["submit proposal by 5pm"],
    "focus_mode": "deep_work|meeting|coding|idle",
    "recommended_music": "lofi|focus|energetic|none",
    "suggested_first_action": "Continue writing the proactive spec"
  }
  ```

**Processing**:
1. Scan all input sources
2. Single LLM call with structured prompt:
   - "Analyze this context and produce a daily intent model"
   - Include examples of good intent models
   - Request JSON output
3. Parse and validate JSON
4. Write to intent.json atomically
5. Log generation timestamp to proactive_state.json

**Schedule**: Runs at startup and every 6 hours (via ProactiveEngine timer)

**Error Handling**: If LLM call fails, use previous intent.json and log error

#### 1.2 BehavioralPatternLearner

**Purpose**: Learns user behavioral patterns over time.

**Inputs**:
- `.ankita/state/patterns.jsonl` (behavioral fingerprints)
- Each fingerprint contains:
  ```json
  {
    "timestamp": "2024-01-15T14:30:00",
    "interaction_type": "code|write|search|system",
    "duration_sec": 120,
    "tools_used": ["write_file", "execute_shell"],
    "context": "working on proactive spec"
  }
  ```

**Outputs**:
- `.ankita/state/behavioral_model.json`:
  ```json
  {
    "generated_at": "2024-01-14T22:00:00",
    "morning_routine": {
      "typical_start_time": "08:30",
      "first_actions": ["check email", "review tasks"]
    },
    "peak_coding_hours": ["10:00-12:00", "14:00-17:00"],
    "typical_project_switch_time": "90 minutes",
    "never_works_on": ["weekends after 6pm"],
    "frequently_forgets": ["commit messages", "closing files"]
  }
  ```

**Processing**:
1. Record fingerprint after every Orchestrator interaction
2. Weekly analysis (Sunday 22:00-23:00):
   - Load last 4 weeks of patterns.jsonl
   - Single LLM call: "Analyze these patterns and extract behavioral model"
   - Parse JSON response
   - Write to behavioral_model.json
3. Prune patterns.jsonl older than 30 days

**Schedule**: 
- Fingerprint recording: after every interaction
- Analysis: Sunday 22:00-23:00

**Error Handling**: If analysis fails, keep previous behavioral_model.json

#### 1.3 AnticipatoryActionSystem

**Purpose**: Pre-executes low-risk actions based on predictions.

**Inputs**:
- intent.json (current intent model)
- behavioral_model.json (learned patterns)
- Current time and user idle state

**Outputs**:
- `.ankita/state/prefetch_cache.json`:
  ```json
  {
    "morning_news": {
      "cached_at": "2024-01-15T08:50:00",
      "ttl_sec": 1800,
      "data": {"articles": [...]}
    },
    "git_status": {
      "cached_at": "2024-01-15T10:00:00",
      "ttl_sec": 1800,
      "data": {"status": "clean", "branch": "main"}
    }
  }
  ```

**Processing**:
1. Check behavioral_model for predictable actions:
   - If morning_routine includes "check news" at 9am → pre-search at 8:50am
   - If peak_coding_hours → pre-run git status
   - If away for 3hrs → prepare watchdog summary
2. Execute only low-risk actions (no writes, no side effects)
3. Cache results with 30min TTL
4. When user requests the action, serve from cache if fresh

**Low-Risk Action Criteria**:
- Read-only operations
- No external API calls with side effects
- No file writes
- No system state changes

**Schedule**: Continuous (integrated into ProactiveEngine polling loop)

**Error Handling**: If pre-execution fails, log and skip (user request will execute normally)

### Tier 2: Proactive Speech

#### 2.1 MorningAgent

**Purpose**: Delivers unprompted morning briefing at first boot of the day.

**Inputs**:
- intent.json (daily intent model)
- Pending tasks from task_ops
- Watchdog states
- System health from system_ops
- Cron jobs for today

**Outputs**:
- ProactiveEvent with kind="morning_briefing"
- Spoken-friendly text (max 150 words)

**Processing**:
1. Check proactive_state.json for last_morning_briefing_date
2. If today's date != last_briefing_date AND time is 6:00-10:00am:
   - Gather all input data
   - Single LLM call: "Compose a morning briefing (max 150 words, spoken-friendly)"
   - Parse response
   - Push ProactiveEvent to queue
   - If Sarvam TTS configured, speak aloud
   - Update last_morning_briefing_date in proactive_state.json

**Delivery Channels**: GUI, Telegram, CLI (if open), TTS (if configured)

**Schedule**: First boot of day between 6:00-10:00am

**Error Handling**: If LLM fails, use fallback template: "Good morning! You have X tasks pending and Y cron jobs scheduled today."

#### 2.2 InterruptIntelligence (Priority System)

**Purpose**: Intelligently manages notification priority and timing.

**Enhanced ProactiveEvent Structure**:
```python
class ProactiveEvent:
    kind: str  # "system", "cron", "dream_epiphany", etc.
    message: str
    data: Dict[str, Any]
    ts: float
    priority: str  # "low", "medium", "high", "critical"
    urgency: str  # "immediate", "next_idle", "next_session"
    interruptible: bool  # Can this interrupt active work?
```

**Priority Rules**:
- **critical**: Deliver immediately regardless of user state (battery critical, disk full)
- **high**: Deliver at next idle moment if user is active
- **medium**: Batch and deliver during natural breaks (every 30min)
- **low**: Batch and deliver at end of session or next startup

**DND Mode**:
- Configured via `ANKITA_DND_HOURS` env var (e.g., "22:00-08:00,13:00-14:00")
- During DND, suppress all non-critical notifications
- Critical notifications always delivered

**Batching**:
- Medium/low priority events batched in memory
- Delivered as single notification: "You have 3 updates: ..."
- Max batch size: 5 events

**Processing**:
1. When ProactiveEvent created, assign priority and urgency
2. Check current time against DND_HOURS
3. Check user active state (from idle_ops)
4. Route to NotificationRouter with delivery instructions

**Schedule**: Continuous (part of ProactiveEngine event processing)

#### 2.3 ConversationalProactive

**Purpose**: Appends relevant proactive information to agent responses.

**Inputs**:
- Agent response (just completed)
- Pending high-priority watchdog alerts
- Task deadlines within 2 hours
- Natural follow-ups (from intent.json)

**Outputs**:
- Modified agent response with appended proactive context

**Processing**:
1. After Orchestrator completes agent response, run micro-check (< 100ms)
2. No LLM calls (performance requirement)
3. Check:
   - High-priority watchdog alerts not yet delivered
   - Tasks with deadline < 2 hours
   - Natural follow-ups from intent.json (e.g., "suggested_first_action")
4. If relevant info found, append naturally:
   - "By the way, BTC dropped 5% (watchdog alert)"
   - "Also, your report is due in 90 minutes"
5. Return modified response

**Schedule**: After every agent response in Orchestrator

**Error Handling**: If micro-check fails, return original response unchanged

### Tier 3: Autonomous Actions

#### 3.1 AutoExecutor

**Purpose**: Automatically executes routine maintenance tasks.

**Action Classification**:

**Class A (Always Automatic)**:
- Memory consolidation (via memory_ops.memory_consolidate)
- Disk analysis (via system_ops)
- File cleanup suggestions (scan Downloads, Desktop)
- Auto git status (in active project directories)

**Class B (Automatic with Notification)**:
- Disk cleanup at >90% (via system_ops)
- Battery critical alerts (<10%)
- Auto-save research (from WebAgent deep_research)

**Class C (Queued for Approval)**:
- Fix plans for repeated errors (from error logs)
- Folder organization suggestions (via file_ops)

**Processing**:
1. Run as daemon registered with ProactiveEngine
2. Poll every 5 minutes for Class A/B/C conditions
3. Class A: Execute silently, log to audit.jsonl
4. Class B: Execute, push notification via NotificationRouter
5. Class C: Queue action, present to user with approve/reject UI

**Approval UI** (Class C):
- GUI: Modal dialog with action description and approve/reject buttons
- Telegram: Inline keyboard with "✅ Approve" / "❌ Reject" buttons
- CLI: Prompt with y/n input

**Schedule**: Continuous daemon (5min polling interval)

**Error Handling**: If action fails, log error and notify user

#### 3.2 EnvironmentManager

**Purpose**: Manages environment based on focus mode.

**Inputs**:
- focus_mode from intent.json
- User preferences from memory_ops

**Focus Mode Actions**:

**deep_work**:
- Auto-play lofi music (via music_ops)
- Mute non-critical notifications (set DND mode)
- Dim screen brightness (via system_ops)

**meeting**:
- Stop music
- Check camera availability (via camera_ops)
- Mute microphone (via system_ops)

**coding** (long session >90min):
- Gentle break reminder every 90 minutes
- Suggest stretching or water break

**idle**:
- Restore previous environment state
- Resume normal notification priority

**Processing**:
1. Monitor focus_mode changes in intent.json
2. When focus_mode changes, execute corresponding actions
3. Store previous state for restoration
4. Respect user preferences (e.g., "never auto-play music")

**Schedule**: Triggered by IntentionEngine updates (every 6hrs) or manual focus mode changes

**Error Handling**: If action fails (e.g., music app not installed), log and skip

### Tier 4: Predictive Intelligence

#### 4.1 DeadlineCascadePredictor

**Purpose**: Predicts if task deadlines are achievable.

**Inputs**:
- New task with deadline (from task_ops)
- Current workload (pending tasks)
- Behavioral model (typical_project_switch_time, peak_coding_hours)
- Historical task completion data

**Outputs**:
- Risk assessment: "achievable", "tight", "at_risk"
- Proactive schedule suggestion (if tight but doable)
- Alert notification (if at risk)

**Processing**:
1. Hook into task_ops.task_op(action="add") via callback
2. Estimate task complexity:
   - Use LLM call: "Estimate hours needed for: {task_description}"
   - Check similar past tasks from patterns.jsonl
   - Average the estimates
3. Calculate available time:
   - Time until deadline
   - Subtract existing task commitments
   - Subtract non-working hours (from behavioral_model)
4. Risk assessment:
   - available_time > estimated_time * 1.5 → "achievable"
   - available_time > estimated_time * 1.1 → "tight"
   - available_time < estimated_time → "at_risk"
5. If "at_risk", push high-priority alert
6. If "tight", suggest proactive schedule

**Schedule**: Triggered on task creation

**Error Handling**: If estimation fails, default to "achievable" (optimistic)

#### 4.2 CrossAgentInsightSynthesizer

**Purpose**: Synthesizes insights across different agent outputs.

**Inputs**:
- Recent outputs from CodeAgent (last 12hrs)
- Recent outputs from WebAgent (last 12hrs)
- Recent outputs from TaskAgent (last 12hrs)
- Recent outputs from WatchdogAgent (last 12hrs)

**Outputs**:
- 1-3 cross-domain insights
- ProactiveEvent with kind="insight" and priority="medium"

**Processing**:
1. Run every 12 hours during idle periods (check idle_ops)
2. Scan audit.jsonl for agent outputs in last 12hrs
3. Extract key information from each agent:
   - CodeAgent: files modified, errors encountered
   - WebAgent: topics researched, URLs visited
   - TaskAgent: tasks completed, deadlines approaching
   - WatchdogAgent: alerts fired, patterns detected
4. Single LLM call: "Synthesize 1-3 cross-domain insights from these agent outputs"
5. Parse insights
6. Push to NotificationRouter with medium priority

**Example Insights**:
- "You researched Python async patterns (WebAgent) and modified async code (CodeAgent) - consider applying those patterns to your current project"
- "You completed 3 tasks today (TaskAgent) but BTC dropped 10% (WatchdogAgent) - your portfolio may need attention"

**Schedule**: Every 12 hours during idle periods

**Error Handling**: If LLM fails or no insights found, skip silently

### Tier 5: Delivery Infrastructure

#### 5.1 NotificationRouter

**Purpose**: Central routing logic for all proactive notifications.

**Inputs**:
- ProactiveEvent from ProactiveEngine._queue
- Active channels (GUI, Telegram, CLI)
- Priority and urgency from InterruptIntelligence
- DND mode state

**Outputs**:
- Formatted notifications to each active channel
- Notification log in `.ankita/state/notifications.jsonl`

**Processing**:
1. Dequeue ProactiveEvent from ProactiveEngine._queue
2. Check if notification already delivered (via notification_id in history)
3. Check DND mode (skip if non-critical during DND)
4. Determine active channels:
   - GUI: Check if gui.py is running
   - Telegram: Check if telegram_bot.py is running
   - CLI: Check if chat.py is running
5. Format notification for each channel:
   - GUI: Rich text with icons, colors
   - Telegram: Plain text with emojis
   - CLI: Plain text
6. Deliver to each channel
7. Log to notifications.jsonl:
   ```json
   {
     "id": "notif_12345",
     "timestamp": "2024-01-15T10:30:00",
     "kind": "morning_briefing",
     "priority": "high",
     "channels": ["gui", "telegram"],
     "delivered": true
   }
   ```

**Deduplication**:
- Each ProactiveEvent gets unique ID (hash of kind + message + timestamp)
- Check notifications.jsonl for existing ID
- Skip if already delivered within last 24 hours

**Schedule**: Continuous (processes events as they arrive in queue)

**Error Handling**: If delivery to channel fails, log error and try next channel

#### 5.2 ProactiveStatePersistence

**Purpose**: Persistent state layer for proactive system.

**State File**: `.ankita/state/proactive_state.json`

**Structure**:
```json
{
  "last_morning_briefing_date": "2024-01-15",
  "last_insight_synthesis": "2024-01-15T02:00:00",
  "last_pattern_analysis": "2024-01-14T22:00:00",
  "last_intent_refresh": "2024-01-15T08:00:00",
  "delivered_notification_ids": ["notif_12345", "notif_12346"],
  "dnd_active": false,
  "focus_mode": "coding",
  "environment_state": {
    "music_playing": true,
    "brightness": 80,
    "notifications_muted": false
  }
}
```

**Operations**:
- `load_state()`: Load from disk on ProactiveEngine startup
- `save_state()`: Write to disk on every meaningful change
- `update_field(key, value)`: Update single field and save
- `get_field(key)`: Read single field

**Atomic Writes**:
- Write to temp file first
- Rename to proactive_state.json (atomic operation)
- Prevents corruption on crash

**Schedule**: 
- Load: ProactiveEngine startup
- Save: After every state change

**Error Handling**: If file corrupted, initialize with defaults

## Data Models

### IntentModel
```python
@dataclass
class IntentModel:
    timestamp: datetime
    active_projects: List[str]
    open_loops: List[str]
    today_deadlines: List[str]
    focus_mode: str  # "deep_work", "meeting", "coding", "idle"
    recommended_music: str  # "lofi", "focus", "energetic", "none"
    suggested_first_action: str
```

### BehavioralModel
```python
@dataclass
class BehavioralModel:
    generated_at: datetime
    morning_routine: Dict[str, Any]
    peak_coding_hours: List[str]
    typical_project_switch_time: str
    never_works_on: List[str]
    frequently_forgets: List[str]
```

### ProactiveEvent (Enhanced)
```python
@dataclass
class ProactiveEvent:
    kind: str
    message: str
    data: Dict[str, Any]
    ts: float
    priority: str  # "low", "medium", "high", "critical"
    urgency: str  # "immediate", "next_idle", "next_session"
    interruptible: bool
    notification_id: str  # Unique ID for deduplication
```

### BehavioralFingerprint
```python
@dataclass
class BehavioralFingerprint:
    timestamp: datetime
    interaction_type: str  # "code", "write", "search", "system"
    duration_sec: int
    tools_used: List[str]
    context: str
```

### AutoAction
```python
@dataclass
class AutoAction:
    action_class: str  # "A", "B", "C"
    action_type: str  # "memory_consolidate", "disk_cleanup", etc.
    description: str
    execute_fn: Callable
    approval_required: bool
    notification_required: bool
```

### NotificationLog
```python
@dataclass
class NotificationLog:
    id: str
    timestamp: datetime
    kind: str
    priority: str
    channels: List[str]
    delivered: bool
    error: Optional[str]
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

Now I'll analyze the acceptance criteria to determine which are testable as properties:


### Property Reflection

After analyzing all acceptance criteria, I identified several opportunities to consolidate redundant properties:

1. **State Structure Properties**: Requirements 1.4, 2.4, 3.2, 3.4, 6.1 all test that data structures contain required fields. These can be combined into a single comprehensive property about data structure validation.

2. **Round-Trip Properties**: Requirements 1.2 and 9.5 both test state persistence and restoration. These can be combined into a single round-trip property.

3. **Data Source Gathering**: Requirements 2.2, 5.2, 7.3, 11.2 all test that components gather all required inputs. These can be combined into a single property about input completeness.

4. **Priority Routing**: Requirements 6.2, 6.3, 6.4, 6.5, 6.6 all test different aspects of priority-based routing. These can be combined into a comprehensive priority routing property.

5. **Action Classification**: Requirements 8.1, 8.2, 8.3, 8.4 all test action classification and execution. These can be combined into a single property about action classification correctness.

After consolidation, we have 25 unique, non-redundant properties that provide comprehensive validation coverage.

### Correctness Properties

Property 1: State Persistence Round-Trip
*For any* valid proactive state, saving then loading should produce an equivalent state with all fields preserved
**Validates: Requirements 1.2, 1.3**

Property 2: State Structure Completeness
*For any* generated state file (proactive_state.json, intent.json, behavioral_model.json, prefetch_cache.json), all required fields for that type SHALL be present and have valid types
**Validates: Requirements 1.4, 2.4, 3.2, 3.4**

Property 3: State Initialization on Corruption
*For any* corrupted or missing state file, initializing the ProactiveEngine should produce a valid default state and log a warning
**Validates: Requirements 1.5**

Property 4: Input Source Completeness
*For any* component that requires multiple data sources (IntentionEngine, MorningAgent, ConversationalProactive, InsightSynthesizer), all required sources SHALL be queried before processing
**Validates: Requirements 2.2, 5.2, 7.3, 11.2**
