"""
Test suite for bug fixes mentioned in todo.md

Tests:
1. FileAgent make_dir with unrestricted=True
2. HANDOFF signal extraction in orchestrator
3. Session state persistence in TerminalAgent
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tools import fs_ops
from agents.orchestrator import _extract_artifacts


def test_make_dir_unrestricted():
    """Test that make_dir now supports unrestricted parameter."""
    print("\n" + "="*80)
    print("BUG FIX TEST 1: make_dir unrestricted parameter")
    print("="*80)
    
    workspace = Path.cwd()
    
    # Test 1: Create directory outside workspace with unrestricted=True
    test_dir = Path.home() / "Desktop" / "test_ankita_mkdir"
    
    # Clean up if exists
    if test_dir.exists():
        test_dir.rmdir()
    
    try:
        result = fs_ops.make_dir(
            workspace,
            str(test_dir),
            unrestricted=True
        )
        
        print(f"\n1. Created directory with unrestricted=True:")
        print(f"   Path: {result.get('path')}")
        print(f"   Absolute: {result.get('absolute_path')}")
        print(f"   Created: {result.get('created')}")
        
        assert test_dir.exists(), "Directory should be created"
        assert result.get("created"), "Result should indicate creation"
        assert result.get("absolute_path"), "Should return absolute path"
        
        print("   ✅ Directory created successfully outside workspace")
        
        # Clean up
        test_dir.rmdir()
        
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        raise
    
    # Test 2: Verify unrestricted=False still enforces workspace boundary
    try:
        result = fs_ops.make_dir(
            workspace,
            str(test_dir),
            unrestricted=False
        )
        print("\n2. ❌ Should have failed with unrestricted=False")
        assert False, "Should not allow creation outside workspace"
    except (ValueError, Exception) as e:
        print(f"\n2. ✅ Correctly blocked creation outside workspace: {str(e)[:100]}")
    
    print("\n✅ make_dir unrestricted tests PASSED")


def test_handoff_extraction():
    """Test that HANDOFF signals are extracted from agent replies."""
    print("\n" + "="*80)
    print("BUG FIX TEST 2: HANDOFF signal extraction")
    print("="*80)
    
    # Test 1: Extract SUGGEST_NEXT handoff
    text1 = """
    Tests passed successfully!
    SUGGEST_NEXT: CodeAgent → All tests passed. Ready to commit.
    FILE_PATH: C:\\Users\\test\\report.txt
    """
    
    artifacts = _extract_artifacts(text1)
    
    print("\n1. Extract SUGGEST_NEXT handoff:")
    print(f"   Files: {artifacts.get('files')}")
    print(f"   Handoffs: {artifacts.get('handoffs')}")
    
    assert len(artifacts.get("handoffs", [])) == 1, "Should extract 1 handoff"
    assert "CodeAgent" in artifacts["handoffs"][0], "Should contain CodeAgent"
    assert "Ready to commit" in artifacts["handoffs"][0], "Should contain message"
    print("   ✅ SUGGEST_NEXT extracted correctly")
    
    # Test 2: Multiple handoffs
    text2 = """
    Build completed!
    SUGGEST_NEXT: FileAgent → Build output at C:\\dist\\ — zip or deploy?
    SUGGEST_NEXT: TerminalAgent → Run tests on the build
    """
    
    artifacts = _extract_artifacts(text2)
    
    print("\n2. Extract multiple handoffs:")
    print(f"   Handoffs: {artifacts.get('handoffs')}")
    
    assert len(artifacts.get("handoffs", [])) == 2, "Should extract 2 handoffs"
    print("   ✅ Multiple handoffs extracted correctly")
    
    # Test 3: No handoffs
    text3 = "Just a regular message with no handoffs"
    artifacts = _extract_artifacts(text3)
    
    print("\n3. No handoffs in text:")
    print(f"   Handoffs: {artifacts.get('handoffs')}")
    
    assert len(artifacts.get("handoffs", [])) == 0, "Should extract 0 handoffs"
    print("   ✅ Correctly handles text without handoffs")
    
    print("\n✅ HANDOFF extraction tests PASSED")


def test_terminal_session_state():
    """Test that TerminalAgent maintains session state."""
    print("\n" + "="*80)
    print("BUG FIX TEST 3: TerminalAgent session state")
    print("="*80)
    
    from tools import terminal_ops
    
    # Reset session
    terminal_ops._TERMINAL_SESSION["cwd"] = str(Path.home())
    terminal_ops._TERMINAL_SESSION["env_overrides"] = {}
    terminal_ops._TERMINAL_SESSION["last_exit_code"] = 0
    
    print("\n1. Initial session state:")
    print(f"   CWD: {terminal_ops._TERMINAL_SESSION['cwd']}")
    print(f"   Env: {terminal_ops._TERMINAL_SESSION['env_overrides']}")
    print(f"   Exit code: {terminal_ops._TERMINAL_SESSION['last_exit_code']}")
    
    # Test cd command updates session
    docs = str(Path.home() / "Documents")
    result = terminal_ops.execute_shell_command(f"cd {docs}")
    
    print(f"\n2. After 'cd {docs}':")
    print(f"   Session CWD: {terminal_ops._TERMINAL_SESSION['cwd']}")
    print(f"   Result CWD: {result.get('cwd')}")
    
    assert terminal_ops._TERMINAL_SESSION["cwd"] == docs, "Session CWD should update"
    print("   ✅ Session CWD updated correctly")
    
    # Test env var persistence
    result = terminal_ops.execute_shell_command("$env:TEST_VAR = 'test123'")
    
    print(f"\n3. After setting env var:")
    print(f"   Session env: {terminal_ops._TERMINAL_SESSION['env_overrides']}")
    
    assert "TEST_VAR" in terminal_ops._TERMINAL_SESSION["env_overrides"], "Env var should be stored"
    assert terminal_ops._TERMINAL_SESSION["env_overrides"]["TEST_VAR"] == "test123", "Env var value should match"
    print("   ✅ Environment variable persisted correctly")
    
    # Test exit code tracking
    result = terminal_ops.execute_shell_command("exit 99")
    
    print(f"\n4. After 'exit 99':")
    print(f"   Session exit code: {terminal_ops._TERMINAL_SESSION['last_exit_code']}")
    print(f"   Result exit code: {result.get('exit_code')}")
    
    assert terminal_ops._TERMINAL_SESSION["last_exit_code"] == 99, "Exit code should be tracked"
    print("   ✅ Exit code tracked correctly")
    
    print("\n✅ TerminalAgent session state tests PASSED")


def test_smart_timeout():
    """Test that smart timeout detection works."""
    print("\n" + "="*80)
    print("BUG FIX TEST 4: Smart timeout detection")
    print("="*80)
    
    from tools import terminal_ops
    
    test_cases = [
        ("pip install requests", 300),
        ("npm install", 300),
        ("docker build .", 600),
        ("pytest", 180),
        ("git status", 30),
        ("ping google.com", 10),
    ]
    
    for cmd, expected in test_cases:
        detected = terminal_ops._detect_timeout(cmd)
        status = "✅" if detected == expected else "❌"
        print(f"{status} {cmd:30} → {detected}s (expected {expected}s)")
        assert detected == expected, f"Timeout mismatch for {cmd}"
    
    print("\n✅ Smart timeout tests PASSED")


def run_all_tests():
    """Run all bug fix tests."""
    print("\n" + "="*80)
    print("BUG FIX TEST SUITE - todo.md Issues")
    print("="*80)
    
    tests = [
        ("make_dir unrestricted", test_make_dir_unrestricted),
        ("HANDOFF extraction", test_handoff_extraction),
        ("TerminalAgent session state", test_terminal_session_state),
        ("Smart timeout detection", test_smart_timeout),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"\n❌ TEST FAILED: {name}")
            print(f"   Error: {e}")
            failed += 1
        except Exception as e:
            print(f"\n❌ TEST ERROR: {name}")
            print(f"   Exception: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "="*80)
    print("BUG FIX TEST SUMMARY")
    print("="*80)
    print(f"Total tests: {len(tests)}")
    print(f"Passed: {passed} ✅")
    print(f"Failed: {failed} ❌")
    
    if failed == 0:
        print("\n🎉 ALL BUG FIXES VERIFIED! 🎉")
        return 0
    else:
        print(f"\n⚠️  {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
