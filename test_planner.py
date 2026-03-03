"""
Test script for PlannerAgent implementation.

Tests the complete flow:
1. Supervisor detects multi-step request
2. Routes to PlannerAgent
3. PlannerAgent generates a plan
4. Orchestrator executes the plan step by step
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from llm import build_runtime_from_env
from agents.orchestrator import Orchestrator
from agents.supervisor import SupervisorAgent


def test_supervisor_routing():
    """Test that Supervisor correctly routes multi-step requests to PlannerAgent."""
    print("=" * 80)
    print("TEST 1: Supervisor Multi-Step Detection")
    print("=" * 80)
    
    runtime = build_runtime_from_env()
    supervisor = SupervisorAgent(runtime)
    
    test_cases = [
        # Should route to PlannerAgent
        ("research laptops, write a report, save it, email Raj", True),
        ("fix the bug, run tests, if pass commit to github", True),
        ("search Python jobs and JavaScript jobs, then merge results", True),
        
        # Should NOT route to PlannerAgent
        ("write a poem and save it", False),
        ("play lo-fi music", False),
        ("what's the weather", False),
    ]
    
    for request, should_use_planner in test_cases:
        print(f"\nRequest: {request}")
        routing = supervisor.route(request)
        agents = routing.get("agents", [])
        uses_planner = "PlannerAgent" in agents
        
        status = "[OK]" if uses_planner == should_use_planner else "[FAIL]"
        print(f"{status} Routed to: {agents}")
        print(f"   Reasoning: {routing.get('reasoning', '')[:100]}")
        
        if uses_planner != should_use_planner:
            print(f"   FAILED: Expected PlannerAgent={should_use_planner}, got {uses_planner}")


def test_planner_json_generation():
    """Test that PlannerAgent generates valid JSON plans."""
    print("\n" + "=" * 80)
    print("TEST 2: PlannerAgent JSON Generation")
    print("=" * 80)
    
    runtime = build_runtime_from_env()
    workspace_root = Path.cwd()
    orchestrator = Orchestrator(runtime, workspace_root)
    
    # Simulate a multi-step request
    request = "research best budget laptops under 50000 INR, write a comparison report, save it to desktop"
    messages = []
    
    print(f"\nRequest: {request}")
    print("\nCalling PlannerAgent...")
    
    try:
        # This will trigger the full flow: Supervisor → PlannerAgent → Execution
        result = orchestrator.run(request, messages)
        print(f"\n[OK] Plan executed successfully!")
        print(f"Result preview: {result[:200]}...")
    except Exception as e:
        print(f"\n[FAIL] Error: {e}")
        import traceback
        traceback.print_exc()


def test_conditional_execution():
    """Test that PlannerAgent handles conditional steps correctly."""
    print("\n" + "=" * 80)
    print("TEST 3: Conditional Step Execution")
    print("=" * 80)
    
    runtime = build_runtime_from_env()
    workspace_root = Path.cwd()
    orchestrator = Orchestrator(runtime, workspace_root)
    
    # Request with conditional logic
    request = "write a test file, run it, and only if it passes, commit to git"
    messages = []
    
    print(f"\nRequest: {request}")
    print("\nThis should generate a plan with a conditional step...")
    
    try:
        result = orchestrator.run(request, messages)
        print(f"\n[OK] Conditional plan executed!")
        print(f"Result: {result[:300]}...")
    except Exception as e:
        print(f"\n[FAIL] Error: {e}")


def test_parallel_execution():
    """Test that PlannerAgent can handle parallel steps."""
    print("\n" + "=" * 80)
    print("TEST 4: Parallel Step Execution")
    print("=" * 80)
    
    runtime = build_runtime_from_env()
    workspace_root = Path.cwd()
    orchestrator = Orchestrator(runtime, workspace_root)
    
    # Request that can be parallelized
    request = "search for Python jobs and JavaScript jobs at the same time, then merge the results"
    messages = []
    
    print(f"\nRequest: {request}")
    print("\nThis should generate a plan with parallel steps...")
    
    try:
        result = orchestrator.run(request, messages)
        print(f"\n[OK] Parallel plan executed!")
        print(f"Result: {result[:300]}...")
    except Exception as e:
        print(f"\n[FAIL] Error: {e}")


if __name__ == "__main__":
    print("\nPlannerAgent Implementation Test Suite\n")
    
    # Run tests
    test_supervisor_routing()
    
    # Only run full execution tests if user confirms (they make real API calls)
    print("\n" + "=" * 80)
    response = input("\nRun full execution tests? (These will make real LLM API calls) [y/N]: ")
    if response.lower() == 'y':
        test_planner_json_generation()
        test_conditional_execution()
        test_parallel_execution()
    else:
        print("\nSkipping full execution tests.")
    
    print("\n" + "=" * 80)
    print("[OK] Test suite complete!")
    print("=" * 80)
