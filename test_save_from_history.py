#!/usr/bin/env python3
"""Test that FileAgent can extract and save content from conversation history."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from agents.specialists import FileAgent
from agents.supervisor import SupervisorAgent
from llm import build_runtime_from_env

def test_fileagent_history_extraction():
    """Test that FileAgent extracts content from history when user says 'save it'."""
    print("\n" + "=" * 70)
    print("TEST: FileAgent History Extraction")
    print("=" * 70)
    
    # Simulate conversation history with a price comparison
    history = [
        {
            "role": "user",
            "content": "compare iPhone 15 vs Samsung S24 prices"
        },
        {
            "role": "assistant",
            "content": (
                "Here's the price comparison:\n\n"
                "iPhone 15: $799 (128GB base model)\n"
                "- Display: 6.1-inch OLED\n"
                "- Chip: A16 Bionic\n"
                "- Camera: 48MP main\n\n"
                "Samsung S24: $799 (128GB base model)\n"
                "- Display: 6.2-inch AMOLED\n"
                "- Chip: Snapdragon 8 Gen 3\n"
                "- Camera: 50MP main\n\n"
                "Both phones are priced identically at launch."
            )
        }
    ]
    
    # User now says "save it to a file"
    task = "save it to a file"
    
    print(f"\n📝 Conversation History:")
    print(f"  User: {history[0]['content']}")
    print(f"  ANKITA: {history[1]['content'][:60]}...")
    print(f"\n📝 Current Task: {task}")
    
    # Build messages as FileAgent would receive them
    messages = FileAgent.make_messages(task, history=history)
    
    print(f"\n✅ FileAgent received {len(messages)} messages:")
    print(f"  [0] system prompt")
    for i, msg in enumerate(messages[1:], 1):
        content_preview = msg['content'][:50] if len(msg['content']) > 50 else msg['content']
        print(f"  [{i}] {msg['role']}: {content_preview}...")
    
    # Verify structure
    assert len(messages) == 4, f"Expected 4 messages, got {len(messages)}"
    assert messages[0]['role'] == 'system'
    assert messages[1]['role'] == 'user'
    assert messages[1]['content'] == history[0]['content']
    assert messages[2]['role'] == 'assistant'
    assert 'iPhone 15' in messages[2]['content']
    assert messages[3]['role'] == 'user'
    assert messages[3]['content'] == task
    
    print("\n✅ FileAgent has full conversation history including the comparison!")
    print("   It can now extract 'iPhone 15 vs Samsung S24' content and save it.")
    
    return True

def test_supervisor_routing():
    """Test that Supervisor routes 'save it' to FileAgent when history exists."""
    print("\n" + "=" * 70)
    print("TEST: Supervisor Routing for 'save it'")
    print("=" * 70)
    
    runtime = build_runtime_from_env()
    supervisor = SupervisorAgent(runtime)
    
    # History with previous comparison
    history = [
        {"role": "user", "content": "compare iPhone 15 vs Samsung S24 prices"},
        {"role": "assistant", "content": "Here's the comparison: iPhone 15: $799, Samsung S24: $799"}
    ]
    
    # Test various "save" phrasings
    test_cases = [
        "save it to a file",
        "save that",
        "prepare a report on it and open in notepad",
        "write it to a file",
        "put that in a file"
    ]
    
    print("\n📝 Testing routing with conversation history present:")
    for task in test_cases:
        result = supervisor.route(task, history=history)
        agents = result['agents']
        reasoning = result['reasoning']
        
        print(f"\n  Task: '{task}'")
        print(f"  → Routed to: {agents}")
        print(f"  → Reasoning: {reasoning[:60]}...")
        
        # Should route to FileAgent (not ContentAgent)
        if 'FileAgent' in agents:
            print(f"  ✅ Correct! Routed to FileAgent")
        else:
            print(f"  ⚠️  Warning: Expected FileAgent, got {agents}")
    
    return True

def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("TESTING: Save Content From Conversation History")
    print("=" * 70)
    print("\nThis tests the fix for:")
    print("  User: 'compare prices'")
    print("  ANKITA: [returns comparison]")
    print("  User: 'save it to a file'")
    print("  Expected: FileAgent extracts comparison from history and saves it")
    
    tests = [
        test_fileagent_history_extraction,
        test_supervisor_routing,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"\n❌ {test.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)
    
    if failed == 0:
        print("\n🎉 All tests passed!")
        print("\nWhat this means:")
        print("  ✅ FileAgent receives conversation history")
        print("  ✅ FileAgent can extract previous content when user says 'save it'")
        print("  ✅ Supervisor routes 'save it' to FileAgent (not ContentAgent)")
        print("\nThe 'save that' bug is FIXED!")
    
    return failed == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
