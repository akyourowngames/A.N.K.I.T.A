
import sys
import os
import json
import time
from datetime import datetime

# Fix for Windows encoding issues
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add the project directory to path
PROJECT_ROOT = r"C:\Users\anime\3D Objects\New folder\A.N.K.I.T.A\ankita"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Also add the directory above ankita if imports look for the package name
PARENT_DIR = os.path.dirname(PROJECT_ROOT)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

try:
    from brain.scenario_generator import ScenarioGenerator
    from brain.intent_model import classify
    from brain.planner import plan
    from brain.context_collector import get_current_context
    print("[Diagnostic] Modules loaded successfully.")
except ImportError as e:
    print(f"[Error] Could not load Ankita modules: {e}")
    sys.exit(1)

def run_deep_test(num_scenarios=20):
    gen = ScenarioGenerator(use_dynamic_queries=True)
    scenarios = gen.generate_batch(count=num_scenarios)
    
    from brain.semantic import get_interpreter, get_planner
    interpreter = get_interpreter()
    planner = get_planner()
    
    results = {
        "total": num_scenarios,
        "semantic_matches": 0,
        "traditional_matches": 0,
        "action_matches": 0,
        "failures": [],
        "latency_ms": []
    }
    
    print(f"--- Starting Deep Brain Test ({num_scenarios} scenarios) ---")
    
    for i, sc in enumerate(scenarios):
        query = sc['query']
        expected_situation = sc['situation']
        expected_action = sc['expected_action']
        
        start_time = time.time()
        
        # 1. Test Semantic Layer
        sem_res = interpreter.detect_situation(query.lower(), threshold=0.1) # low threshold for testing
        sem_sit = sem_res['situation'] if sem_res else "unknown"
        
        # 2. Test Traditional Layer
        trad_res = classify(query)
        trad_intent = trad_res.get('intent', 'unknown')
        
        # 3. Test Planning (using expected situation for planning test)
        # We want to see if the planner correctly maps situation -> actions
        p_actions = planner.plan_actions(expected_situation, sc['context'])
        planned_tools = [a.get('tool') for a in p_actions]
        
        end_time = time.time()
        
        latency = (end_time - start_time) * 1000
        results["latency_ms"].append(latency)
        
        is_sem_match = sem_sit == expected_situation
        is_trad_match = trad_intent.startswith(expected_situation.split('.')[0]) or trad_intent == expected_situation
        is_action_match = any(expected_action in t or t in expected_action for t in planned_tools)
        
        if is_sem_match: results["semantic_matches"] += 1
        if is_trad_match: results["traditional_matches"] += 1
        if is_action_match: results["action_matches"] += 1
        
        status = "PASS" if (is_sem_match or is_trad_match) and is_action_match else "FAIL"
        print(f"[{i+1}/{num_scenarios}] {status} Query: '{query}'")
        if status == "FAIL":
            print(f"    Expected Sit: {expected_situation} | Got Sem: {sem_sit}, Trad: {trad_intent}")
            print(f"    Expected Act: {expected_action} | Got Planned: {planned_tools}")
            results["failures"].append({
                "query": query,
                "expected": {"sit": expected_situation, "act": expected_action},
                "got": {"sem": sem_sit, "trad": trad_intent, "acts": planned_tools}
            })

    # Summary
    print("\n--- TEST SUMMARY ---")
    print(f"Semantic Accuracy:    {(results['semantic_matches']/num_scenarios)*100:.1f}%")
    print(f"Traditional Accuracy: {(results['traditional_matches']/num_scenarios)*100:.1f}%")
    print(f"Planning Accuracy:    {(results['action_matches']/num_scenarios)*100:.1f}%")
    avg_latency = sum(results["latency_ms"]) / num_scenarios
    print(f"Average Latency:      {avg_latency:.2f}ms")
    
    return results

if __name__ == "__main__":
    report = run_deep_test(20)
    with open("brain_diagnostic_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("\n[Diagnostic] Detailed report saved to brain_diagnostic_report.json")
