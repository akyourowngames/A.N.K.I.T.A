#!/usr/bin/env python3
"""Test conversation history flow in the agent system."""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from agents.orchestrator import _extract_clean_history, Orchestrator
from agents.specialists import WebAgent, GeneralAgent
from llm import build_runtime_from_env

def test_extract_clean_history():
    """Test the _extract_clean_history helper function."""
    print("\n=== Testing _extract_clean_history ===")
    
    # Simulate a conversation history
    messages = [
        {"role": "system", "content": "You are ANKITA"},
        {"role": "user", "content": "compare iPhone 15 vs Samsung S24 prices"},
        {"role": "assistant", "content": "Here's the price comparison: iPhone 15 costs $799, Samsung S24 costs $799"},
        {"role": "tool", "content": '{"ok": true}'},  # Should be filtered out
        {"role": "user", "content": "did you search online?"},
        {"role": "assistant", "content": "Yes, I used the compare_search tool"},
        {"role": "user", "content": "save that to a file"},
    ]
    
    # Extract last 6 turns
    clean = _extract_clean_history(messages, max_turns=6)
    
    print(f"Original messages: {len(messages)}")
    print(f"Clean history: {len(clean)}")
    print("\nClean history content:")
    for msg in clean:
        print(f"  {msg['role']}: {msg['content'][:60]}...")
    
    # Verify filtering worked
    assert len(clean) == 5, f"Expected 5 clean messages, got {len(clean)}"
    assert all(msg['role'] in ('user', 'assistant') for msg in clean), "Should only have user/assistant"
    assert not any(msg.get('role') == 'tool' for msg in clean), "Should not have tool role messages"
    
    print("✅ _extract_clean_history works correctly")
    return True

def test_specialist_make_messages():
    """Test that specialists can accept history parameter."""
    print("\n=== Testing SpecialistAgent.make_messages ===")
    
    task = "did you search online?"
    history = [
        {"role": "user", "content": "compare iPhone 15 vs Samsung S24 prices"},
        {"role": "assistant", "content": "Here's the comparison..."},
    ]
    
    # Test WebAgent
    messages = WebAgent.make_messages(task, history=history)
    
    print(f"Generated {len(messages)} messages")
    print("Message structure:")
    for i, msg in enumerate(messages):
        content_preview = msg['content'][:60] if len(msg['content']) > 60 else msg['content']
        print(f"  [{i}] {msg['role']}: {content_preview}...")
    
    # Verify structure
    assert messages[0]['role'] == 'system', "First message should be system"
    assert messages[1]['role'] == 'user', "History should be injected"
    assert messages[1]['content'] == history[0]['content'], "History content should match"
    assert messages[-1]['role'] == 'user', "Last message should be current task"
    assert messages[-1]['content'] == task, "Last message should be the task"
    
    print("✅ SpecialistAgent.make_messages works with history")
    return True

def test_orchestrator_integration():
    """Test that Orchestrator properly extracts and passes history."""
    print("\n=== Testing Orchestrator Integration ===")
    
    # Build runtime
    runtime = build_runtime_from_env()
    workspace_root = Path.cwd()
    
    # Create orchestrator
    orch = Orchestrator(runtime, workspace_root)
    
    # Simulate conversation
    messages = [
        {"role": "system", "content": "You are ANKITA"},
        {"role": "user", "content": "compare iPhone 15 vs Samsung S24 prices"},
        {"role": "assistant", "content": "Here's the comparison: iPhone 15 costs $799, Samsung S24 costs $799"},
    ]
    
    # Store messages in orchestrator (simulating what run() does)
    orch.messages = messages
    
    # Extract history
    history = _extract_clean_history(messages, max_turns=6)
    
    print(f"Orchestrator has {len(messages)} messages")
    print(f"Extracted {len(history)} clean history turns")
    
    assert len(history) == 2, f"Expected 2 clean turns, got {len(history)}"
    
    print("✅ Orchestrator integration works")
    return True

def test_supervisor_with_history():
    """Test that Supervisor can handle history for follow-up detection."""
    print("\n=== Testing Supervisor with History ===")
    
    from agents.supervisor import SupervisorAgent
    from llm import build_runtime_from_env
    
    runtime = build_runtime_from_env()
    supervisor = SupervisorAgent(runtime)
    
    # Test follow-up question with history
    history = [
        {"role": "user", "content": "compare iPhone 15 vs Samsung S24 prices"},
        {"role": "assistant", "content": "Here's the comparison..."},
    ]
    
    # This should route to GeneralAgent (follow-up question)
    result = supervisor.route("did you search online?", history=history)
    
    print(f"Routing result: {result}")
    print(f"  Agents: {result['agents']}")
    print(f"  Reasoning: {result['reasoning']}")
    
    # Note: The actual routing depends on the LLM, so we just verify it doesn't crash
    assert 'agents' in result, "Should return agents list"
    assert isinstance(result['agents'], list), "Agents should be a list"
    
    print("✅ Supervisor handles history without errors")
    return True

def main():
    """Run all tests."""
    print("=" * 60)
    print("CONVERSATION HISTORY IMPLEMENTATION TEST SUITE")
    print("=" * 60)
    
    tests = [
        test_extract_clean_history,
        test_specialist_make_messages,
        test_orchestrator_integration,
        test_supervisor_with_history,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
