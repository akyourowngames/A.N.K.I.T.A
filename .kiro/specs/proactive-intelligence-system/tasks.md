# Implementation Plan: Proactive Intelligence System

## Overview

This implementation plan transforms ANKITA from a reactive assistant into a truly proactive AI that anticipates needs, initiates actions, and manages the user's environment autonomously. The implementation follows a tiered architecture with 5 tiers: Ambient Intelligence, Proactive Speech, Autonomous Actions, Predictive Intelligence, and Delivery Infrastructure.

The implementation strategy focuses on building the foundational infrastructure first (Tier 5), then the intelligence layers (Tier 1), followed by proactive speech (Tier 2), autonomous actions (Tier 3), and finally predictive intelligence (Tier 4).

## Tasks

- [~] 1. Set up foundational infrastructure and state management
  - [x] 1.1 Create state persistence layer (ProactiveStatePersistence)
    - Create `.ankita/state/` directory structure
    - Implement `ProactiveStatePersistence` class with load_state(), save_state(), update_field(), get_field() methods
    - Implement atomic writes using temp file + rename pattern
    - Add default state initialization for corrupted/missing files
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_
  
  - [x] 1.2 Write property test for state persistence
    - **Property 1: State Persistence Round-Trip**
    - **Validates: Requirements 1.2, 1.3**
  
  - [x] 1.3 Write property test for state structure validation
    - **Property 2: State Structure Completeness**
    - **Validates: Requirements 1.4, 2.4, 3.2, 3.4**
  
  - [x] 1.4 Write unit test for state corruption handling
    - Test corrupted JSON file initialization
    - Test missing file initialization
    - Verify warning logs are generated
    - _Requirements: 1.5_

- [~] 2. Implement data models and core structures
  - [x] 2.1 Create data model classes
    - Implement `IntentModel` dataclass with all required fields
    - Implement `BehavioralModel` dataclass with all required fields
    - Implement enhanced `ProactiveEvent` dataclass with priority, urgency, interruptible, notification_id fields
    - Implement `BehavioralFingerprint` dataclass
    - Implement `AutoAction` dataclass
    - Implement `NotificationLog` dataclass
    - _Requirements: 2.4, 3.2, 3.4, 6.1_
  
  - [x] 2.2 Write unit tests for data model validation
    - Test field types and constraints
    - Test serialization/deserialization
    - _Requirements: 2.4, 3.2, 3.4, 6.1_


- [~] 3. Build Tier 5: Delivery Infrastructure
  - [x] 3.1 Implement NotificationRouter
    - Create `NotificationRouter` class with central routing logic
    - Implement channel detection (GUI, Telegram, CLI active checks)
    - Implement per-channel formatting (rich text for GUI, plain text for Telegram/CLI)
    - Implement deduplication logic using notification IDs
    - Implement notification logging to `.ankita/state/notifications.jsonl`
    - Add DND mode checking (read from `ANKITA_DND_HOURS` env var)
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_
  
  - [x] 3.2 Write property test for notification deduplication
    - **Property 5: Notification Deduplication**
    - **Validates: Requirements 12.5**
  
  - [x] 3.3 Write unit tests for NotificationRouter
    - Test channel detection logic
    - Test per-channel formatting
    - Test DND mode filtering
    - _Requirements: 12.2, 12.3, 12.6_

- [x] 4. Checkpoint - Ensure infrastructure tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [~] 5. Build Tier 1: Ambient Intelligence - IntentionEngine
  - [x] 5.1 Implement IntentionEngine
    - Create `IntentionEngine` class with context scanning logic
    - Implement data gathering from ChromaDB (last 30 entries), task_ops, corn/store, git, watchdog_manager
    - Implement LLM call with structured prompt for intent model generation
    - Implement JSON parsing and validation
    - Implement atomic write to `.ankita/state/intent.json`
    - Add error handling to use previous intent.json on failure
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  
  - [x] 5.2 Write property test for input source completeness
    - **Property 4: Input Source Completeness**
    - **Validates: Requirements 2.2, 5.2, 7.3, 11.2**
  
  - [x] 5.3 Write unit tests for IntentionEngine
    - Test LLM failure fallback to previous intent.json
    - Test JSON validation
    - Test schedule timing (startup + every 6 hours)
    - _Requirements: 2.6_

- [~] 6. Build Tier 1: Ambient Intelligence - BehavioralPatternLearner
  - [x] 6.1 Implement BehavioralPatternLearner
    - Create `BehavioralPatternLearner` class
    - Implement fingerprint recording after every Orchestrator interaction
    - Implement weekly analysis logic (Sunday 22:00-23:00)
    - Implement LLM call for pattern synthesis
    - Implement write to `.ankita/state/behavioral_model.json`
    - Implement patterns.jsonl pruning (>30 days)
    - Add error handling to keep previous behavioral_model.json on failure
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  
  - [x] 6.2 Write property test for fingerprint recording
    - **Property 6: Fingerprint Recording Completeness**
    - **Validates: Requirements 3.1, 3.2**
  
  - [x] 6.3 Write unit tests for BehavioralPatternLearner
    - Test weekly analysis timing
    - Test patterns.jsonl pruning
    - Test LLM failure handling
    - _Requirements: 3.3, 3.5_


- [~] 7. Build Tier 1: Ambient Intelligence - AnticipatoryActionSystem
  - [x] 7.1 Implement AnticipatoryActionSystem
    - Create `AnticipatoryActionSystem` class
    - Implement prediction logic based on behavioral_model.json and intent.json
    - Implement low-risk action classification (read-only, no side effects)
    - Implement pre-execution for morning news, git status, watchdog summary
    - Implement caching to `.ankita/state/prefetch_cache.json` with 30min TTL
    - Add cache serving logic for user requests
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_
  
  - [~] 7.2 Write property test for cache TTL expiration
    - **Property 7: Cache TTL Expiration**
    - **Validates: Requirements 4.5**
  
  - [~] 7.3 Write unit tests for AnticipatoryActionSystem
    - Test low-risk action classification
    - Test pre-execution timing
    - Test cache serving logic
    - _Requirements: 4.2, 4.3, 4.6_

- [~] 8. Checkpoint - Ensure Tier 1 tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [~] 9. Build Tier 2: Proactive Speech - MorningAgent
  - [~] 9.1 Implement MorningAgent
    - Create `MorningAgent` class
    - Implement first-boot-of-day detection (check proactive_state.json)
    - Implement time window check (6:00-10:00am)
    - Implement data gathering from intent.json, task_ops, watchdog_manager, system_ops, corn
    - Implement LLM call for briefing composition (max 150 words, spoken-friendly)
    - Implement ProactiveEvent creation and queue push
    - Implement TTS integration (if Sarvam configured)
    - Update last_morning_briefing_date in proactive_state.json
    - Add fallback template for LLM failures
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_
  
  - [~] 9.2 Write unit tests for MorningAgent
    - Test first-boot-of-day detection
    - Test time window filtering
    - Test fallback template on LLM failure
    - Test duplicate briefing prevention
    - _Requirements: 5.1, 5.6_

- [~] 10. Build Tier 2: Proactive Speech - InterruptIntelligence
  - [~] 10.1 Implement InterruptIntelligence (Priority System)
    - Create `InterruptIntelligence` class
    - Implement priority assignment logic (low/medium/high/critical)
    - Implement urgency assignment logic (immediate/next_idle/next_session)
    - Implement DND mode checking (parse ANKITA_DND_HOURS env var)
    - Implement user active state checking (via idle_ops)
    - Implement batching logic for medium/low priority events (max 5 events)
    - Implement delivery timing rules based on priority and user state
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_
  
  - [~] 10.2 Write property test for priority-based routing
    - **Property 8: Priority-Based Routing Correctness**
    - **Validates: Requirements 6.2, 6.3, 6.4, 6.5, 6.6**
  
  - [~] 10.3 Write unit tests for InterruptIntelligence
    - Test DND mode parsing and filtering
    - Test batching logic
    - Test delivery timing for each priority level
    - _Requirements: 6.5, 6.6_


- [~] 11. Build Tier 2: Proactive Speech - ConversationalProactive
  - [~] 11.1 Implement ConversationalProactive
    - Create `ConversationalProactive` class
    - Implement micro-check logic (<100ms, no LLM calls)
    - Implement checks for high-priority watchdog alerts, task deadlines <2hrs, natural follow-ups
    - Implement natural appending to agent responses
    - Add error handling to return original response on failure
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_
  
  - [~] 11.2 Write property test for micro-check performance
    - **Property 9: Micro-Check Performance**
    - **Validates: Requirements 7.2**
  
  - [~] 11.3 Write unit tests for ConversationalProactive
    - Test watchdog alert detection
    - Test deadline detection
    - Test natural appending format
    - Test error handling fallback
    - _Requirements: 7.3, 7.4, 7.5_

- [~] 12. Checkpoint - Ensure Tier 2 tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [~] 13. Build Tier 3: Autonomous Actions - AutoExecutor
  - [~] 13.1 Implement AutoExecutor
    - Create `AutoExecutor` class with daemon polling (5min interval)
    - Implement action classification (Class A/B/C)
    - Implement Class A actions: memory consolidation, disk analysis, file cleanup suggestions, auto git status
    - Implement Class B actions: disk cleanup at >90%, battery critical alerts, auto-save research
    - Implement Class C actions: fix plans for repeated errors, folder organization suggestions
    - Implement approval UI for Class C (GUI modal, Telegram inline keyboard, CLI prompt)
    - Implement audit logging to audit.jsonl
    - Add error handling and user notification on action failure
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_
  
  - [~] 13.2 Write property test for action classification
    - **Property 10: Action Classification Correctness**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4**
  
  - [~] 13.3 Write unit tests for AutoExecutor
    - Test Class A silent execution
    - Test Class B notification delivery
    - Test Class C approval queueing
    - Test error handling
    - _Requirements: 8.2, 8.3, 8.4, 8.6_

- [~] 14. Build Tier 3: Autonomous Actions - EnvironmentManager
  - [~] 14.1 Implement EnvironmentManager
    - Create `EnvironmentManager` class
    - Implement focus mode monitoring (watch intent.json changes)
    - Implement deep_work actions: auto-play lofi, mute notifications, dim brightness
    - Implement meeting actions: stop music, check camera, mute microphone
    - Implement coding session break reminders (>90min)
    - Implement idle state restoration
    - Implement user preference checking (via memory_ops)
    - Add state storage for restoration
    - Add error handling for failed actions (e.g., music app not installed)
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_
  
  - [~] 14.2 Write property test for environment state restoration
    - **Property 11: Environment State Restoration**
    - **Validates: Requirements 9.5**
  
  - [~] 14.3 Write unit tests for EnvironmentManager
    - Test each focus mode action set
    - Test user preference overrides
    - Test error handling for missing dependencies
    - _Requirements: 9.1, 9.2, 9.3, 9.4_


- [~] 15. Checkpoint - Ensure Tier 3 tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [~] 16. Build Tier 4: Predictive Intelligence - DeadlineCascadePredictor
  - [~] 16.1 Implement DeadlineCascadePredictor
    - Create `DeadlineCascadePredictor` class
    - Implement hook into task_ops.task_op(action="add") via callback
    - Implement task complexity estimation (LLM call + historical data)
    - Implement available time calculation (deadline - existing commitments - non-working hours)
    - Implement risk assessment logic (achievable/tight/at_risk thresholds)
    - Implement high-priority alert for at_risk tasks
    - Implement proactive schedule suggestion for tight tasks
    - Add error handling to default to "achievable" on estimation failure
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_
  
  - [~] 16.2 Write property test for complexity estimation
    - **Property 12: Complexity Estimation Consistency**
    - **Validates: Requirements 10.2**
  
  - [~] 16.3 Write unit tests for DeadlineCascadePredictor
    - Test risk assessment thresholds
    - Test alert generation for at_risk tasks
    - Test schedule suggestion for tight tasks
    - Test error handling fallback
    - _Requirements: 10.3, 10.4, 10.5_

- [~] 17. Build Tier 4: Predictive Intelligence - CrossAgentInsightSynthesizer
  - [~] 17.1 Implement CrossAgentInsightSynthesizer
    - Create `CrossAgentInsightSynthesizer` class
    - Implement 12-hour schedule with idle period detection
    - Implement audit.jsonl scanning for last 12hrs of agent outputs
    - Implement key information extraction from CodeAgent, WebAgent, TaskAgent, WatchdogAgent
    - Implement LLM call for insight synthesis (1-3 insights)
    - Implement ProactiveEvent creation with medium priority
    - Add silent skip on LLM failure or no insights found
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_
  
  - [~] 17.2 Write property test for agent output extraction
    - **Property 13: Agent Output Extraction Completeness**
    - **Validates: Requirements 11.2, 11.3**
  
  - [~] 17.3 Write unit tests for CrossAgentInsightSynthesizer
    - Test 12-hour schedule timing
    - Test idle period detection
    - Test insight synthesis
    - Test silent failure handling
    - _Requirements: 11.1, 11.5_

- [~] 18. Checkpoint - Ensure Tier 4 tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [~] 19. Integrate all components into ProactiveEngine
  - [~] 19.1 Update ProactiveEngine with new components
    - Register IntentionEngine with 6-hour schedule
    - Register BehavioralPatternLearner with weekly schedule
    - Register AnticipatoryActionSystem in polling loop
    - Register MorningAgent with first-boot-of-day trigger
    - Register InterruptIntelligence in event processing
    - Register ConversationalProactive in Orchestrator response flow
    - Register AutoExecutor daemon with 5-min polling
    - Register EnvironmentManager with focus mode monitoring
    - Register DeadlineCascadePredictor callback in task_ops
    - Register CrossAgentInsightSynthesizer with 12-hour schedule
    - Wire NotificationRouter to ProactiveEngine._queue
    - Wire ProactiveStatePersistence to all components
    - _Requirements: All requirements_
  
  - [~] 19.2 Write integration tests for ProactiveEngine
    - Test component registration
    - Test event flow from generation to delivery
    - Test state persistence across restarts
    - _Requirements: All requirements_


- [~] 20. Update Orchestrator and Supervisor for intent injection
  - [~] 20.1 Modify Supervisor to inject intent context
    - Update Supervisor to read `.ankita/state/intent.json` on every request
    - Inject intent model as context into agent prompts
    - Add error handling for missing or corrupted intent.json
    - _Requirements: 2.5_
  
  - [~] 20.2 Write unit tests for intent injection
    - Test intent.json reading
    - Test context injection into prompts
    - Test error handling for missing file
    - _Requirements: 2.5_

- [~] 21. Update existing agents to record behavioral fingerprints
  - [~] 21.1 Add fingerprint recording to Orchestrator
    - Hook into Orchestrator completion flow
    - Record timestamp, interaction_type, duration, tools_used, context
    - Append to `.ankita/state/patterns.jsonl`
    - _Requirements: 3.1_
  
  - [~] 21.2 Write unit tests for fingerprint recording
    - Test fingerprint structure
    - Test JSONL appending
    - Test timestamp accuracy
    - _Requirements: 3.1, 3.2_

- [~] 22. Add ConversationalProactive to agent response flow
  - [~] 22.1 Integrate ConversationalProactive into Orchestrator
    - Hook ConversationalProactive after agent response completion
    - Pass agent response through micro-check
    - Append proactive information if found
    - Return modified response
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_
  
  - [~] 22.2 Write integration tests for ConversationalProactive
    - Test response modification
    - Test performance (<100ms requirement)
    - Test error handling fallback
    - _Requirements: 7.2, 7.5_

- [~] 23. Update GUI, Telegram, and CLI for notification delivery
  - [~] 23.1 Add NotificationRouter integration to all interfaces
    - Update GUI to receive notifications from NotificationRouter
    - Update Telegram bot to receive notifications from NotificationRouter
    - Update CLI to receive notifications from NotificationRouter
    - Implement rich text formatting for GUI
    - Implement plain text formatting for Telegram and CLI
    - _Requirements: 12.2, 12.6_
  
  - [~] 23.2 Write unit tests for notification formatting
    - Test GUI rich text formatting
    - Test Telegram plain text formatting
    - Test CLI plain text formatting
    - _Requirements: 12.6_

- [~] 24. Add Class C approval UI to all interfaces
  - [~] 24.1 Implement approval UI for Class C actions
    - Add modal dialog with approve/reject buttons to GUI
    - Add inline keyboard with ✅/❌ buttons to Telegram
    - Add y/n prompt to CLI
    - Wire approval responses back to AutoExecutor
    - _Requirements: 8.6_
  
  - [~] 24.2 Write integration tests for approval UI
    - Test GUI modal interaction
    - Test Telegram inline keyboard interaction
    - Test CLI prompt interaction
    - _Requirements: 8.6_

- [~] 25. Final checkpoint - End-to-end testing
  - [~] 25.1 Run end-to-end tests
    - Test morning briefing delivery on first boot
    - Test intent model generation and injection
    - Test behavioral pattern learning and analysis
    - Test anticipatory action pre-execution and caching
    - Test priority-based notification routing
    - Test conversational proactive appending
    - Test autonomous action execution (Class A/B/C)
    - Test environment management based on focus mode
    - Test deadline cascade prediction
    - Test cross-agent insight synthesis
    - Verify state persistence across restarts
    - _Requirements: All requirements_
  
  - [~] 25.2 Write property test for end-to-end workflow
    - **Property 14: End-to-End Workflow Correctness**
    - **Validates: All requirements**

- [~] 26. Documentation and deployment
  - [~] 26.1 Update documentation
    - Document new environment variables (ANKITA_DND_HOURS)
    - Document state file locations and formats
    - Document Class A/B/C action classification
    - Update README with proactive system overview
    - _Requirements: All requirements_
  
  - [~] 26.2 Create migration guide
    - Document state file initialization
    - Document backward compatibility considerations
    - Document rollback procedures
    - _Requirements: All requirements_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at tier boundaries
- Property tests validate universal correctness properties across all inputs
- Unit tests validate specific examples, edge cases, and error conditions
- The implementation follows a bottom-up approach: infrastructure first, then intelligence layers
- All components integrate through the ProactiveEngine central coordinator
- State persistence ensures continuity across system restarts
- The system maintains backward compatibility with existing ANKITA components
