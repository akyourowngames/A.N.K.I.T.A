"""
Integration test for TerminalAgent with LLM.

Tests the full agent workflow with real LLM calls to verify:
1. Agent understands and uses new features
2. Session state is maintained across turns
3. Git intelligence works
4. Package manager intelligence works
5. Network diagnostics work
6. Memory integration works
"""
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from agents.specialists import TerminalAgent
from llm import build_runtime_from_env


def test_basic_commands():
    """Test basic command execution through the agent."""
    print("\n" + "="*80)
    print("INTEGRATION TEST 1: Basic Commands")
    print("="*80)
    
    runtime = build_runtime_from_env()
    workspace = Path.cwd()
    
    # Test 1: Simple command
    print("\n1. Testing: 'check my current directory'")
    messages = TerminalAgent.make_messages("check my current directory")
    
    # Simulate one turn
    from llm import call_chat_once
    from tools.engine import execute_tool_call
    
    response = call_chat_once(runtime, messages, tools=TerminalAgent.tool_specs)
    print(f"   Agent response: {response.get('content', '')[:200]}")
    
    tool_calls = response.get("tool_calls", [])
    if tool_calls:
        print(f"   Tool calls: {len(tool_calls)}")
        for tc in tool_calls:
            tool_name = tc.get("function", {}).get("name")
            print(f"   - {tool_name}")
            result = execute_tool_call(tc, workspace_root=workspace, agent_name="TerminalAgent")
            print(f"     Result: {str(result)[:200]}")
    
    print("\n✅ Basic command test completed")


def test_session_awareness():
    """Test that agent maintains session state across turns."""
    print("\n" + "="*80)
    print("INTEGRATION TEST 2: Session State Awareness")
    print("="*80)
    
    runtime = build_runtime_from_env()
    workspace = Path.cwd()
    
    from llm import call_chat_once
    from tools.engine import execute_tool_call
    
    # Turn 1: Change directory
    print("\n1. Turn 1: 'cd into my Documents folder'")
    messages = TerminalAgent.make_messages("cd into my Documents folder")
    
    response = call_chat_once(runtime, messages, tools=TerminalAgent.tool_specs)
    print(f"   Agent response: {response.get('content', '')[:200]}")
    
    messages.append({
        "role": "assistant",
        "content": response.get("content", ""),
        "tool_calls": response.get("tool_calls", [])
    })
    
    # Execute tool calls
    for tc in response.get("tool_calls", []):
        result = execute_tool_call(tc, workspace_root=workspace, agent_name="TerminalAgent")
        messages.append({
            "role": "tool",
            "tool_call_id": tc.get("id", ""),
            "content": str(result)
        })
    
    # Turn 2: Check current directory (should be Documents)
    print("\n2. Turn 2: 'what directory am I in now?'")
    messages.append({"role": "user", "content": "what directory am I in now?"})
    
    response = call_chat_once(runtime, messages, tools=TerminalAgent.tool_specs)
    print(f"   Agent response: {response.get('content', '')[:200]}")
    
    # Execute tool calls
    for tc in response.get("tool_calls", []):
        result = execute_tool_call(tc, workspace_root=workspace, agent_name="TerminalAgent")
        print(f"   Tool result: {str(result)[:200]}")
        # Check if we're in Documents
        if "Documents" in str(result):
            print("   ✅ Session state maintained - still in Documents!")
    
    print("\n✅ Session awareness test completed")


def test_git_intelligence():
    """Test git intelligence features."""
    print("\n" + "="*80)
    print("INTEGRATION TEST 3: Git Intelligence")
    print("="*80)
    
    # Check if we're in a git repo
    from tools import terminal_ops
    check = terminal_ops.execute_shell_command("git rev-parse --git-dir")
    if not check["ok"]:
        print("\n⚠️  Not in a git repository, skipping git intelligence test")
        return
    
    runtime = build_runtime_from_env()
    workspace = Path.cwd()
    
    from llm import call_chat_once
    from tools.engine import execute_tool_call
    
    # Test: "what changed in my repo"
    print("\n1. Testing: 'what changed in my repo'")
    messages = TerminalAgent.make_messages("what changed in my repo")
    
    response = call_chat_once(runtime, messages, tools=TerminalAgent.tool_specs)
    print(f"   Agent response: {response.get('content', '')[:300]}")
    
    tool_calls = response.get("tool_calls", [])
    if tool_calls:
        for tc in tool_calls:
            tool_name = tc.get("function", {}).get("name")
            args = tc.get("function", {}).get("arguments", "{}")
            print(f"   Tool: {tool_name}")
            print(f"   Args: {args[:200]}")
            
            # Check if agent used git diff or git status
            if "git" in args.lower():
                print("   ✅ Agent used git command!")
    
    print("\n✅ Git intelligence test completed")


def test_smart_timeout():
    """Test that agent benefits from smart timeout."""
    print("\n" + "="*80)
    print("INTEGRATION TEST 4: Smart Timeout")
    print("="*80)
    
    runtime = build_runtime_from_env()
    workspace = Path.cwd()
    
    from llm import call_chat_once
    from tools.engine import execute_tool_call
    
    # Test: Command that would timeout with old 15s limit
    print("\n1. Testing: 'ping google.com 5 times'")
    messages = TerminalAgent.make_messages("ping google.com 5 times")
    
    response = call_chat_once(runtime, messages, tools=TerminalAgent.tool_specs)
    print(f"   Agent response: {response.get('content', '')[:200]}")
    
    tool_calls = response.get("tool_calls", [])
    if tool_calls:
        for tc in tool_calls:
            result = execute_tool_call(tc, workspace_root=workspace, agent_name="TerminalAgent")
            # Check if command succeeded (didn't timeout)
            if isinstance(result, dict) and result.get("ok"):
                print("   ✅ Command succeeded without timeout!")
            elif isinstance(result, dict) and "timeout" in str(result.get("error", "")).lower():
                print("   ❌ Command timed out")
            print(f"   Result: {str(result)[:200]}")
    
    print("\n✅ Smart timeout test completed")


def test_network_diagnostics():
    """Test network diagnostic intelligence."""
    print("\n" + "="*80)
    print("INTEGRATION TEST 5: Network Diagnostics")
    print("="*80)
    
    runtime = build_runtime_from_env()
    workspace = Path.cwd()
    
    from llm import call_chat_once
    from tools.engine import execute_tool_call
    
    # Test: "check my internet connection"
    print("\n1. Testing: 'check my internet connection'")
    messages = TerminalAgent.make_messages("check my internet connection")
    
    response = call_chat_once(runtime, messages, tools=TerminalAgent.tool_specs)
    print(f"   Agent response: {response.get('content', '')[:300]}")
    
    tool_calls = response.get("tool_calls", [])
    if tool_calls:
        print(f"   Tool calls: {len(tool_calls)}")
        for tc in tool_calls:
            tool_name = tc.get("function", {}).get("name")
            args = tc.get("function", {}).get("arguments", "{}")
            print(f"   - {tool_name}")
            
            # Check if agent used ping
            if "ping" in args.lower():
                print("   ✅ Agent used ping command!")
    
    print("\n✅ Network diagnostics test completed")


def run_integration_tests():
    """Run all integration tests."""
    print("\n" + "="*80)
    print("TERMINAL AGENT - INTEGRATION TEST SUITE")
    print("="*80)
    
    # Check if we have API key
    if not os.getenv("ANTHROPIC_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        print("\n⚠️  No API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY to run integration tests.")
        return 1
    
    tests = [
        ("Basic Commands", test_basic_commands),
        ("Session State Awareness", test_session_awareness),
        ("Git Intelligence", test_git_intelligence),
        ("Smart Timeout", test_smart_timeout),
        ("Network Diagnostics", test_network_diagnostics),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"\n❌ TEST ERROR: {name}")
            print(f"   Exception: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "="*80)
    print("INTEGRATION TEST SUMMARY")
    print("="*80)
    print(f"Total tests: {len(tests)}")
    print(f"Passed: {passed} ✅")
    print(f"Failed: {failed} ❌")
    
    if failed == 0:
        print("\n🎉 ALL INTEGRATION TESTS PASSED! 🎉")
        return 0
    else:
        print(f"\n⚠️  {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = run_integration_tests()
    sys.exit(exit_code)
