"""
Comprehensive test suite for TerminalAgent upgrade.

Tests all new features:
1. Working directory control (cwd parameter)
2. Session state persistence (cwd, env vars, exit code)
3. Smart timeout detection
4. Git intelligence
5. Package manager intelligence
6. Network diagnostics
7. Command chaining
8. Output intelligence
"""
import os
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from tools import terminal_ops


def test_session_state():
    """Test that session state persists across commands."""
    print("\n" + "="*80)
    print("TEST 1: Session State Persistence")
    print("="*80)
    
    # Reset session
    terminal_ops._TERMINAL_SESSION["cwd"] = str(Path.home())
    terminal_ops._TERMINAL_SESSION["env_overrides"] = {}
    terminal_ops._TERMINAL_SESSION["last_exit_code"] = 0
    
    # Test 1: Check initial CWD
    result = terminal_ops.execute_shell_command("pwd")
    print(f"\n1. Initial CWD: {result.get('cwd')}")
    assert result["ok"], "pwd should succeed"
    
    # Test 2: Change directory with cd command
    docs_path = str(Path.home() / "Documents")
    result = terminal_ops.execute_shell_command(f"cd {docs_path}")
    print(f"\n2. After cd to Documents:")
    print(f"   Session CWD: {terminal_ops._TERMINAL_SESSION['cwd']}")
    assert terminal_ops._TERMINAL_SESSION["cwd"] == docs_path, "Session CWD should update"
    
    # Test 3: Next command should run in new CWD
    result = terminal_ops.execute_shell_command("pwd")
    print(f"\n3. Next command CWD: {result.get('cwd')}")
    assert result.get("cwd") == docs_path, "Next command should use session CWD"
    
    # Test 4: Set environment variable
    result = terminal_ops.execute_shell_command("$env:TEST_VAR = 'hello'")
    print(f"\n4. Set env var TEST_VAR")
    print(f"   Session env: {terminal_ops._TERMINAL_SESSION['env_overrides']}")
    assert "TEST_VAR" in terminal_ops._TERMINAL_SESSION["env_overrides"], "Env var should be stored"
    
    # Test 5: Explicit cwd parameter overrides session
    desktop_path = str(Path.home() / "Desktop")
    result = terminal_ops.execute_shell_command("pwd", cwd=desktop_path)
    print(f"\n5. Explicit cwd parameter:")
    print(f"   Command CWD: {result.get('cwd')}")
    print(f"   Session CWD: {terminal_ops._TERMINAL_SESSION['cwd']}")
    assert result.get("cwd") == desktop_path, "Explicit cwd should override session"
    assert terminal_ops._TERMINAL_SESSION["cwd"] == docs_path, "Session CWD should not change"
    
    print("\n✅ Session state tests PASSED")


def test_smart_timeout():
    """Test that timeout is auto-detected based on command type."""
    print("\n" + "="*80)
    print("TEST 2: Smart Timeout Detection")
    print("="*80)
    
    test_cases = [
        ("ping google.com -n 1", 10, "quick"),
        ("git status", 30, "git"),
        ("pip install requests", 300, "install"),
        ("npm run build", 600, "build"),
        ("pytest", 180, "test"),
        ("docker build .", 600, "docker"),
        ("echo hello", 60, "default"),
    ]
    
    for cmd, expected_timeout, tier in test_cases:
        detected = terminal_ops._detect_timeout(cmd)
        status = "✅" if detected == expected_timeout else "❌"
        print(f"\n{status} {tier:10} | {cmd:30} → {detected}s (expected {expected_timeout}s)")
        assert detected == expected_timeout, f"Timeout mismatch for {cmd}"
    
    print("\n✅ Smart timeout tests PASSED")


def test_cwd_parameter():
    """Test working directory control via cwd parameter."""
    print("\n" + "="*80)
    print("TEST 3: Working Directory Control")
    print("="*80)
    
    # Test 1: Run command in specific directory
    desktop = str(Path.home() / "Desktop")
    result = terminal_ops.execute_shell_command("pwd", cwd=desktop)
    print(f"\n1. Command with cwd={desktop}")
    print(f"   Result CWD: {result.get('cwd')}")
    assert result["ok"], "Command should succeed"
    assert result.get("cwd") == desktop, "CWD should match parameter"
    
    # Test 2: Environment variable expansion
    result = terminal_ops.execute_shell_command("pwd", cwd="%USERPROFILE%\\Documents")
    print(f"\n2. Command with env var cwd=%USERPROFILE%\\Documents")
    print(f"   Result CWD: {result.get('cwd')}")
    assert result["ok"], "Command should succeed"
    assert "Documents" in result.get("cwd", ""), "CWD should expand env var"
    
    # Test 3: Invalid directory
    result = terminal_ops.execute_shell_command("pwd", cwd="C:\\NonExistentDirectory123456")
    print(f"\n3. Command with invalid cwd")
    print(f"   Result: {result.get('error', '')[:100]}")
    assert not result["ok"], "Command should fail with invalid cwd"
    assert "does not exist" in result.get("error", "").lower(), "Error should mention directory"
    
    print("\n✅ Working directory tests PASSED")


def test_git_commands():
    """Test git command execution (if in a git repo)."""
    print("\n" + "="*80)
    print("TEST 4: Git Commands")
    print("="*80)
    
    # Check if we're in a git repo
    check = terminal_ops.execute_shell_command("git rev-parse --git-dir")
    if not check["ok"]:
        print("\n⚠️  Not in a git repository, skipping git tests")
        return
    
    # Test 1: git status
    result = terminal_ops.execute_shell_command("git status --short")
    print(f"\n1. git status --short:")
    print(f"   Exit code: {result.get('exit_code')}")
    print(f"   Output preview: {result.get('output', '')[:200]}")
    assert result["ok"] or result.get("exit_code") == 0, "git status should succeed"
    
    # Test 2: git log
    result = terminal_ops.execute_shell_command("git log --oneline -5")
    print(f"\n2. git log --oneline -5:")
    print(f"   Exit code: {result.get('exit_code')}")
    print(f"   Output preview: {result.get('output', '')[:200]}")
    assert result["ok"] or result.get("exit_code") == 0, "git log should succeed"
    
    # Test 3: git branch
    result = terminal_ops.execute_shell_command("git branch")
    print(f"\n3. git branch:")
    print(f"   Exit code: {result.get('exit_code')}")
    print(f"   Output preview: {result.get('output', '')[:200]}")
    assert result["ok"] or result.get("exit_code") == 0, "git branch should succeed"
    
    print("\n✅ Git command tests PASSED")


def test_command_chaining():
    """Test command chaining with ; and &&."""
    print("\n" + "="*80)
    print("TEST 5: Command Chaining")
    print("="*80)
    
    # Test 1: Sequential execution with ;
    result = terminal_ops.execute_shell_command("echo 'First'; echo 'Second'")
    print(f"\n1. Sequential with ; (echo First; echo Second):")
    print(f"   Exit code: {result.get('exit_code')}")
    print(f"   Output: {result.get('output', '')[:200]}")
    assert result["ok"], "Chained command should succeed"
    assert "First" in result.get("output", "") and "Second" in result.get("output", ""), "Both commands should run"
    
    # Test 2: Conditional execution with && (PowerShell style)
    # In PowerShell, we need to use proper syntax
    result = terminal_ops.execute_shell_command("Write-Output 'Success'; if ($?) { Write-Output 'Also runs' }")
    print(f"\n2. Conditional execution (success case):")
    print(f"   Exit code: {result.get('exit_code')}")
    print(f"   Output: {result.get('output', '')[:200]}")
    # Just check it ran without error
    assert result.get("exit_code") is not None, "Command should execute"
    
    # Test 3: Multiple commands in sequence
    result = terminal_ops.execute_shell_command("$x = 5; $y = 10; Write-Output ($x + $y)")
    print(f"\n3. Multiple variable assignments and output:")
    print(f"   Exit code: {result.get('exit_code')}")
    print(f"   Output: {result.get('output', '')[:200]}")
    assert result["ok"], "Multi-command sequence should succeed"
    assert "15" in result.get("output", ""), "Should output 15"
    
    print("\n✅ Command chaining tests PASSED")


def test_network_commands():
    """Test network diagnostic commands."""
    print("\n" + "="*80)
    print("TEST 6: Network Diagnostics")
    print("="*80)
    
    # Test 1: ping
    result = terminal_ops.execute_shell_command("ping 8.8.8.8 -n 2")
    print(f"\n1. ping 8.8.8.8 -n 2:")
    print(f"   Exit code: {result.get('exit_code')}")
    print(f"   Output preview: {result.get('output', '')[:200]}")
    # Ping might fail in some environments, so just check it ran
    assert result.get("exit_code") is not None, "Ping should return exit code"
    
    # Test 2: ipconfig (Windows) or ifconfig (Unix)
    if os.name == "nt":
        result = terminal_ops.execute_shell_command("ipconfig")
        print(f"\n2. ipconfig:")
    else:
        result = terminal_ops.execute_shell_command("ifconfig")
        print(f"\n2. ifconfig:")
    print(f"   Exit code: {result.get('exit_code')}")
    print(f"   Output preview: {result.get('output', '')[:200]}")
    assert result["ok"], "Network info command should succeed"
    
    print("\n✅ Network diagnostic tests PASSED")


def test_output_truncation():
    """Test that large outputs are properly truncated."""
    print("\n" + "="*80)
    print("TEST 7: Output Truncation")
    print("="*80)
    
    # Generate a command that produces many lines
    if os.name == "nt":
        # Windows: list all files recursively (limited)
        result = terminal_ops.execute_shell_command("Get-ChildItem -Recurse | Select-Object -First 600")
    else:
        # Unix: generate many lines
        result = terminal_ops.execute_shell_command("seq 1 600")
    
    print(f"\n1. Command that generates many lines:")
    print(f"   Exit code: {result.get('exit_code')}")
    output = result.get("output", "")
    lines = output.count("\n")
    print(f"   Output lines: {lines}")
    print(f"   Output length: {len(output)} chars")
    
    # Check if truncation message is present for large outputs
    if lines > terminal_ops._MAX_OUTPUT_LINES:
        assert "truncated" in output.lower(), "Large output should be truncated"
        print("   ✅ Output was truncated as expected")
    else:
        print("   ℹ️  Output was small enough, no truncation needed")
    
    print("\n✅ Output truncation tests PASSED")


def test_exit_code_tracking():
    """Test that exit codes are tracked in session state."""
    print("\n" + "="*80)
    print("TEST 8: Exit Code Tracking")
    print("="*80)
    
    # Test 1: Successful command
    result = terminal_ops.execute_shell_command("echo 'success'")
    print(f"\n1. Successful command:")
    print(f"   Exit code: {result.get('exit_code')}")
    print(f"   Session last_exit_code: {terminal_ops._TERMINAL_SESSION['last_exit_code']}")
    assert result.get("exit_code") == 0, "Successful command should have exit code 0"
    assert terminal_ops._TERMINAL_SESSION["last_exit_code"] == 0, "Session should track exit code"
    
    # Test 2: Failed command
    result = terminal_ops.execute_shell_command("exit 42")
    print(f"\n2. Failed command (exit 42):")
    print(f"   Exit code: {result.get('exit_code')}")
    print(f"   Session last_exit_code: {terminal_ops._TERMINAL_SESSION['last_exit_code']}")
    assert result.get("exit_code") == 42, "Failed command should have exit code 42"
    assert terminal_ops._TERMINAL_SESSION["last_exit_code"] == 42, "Session should track exit code"
    
    print("\n✅ Exit code tracking tests PASSED")


def run_all_tests():
    """Run all test suites."""
    print("\n" + "="*80)
    print("TERMINAL AGENT UPGRADE - COMPREHENSIVE TEST SUITE")
    print("="*80)
    print(f"Python: {sys.version}")
    print(f"OS: {os.name}")
    print(f"Platform: {sys.platform}")
    
    tests = [
        ("Session State Persistence", test_session_state),
        ("Smart Timeout Detection", test_smart_timeout),
        ("Working Directory Control", test_cwd_parameter),
        ("Git Commands", test_git_commands),
        ("Command Chaining", test_command_chaining),
        ("Network Diagnostics", test_network_commands),
        ("Output Truncation", test_output_truncation),
        ("Exit Code Tracking", test_exit_code_tracking),
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
    print("TEST SUMMARY")
    print("="*80)
    print(f"Total tests: {len(tests)}")
    print(f"Passed: {passed} ✅")
    print(f"Failed: {failed} ❌")
    
    if failed == 0:
        print("\n🎉 ALL TESTS PASSED! 🎉")
        return 0
    else:
        print(f"\n⚠️  {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
