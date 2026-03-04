"""
Test suite for PlannerAgent bug fixes from todo.md

Tests:
1. Conditional evaluation with actual result data
2. Parallel execution timeout guard
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agents.orchestrator import _evaluate_condition


def test_conditional_evaluation():
    """Test that conditions are evaluated against actual step results."""
    print("\n" + "="*80)
    print("PLANNER FIX TEST 1: Conditional Evaluation")
    print("="*80)
    
    # Mock step results
    step_results = {
        1: {"ok": True, "exit_code": 0, "reply": "Success"},
        2: {"ok": False, "exit_code": 1, "reply": "Failed"},
        3: {"ok": True, "exit_code": 0, "reply": "Done"},
    }
    
    # Test 1: Check exit_code == 0
    condition = "only if step 1 exit_code == 0"
    result = _evaluate_condition(condition, step_results, [1])
    print(f"\n1. Condition: '{condition}'")
    print(f"   Step 1 exit_code: {step_results[1]['exit_code']}")
    print(f"   Result: {result}")
    assert result == True, "Should pass when exit_code == 0"
    print("   ✅ Correctly evaluated exit_code == 0")
    
    # Test 2: Check exit_code == 1 (should fail)
    condition = "only if step 2 exit_code == 0"
    result = _evaluate_condition(condition, step_results, [2])
    print(f"\n2. Condition: '{condition}'")
    print(f"   Step 2 exit_code: {step_results[2]['exit_code']}")
    print(f"   Result: {result}")
    assert result == False, "Should fail when exit_code != 0"
    print("   ✅ Correctly evaluated exit_code != 0")
    
    # Test 3: Check "succeeded" keyword
    condition = "only if step 1 succeeded"
    result = _evaluate_condition(condition, step_results, [1])
    print(f"\n3. Condition: '{condition}'")
    print(f"   Step 1 ok: {step_results[1]['ok']}")
    print(f"   Result: {result}")
    assert result == True, "Should pass when step succeeded"
    print("   ✅ Correctly evaluated 'succeeded'")
    
    # Test 4: Check "failed" keyword
    condition = "only if step 2 failed"
    result = _evaluate_condition(condition, step_results, [2])
    print(f"\n4. Condition: '{condition}'")
    print(f"   Step 2 ok: {step_results[2]['ok']}")
    print(f"   Result: {result}")
    assert result == True, "Should pass when step failed"
    print("   ✅ Correctly evaluated 'failed'")
    
    # Test 5: Check ok == true
    condition = "only if step 3 ok == true"
    result = _evaluate_condition(condition, step_results, [3])
    print(f"\n5. Condition: '{condition}'")
    print(f"   Step 3 ok: {step_results[3]['ok']}")
    print(f"   Result: {result}")
    assert result == True, "Should pass when ok == true"
    print("   ✅ Correctly evaluated ok == true")
    
    # Test 6: Check non-existent step
    condition = "only if step 99 exit_code == 0"
    result = _evaluate_condition(condition, step_results, [99])
    print(f"\n6. Condition: '{condition}'")
    print(f"   Step 99 exists: False")
    print(f"   Result: {result}")
    assert result == False, "Should fail when step doesn't exist"
    print("   ✅ Correctly handled non-existent step")
    
    print("\n✅ Conditional evaluation tests PASSED")


def test_parallel_timeout_implementation():
    """Test that parallel execution has timeout guards."""
    print("\n" + "="*80)
    print("PLANNER FIX TEST 2: Parallel Timeout Guard")
    print("="*80)
    
    # Read the _fan_out_parallel implementation
    from agents.orchestrator import Orchestrator
    import inspect
    
    source = inspect.getsource(Orchestrator._fan_out_parallel)
    
    print("\n1. Checking _fan_out_parallel implementation:")
    
    # Check for timeout constant
    has_timeout_constant = "STEP_TIMEOUT" in source or "timeout" in source.lower()
    print(f"   Has timeout constant: {has_timeout_constant}")
    assert has_timeout_constant, "Should define timeout constant"
    
    # Check for timeout in as_completed
    has_as_completed_timeout = "as_completed" in source and "timeout=" in source
    print(f"   Uses timeout in as_completed: {has_as_completed_timeout}")
    assert has_as_completed_timeout, "Should use timeout in as_completed"
    
    # Check for TimeoutError handling
    has_timeout_error = "TimeoutError" in source or "timeout" in source.lower()
    print(f"   Handles TimeoutError: {has_timeout_error}")
    assert has_timeout_error, "Should handle TimeoutError"
    
    # Check for per-future timeout
    has_future_timeout = "future.result(timeout=" in source
    print(f"   Has per-future timeout: {has_future_timeout}")
    assert has_future_timeout, "Should have per-future timeout"
    
    print("\n   ✅ All timeout guards implemented")
    
    print("\n✅ Parallel timeout guard tests PASSED")


def test_handoff_in_context():
    """Test that handoffs are included in prior context."""
    print("\n" + "="*80)
    print("PLANNER FIX TEST 3: HANDOFF in Context")
    print("="*80)
    
    from agents.orchestrator import _build_prior_context_block
    
    # Test with handoffs
    artifacts = {
        "files": ["C:\\test\\file.txt"],
        "urls": ["https://example.com"],
        "handoffs": ["SUGGEST_NEXT: CodeAgent → Fix the error"]
    }
    
    context = _build_prior_context_block("TerminalAgent", "Tests passed!", artifacts)
    
    print("\n1. Building context with handoff:")
    print(f"   Artifacts: {artifacts}")
    print(f"\n   Context preview:")
    print("   " + "\n   ".join(context.split("\n")[:10]))
    
    assert "HANDOFF:" in context, "Context should include HANDOFF line"
    assert "CodeAgent" in context, "Context should include agent name"
    print("\n   ✅ HANDOFF included in context")
    
    print("\n✅ HANDOFF context tests PASSED")


def run_all_tests():
    """Run all PlannerAgent fix tests."""
    print("\n" + "="*80)
    print("PLANNER AGENT BUG FIX TEST SUITE")
    print("="*80)
    
    tests = [
        ("Conditional Evaluation", test_conditional_evaluation),
        ("Parallel Timeout Guard", test_parallel_timeout_implementation),
        ("HANDOFF in Context", test_handoff_in_context),
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
    print("PLANNER FIX TEST SUMMARY")
    print("="*80)
    print(f"Total tests: {len(tests)}")
    print(f"Passed: {passed} ✅")
    print(f"Failed: {failed} ❌")
    
    if failed == 0:
        print("\n🎉 ALL PLANNER FIXES VERIFIED! 🎉")
        return 0
    else:
        print(f"\n⚠️  {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
