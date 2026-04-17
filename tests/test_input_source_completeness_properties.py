"""
Property-based tests for Input Source Completeness

Tests that components requiring multiple data sources query all required
sources before processing. Uses Hypothesis for property-based testing.

**Property 4: Input Source Completeness**
**Validates: Requirements 2.2, 5.2, 7.3, 11.2**
"""
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Set
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from tools.intention_engine import IntentionEngine


# ============================================================================
# Strategies for generating test scenarios
# ============================================================================

@st.composite
def component_scenario(draw):
    """
    Generate a test scenario for a component that requires multiple data sources.
    
    Returns a tuple of (component_name, required_sources, mock_config)
    """
    # For now, we focus on IntentionEngine as it's the only implemented component
    # that requires multiple data sources
    component = "IntentionEngine"
    
    # Required sources for IntentionEngine per Requirement 2.2
    required_sources = [
        "chromadb_memories",
        "pending_tasks",
        "cron_jobs_24h",
        "recent_git_commits",
        "watchdog_states",
    ]
    
    # Generate mock configuration for each source
    mock_config = {
        "chromadb_enabled": draw(st.booleans()),
        "tasks_available": draw(st.booleans()),
        "cron_available": draw(st.booleans()),
        "git_available": draw(st.booleans()),
        "watchdog_available": draw(st.booleans()),
    }
    
    return (component, required_sources, mock_config)


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# ============================================================================
# Property Tests
# ============================================================================

@given(scenario=component_scenario())
@settings(deadline=None)  # Disable deadline for this test due to mocking overhead
def test_property_intention_engine_queries_all_sources(scenario):
    """
    **Property 4: Input Source Completeness (IntentionEngine)**
    
    For any IntentionEngine execution, all required data sources SHALL be
    queried before processing, regardless of whether the sources return data.
    
    **Validates: Requirements 2.2**
    
    Required sources for IntentionEngine:
    - ChromaDB memory entries (last 30)
    - Pending tasks from task_ops
    - Cron jobs for next 24 hours
    - Recent git commits (last 10)
    - Watchdog states
    
    This property ensures that:
    1. All required sources are attempted (even if they fail)
    2. The context dictionary contains all required keys
    3. Each source is queried exactly once per execution
    4. Missing or failing sources result in empty collections, not missing keys
    """
    component_name, required_sources, mock_config = scenario
    
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        engine = IntentionEngine(workspace)
        
                # Track which sources were queried
        queried_sources: Set[str] = set()
        
        # Mock all external dependencies and track calls
        with patch("memory.MemoryStore", create=True) as mock_memory:
            with patch("tools.task_ops.task_op") as mock_task_op:
                with patch.object(IntentionEngine, "_load_scheduled_jobs") as mock_load_store:
                    with patch("subprocess.run") as mock_subprocess:
                        with patch("watchdog_manager.get_instance", create=True) as mock_get_instance:
                            
                            # Setup mocks to track queries
                            def track_memory(*args, **kwargs):
                                queried_sources.add("chromadb_memories")
                                mock_store = MagicMock()
                                mock_store.enabled = mock_config["chromadb_enabled"]
                                if mock_config["chromadb_enabled"]:
                                    mock_store._col.get.return_value = {
                                        "documents": ["test doc"],
                                        "metadatas": [{"role": "user", "ts": 1234567890}],
                                    }
                                return mock_store
                            
                            def track_task_op(*args, **kwargs):
                                # Note: pending_tasks is queried twice (pending + in_progress)
                                # but we only track it once as a single source
                                queried_sources.add("pending_tasks")
                                if mock_config["tasks_available"]:
                                    return {"status": "success", "tasks": [{"title": "test task"}]}
                                return {"status": "error", "tasks": []}
                            
                            def track_load_store(*args, **kwargs):
                                queried_sources.add("cron_jobs_24h")
                                if mock_config["cron_available"]:
                                    return {"jobs": [{"name": "test job", "enabled": True}]}
                                return {"jobs": []}
                            
                            def track_subprocess(*args, **kwargs):
                                queried_sources.add("recent_git_commits")
                                result = MagicMock()
                                if mock_config["git_available"]:
                                    result.returncode = 0
                                    result.stdout = "abc123 Test commit\n"
                                else:
                                    result.returncode = 1
                                    result.stdout = ""
                                return result
                            
                            def track_watchdog(*args, **kwargs):
                                queried_sources.add("watchdog_states")
                                if mock_config["watchdog_available"]:
                                    mgr = MagicMock()
                                    mgr._watchers = {"test_watcher": MagicMock()}
                                    return mgr
                                return None
                            
                            # Assign tracking functions
                            mock_memory.side_effect = track_memory
                            mock_task_op.side_effect = track_task_op
                            mock_load_store.side_effect = track_load_store
                            mock_subprocess.side_effect = track_subprocess
                            mock_get_instance.side_effect = track_watchdog
                            
                            # Execute _gather_context
                            context = engine._gather_context()
        
        # Verify all required sources were queried
        assert queried_sources == set(required_sources), (
            f"Not all required sources were queried!\n"
            f"Required: {set(required_sources)}\n"
            f"Queried: {queried_sources}\n"
            f"Missing: {set(required_sources) - queried_sources}"
        )
        
        # Verify context contains all required keys
        for source in required_sources:
            assert source in context, (
                f"Required source '{source}' is missing from context!\n"
                f"Context keys: {list(context.keys())}"
            )
        
        # Verify each source has the correct type (list or dict)
        list_sources = ["chromadb_memories", "pending_tasks", "cron_jobs_24h", "recent_git_commits"]
        dict_sources = ["watchdog_states"]
        
        for source in list_sources:
            assert isinstance(context[source], list), (
                f"Source '{source}' should be a list, got {type(context[source])}"
            )
        
        for source in dict_sources:
            assert isinstance(context[source], dict), (
                f"Source '{source}' should be a dict, got {type(context[source])}"
            )
        
        # Verify timestamp is present
        assert "timestamp" in context, "Context should include a timestamp"


@given(
    num_failures=st.integers(min_value=0, max_value=5),
    failure_indices=st.lists(st.integers(min_value=0, max_value=4), max_size=5, unique=True),
)
@settings(deadline=None)  # Disable deadline for this test due to mocking overhead
def test_property_intention_engine_handles_source_failures(num_failures: int, failure_indices: List[int]):
    """
    Property: IntentionEngine handles source failures gracefully.
    
    For any combination of source failures, the IntentionEngine should:
    1. Still query all sources (not short-circuit on first failure)
    2. Return a context with all required keys
    3. Use empty collections for failed sources
    4. Not raise exceptions during context gathering
    
    **Validates: Requirements 2.2**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        engine = IntentionEngine(workspace)
        
                # Limit failure_indices to num_failures
        actual_failures = failure_indices[:num_failures]
        
        # Track which sources were queried
        queried_sources: Set[str] = set()
        
        # Mock all external dependencies with controlled failures
        with patch("memory.MemoryStore", create=True) as mock_memory:
            with patch("tools.task_ops.task_op") as mock_task_op:
                with patch.object(IntentionEngine, "_load_scheduled_jobs") as mock_load_store:
                    with patch("subprocess.run") as mock_subprocess:
                        with patch("watchdog_manager.get_instance", create=True) as mock_get_instance:
                            
                            # Setup mocks with potential failures
                            def track_memory(*args, **kwargs):
                                queried_sources.add("chromadb_memories")
                                if 0 in actual_failures:
                                    raise Exception("ChromaDB connection failed")
                                mock_store = MagicMock()
                                mock_store.enabled = True
                                mock_store._col.get.return_value = {
                                    "documents": ["test"],
                                    "metadatas": [{"role": "user", "ts": 123}],
                                }
                                return mock_store
                            
                            def track_task_op(*args, **kwargs):
                                queried_sources.add("pending_tasks")
                                if 1 in actual_failures:
                                    raise Exception("Task ops failed")
                                return {"status": "success", "tasks": []}
                            
                            def track_load_store(*args, **kwargs):
                                queried_sources.add("cron_jobs_24h")
                                if 2 in actual_failures:
                                    raise Exception("Cron store failed")
                                return {"jobs": []}
                            
                            def track_subprocess(*args, **kwargs):
                                queried_sources.add("recent_git_commits")
                                if 3 in actual_failures:
                                    raise Exception("Git command failed")
                                result = MagicMock()
                                result.returncode = 0
                                result.stdout = "abc123 Test\n"
                                return result
                            
                            def track_watchdog(*args, **kwargs):
                                queried_sources.add("watchdog_states")
                                if 4 in actual_failures:
                                    raise Exception("Watchdog manager failed")
                                return None
                            
                            # Assign tracking functions
                            mock_memory.side_effect = track_memory
                            mock_task_op.side_effect = track_task_op
                            mock_load_store.side_effect = track_load_store
                            mock_subprocess.side_effect = track_subprocess
                            mock_get_instance.side_effect = track_watchdog
                            
                            # Execute _gather_context (should not raise)
                            try:
                                context = engine._gather_context()
                            except Exception as e:
                                pytest.fail(f"_gather_context should not raise exceptions, got: {e}")
        
        # Verify all sources were attempted despite failures
        required_sources = {
            "chromadb_memories",
            "pending_tasks",
            "cron_jobs_24h",
            "recent_git_commits",
            "watchdog_states",
        }
        
        assert queried_sources == required_sources, (
            f"Not all sources were attempted despite failures!\n"
            f"Required: {required_sources}\n"
            f"Queried: {queried_sources}\n"
            f"Missing: {required_sources - queried_sources}"
        )
        
        # Verify context contains all required keys (even for failed sources)
        for source in required_sources:
            assert source in context, (
                f"Required source '{source}' is missing from context after failure!\n"
                f"Context keys: {list(context.keys())}"
            )
        
        # Verify failed sources have empty collections
        source_names = [
            "chromadb_memories",
            "pending_tasks",
            "cron_jobs_24h",
            "recent_git_commits",
            "watchdog_states",
        ]
        
        for idx in actual_failures:
            if idx < len(source_names):
                source = source_names[idx]
                if source == "watchdog_states":
                    # Dict source should be empty dict
                    assert context[source] == {}, (
                        f"Failed source '{source}' should be empty dict, got: {context[source]}"
                    )
                else:
                    # List sources should be empty list
                    assert context[source] == [], (
                        f"Failed source '{source}' should be empty list, got: {context[source]}"
                    )


def test_property_intention_engine_queries_sources_once():
    """
    Property: IntentionEngine queries each source exactly once per execution.
    
    For any single execution of _gather_context, each data source should be
    queried exactly once (no duplicate queries, no skipped queries).
    
    **Validates: Requirements 2.2**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        engine = IntentionEngine(workspace)
        
                # Track call counts for each source
        call_counts: Dict[str, int] = {
            "chromadb_memories": 0,
            "pending_tasks": 0,
            "cron_jobs_24h": 0,
            "recent_git_commits": 0,
            "watchdog_states": 0,
        }
        
        # Mock all external dependencies and count calls
        with patch("memory.MemoryStore", create=True) as mock_memory:
            with patch("tools.task_ops.task_op") as mock_task_op:
                with patch.object(IntentionEngine, "_load_scheduled_jobs") as mock_load_store:
                    with patch("subprocess.run") as mock_subprocess:
                        with patch("watchdog_manager.get_instance", create=True) as mock_get_instance:
                            
                            # Setup mocks to count calls
                            def count_memory(*args, **kwargs):
                                call_counts["chromadb_memories"] += 1
                                mock_store = MagicMock()
                                mock_store.enabled = False
                                return mock_store
                            
                            def count_task_op(*args, **kwargs):
                                # Note: task_op is called twice (pending + in_progress)
                                # We count this as one logical query of the pending_tasks source
                                call_counts["pending_tasks"] += 1
                                return {"status": "success", "tasks": []}
                            
                            def count_load_store(*args, **kwargs):
                                call_counts["cron_jobs_24h"] += 1
                                return {"jobs": []}
                            
                            def count_subprocess(*args, **kwargs):
                                call_counts["recent_git_commits"] += 1
                                result = MagicMock()
                                result.returncode = 1
                                result.stdout = ""
                                return result
                            
                            def count_watchdog(*args, **kwargs):
                                call_counts["watchdog_states"] += 1
                                return None
                            
                            # Assign counting functions
                            mock_memory.side_effect = count_memory
                            mock_task_op.side_effect = count_task_op
                            mock_load_store.side_effect = count_load_store
                            mock_subprocess.side_effect = count_subprocess
                            mock_get_instance.side_effect = count_watchdog
                            
                            # Execute _gather_context
                            context = engine._gather_context()
        
        # Verify each source was queried at least once
        # Note: pending_tasks is queried twice (pending + in_progress) which is expected
        for source, count in call_counts.items():
            if source == "pending_tasks":
                assert count == 2, (
                    f"Source '{source}' should be queried twice (pending + in_progress), "
                    f"but was queried {count} times"
                )
            else:
                assert count == 1, (
                    f"Source '{source}' should be queried exactly once, "
                    f"but was queried {count} times"
                )


@given(
    num_executions=st.integers(min_value=1, max_value=5),
)
@settings(deadline=None)  # Disable deadline for this test due to mocking overhead
def test_property_intention_engine_consistent_across_executions(num_executions: int):
    """
    Property: IntentionEngine queries all sources consistently across multiple executions.
    
    For any number of sequential executions, each execution should query all
    required sources independently (no caching or state leakage between executions).
    
    **Validates: Requirements 2.2**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        engine = IntentionEngine(workspace)
        
                # Track queries across all executions
        all_queries: List[Set[str]] = []
        
        for execution_num in range(num_executions):
            queried_sources: Set[str] = set()
            
            # Mock all external dependencies
            with patch("memory.MemoryStore", create=True) as mock_memory:
                with patch("tools.task_ops.task_op") as mock_task_op:
                    with patch.object(IntentionEngine, "_load_scheduled_jobs") as mock_load_store:
                        with patch("subprocess.run") as mock_subprocess:
                            with patch("watchdog_manager.get_instance", create=True) as mock_get_instance:
                                
                                # Setup mocks to track queries
                                def track_memory(*args, **kwargs):
                                    queried_sources.add("chromadb_memories")
                                    mock_store = MagicMock()
                                    mock_store.enabled = False
                                    return mock_store
                                
                                def track_task_op(*args, **kwargs):
                                    queried_sources.add("pending_tasks")
                                    return {"status": "success", "tasks": []}
                                
                                def track_load_store(*args, **kwargs):
                                    queried_sources.add("cron_jobs_24h")
                                    return {"jobs": []}
                                
                                def track_subprocess(*args, **kwargs):
                                    queried_sources.add("recent_git_commits")
                                    result = MagicMock()
                                    result.returncode = 1
                                    result.stdout = ""
                                    return result
                                
                                def track_watchdog(*args, **kwargs):
                                    queried_sources.add("watchdog_states")
                                    return None
                                
                                # Assign tracking functions
                                mock_memory.side_effect = track_memory
                                mock_task_op.side_effect = track_task_op
                                mock_load_store.side_effect = track_load_store
                                mock_subprocess.side_effect = track_subprocess
                                mock_get_instance.side_effect = track_watchdog
                                
                                # Execute _gather_context
                                context = engine._gather_context()
            
            all_queries.append(queried_sources.copy())
        
        # Verify all executions queried the same sources
        required_sources = {
            "chromadb_memories",
            "pending_tasks",
            "cron_jobs_24h",
            "recent_git_commits",
            "watchdog_states",
        }
        
        for execution_num, queried in enumerate(all_queries):
            assert queried == required_sources, (
                f"Execution {execution_num + 1} did not query all required sources!\n"
                f"Required: {required_sources}\n"
                f"Queried: {queried}\n"
                f"Missing: {required_sources - queried}"
            )


# ============================================================================
# Future Component Tests (Placeholders)
# ============================================================================

def test_property_morning_agent_queries_all_sources():
    """
    **Property 4: Input Source Completeness (MorningAgent)**
    
    For any MorningAgent execution, all required data sources SHALL be
    queried before composing the morning briefing.
    
    **Validates: Requirements 5.2**
    
    Required sources for MorningAgent:
    - intent.json (daily intent model)
    - Pending tasks from task_ops
    - Watchdog states
    - System health from system_ops
    - Cron jobs for today
    
    NOTE: This test is a placeholder. MorningAgent is not yet implemented.
    """
    pytest.skip("MorningAgent not yet implemented")


def test_property_conversational_proactive_queries_all_sources():
    """
    **Property 4: Input Source Completeness (ConversationalProactive)**
    
    For any ConversationalProactive micro-check, all required data sources
    SHALL be queried before appending proactive information.
    
    **Validates: Requirements 7.3**
    
    Required sources for ConversationalProactive:
    - Pending high-priority watchdog alerts
    - Task deadlines within 2 hours
    - Natural follow-ups from intent.json
    
    NOTE: This test is a placeholder. ConversationalProactive is not yet implemented.
    """
    pytest.skip("ConversationalProactive not yet implemented")


def test_property_insight_synthesizer_queries_all_sources():
    """
    **Property 4: Input Source Completeness (InsightSynthesizer)**
    
    For any InsightSynthesizer execution, all required agent outputs SHALL
    be queried before synthesizing insights.
    
    **Validates: Requirements 11.2**
    
    Required sources for InsightSynthesizer:
    - Recent outputs from CodeAgent (last 12hrs)
    - Recent outputs from WebAgent (last 12hrs)
    - Recent outputs from TaskAgent (last 12hrs)
    - Recent outputs from WatchdogAgent (last 12hrs)
    
    NOTE: This test is a placeholder. InsightSynthesizer is not yet implemented.
    """
    pytest.skip("InsightSynthesizer not yet implemented")
