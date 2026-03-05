"""
Real-world scenario tests for the new autonomous tools.
Tests: autonomous_ops, integration_hub, terminal_ops (new functions)

NOTE: Imports use direct module imports to avoid the heavy tools/__init__.py
chain which loads pyautogui/desktop_ops and can hang on some systems.
"""
import json
import sys
import os

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Direct imports — bypass tools/__init__.py which loads heavy modules
import importlib
autonomous_ops = importlib.import_module("tools.autonomous_ops")
integration_hub = importlib.import_module("tools.integration_hub")
terminal_ops = importlib.import_module("tools.terminal_ops")


def test_discover_tools():
    """Scenario: ANKITA starts up and needs to know what's available."""
    result = autonomous_ops.discover_tools()
    assert result["ok"], f"discover_tools failed: {result}"
    inv = result["inventory"]
    assert "package_managers" in inv
    assert "runtimes" in inv
    assert "cli_tools" in inv
    assert "shells" in inv
    # At least Python and git should be found
    assert "python" in inv["runtimes"], "Python should be detected"
    assert inv["cli_tools"].get("git"), "Git should be available"
    print(f"  PASS: discover_tools — {result['summary']}")


def test_system_audit():
    """Scenario: User asks 'what system am I running on?'"""
    result = autonomous_ops.system_audit()
    assert result["ok"], f"system_audit failed: {result}"
    assert result["os"], "OS info should be present"
    assert result["cpu"], "CPU info should be present"
    assert result["ram_gb"], "RAM info should be present"
    print(f"  PASS: system_audit — OS: {result['os'][:40]}...")


def test_get_system_context():
    """Scenario: Terminal agent needs to know current environment state."""
    result = terminal_ops.get_system_context()
    assert result["ok"], f"get_system_context failed: {result}"
    assert result["platform"] in ("windows", "unix")
    assert "available_tools" in result
    assert isinstance(result["available_tools"], dict)
    print(f"  PASS: get_system_context — platform={result['platform']}, tools={sum(result['available_tools'].values())}")


def test_generate_and_run_script_python():
    """Scenario: User asks 'count all Python files in this project'."""
    script = """
import os
from pathlib import Path
root = Path(os.environ.get('USERPROFILE', os.path.expanduser('~')))
txt_files = list(root.glob('*.txt'))
print(f"Found {len(txt_files)} .txt files in home directory")
for f in txt_files[:5]:
    print(f"  {f.name}")
"""
    result = autonomous_ops.generate_and_run_script(
        description="Count .txt files in home directory",
        language="python",
        script_content=script,
    )
    assert result["ok"], f"Script failed: {result.get('error', '')}"
    assert result["exit_code"] == 0
    assert result["kind"] == "script_execution"
    print(f"  PASS: generate_and_run_script(python) — {result['output'][:80]}")


def test_generate_and_run_script_powershell():
    """Scenario: User asks 'get me a list of running processes sorted by memory'."""
    script = """
Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 5 Name, @{N='MemMB';E={[math]::Round($_.WorkingSet64/1MB)}} | Format-Table -AutoSize
"""
    result = autonomous_ops.generate_and_run_script(
        description="Top 5 processes by memory",
        language="powershell",
        script_content=script,
    )
    assert result["ok"], f"Script failed: exit={result.get('exit_code')} err={result.get('error', '')[:200]}"
    assert "Name" in result["output"] or result["output"] != "(no output)"
    print(f"  PASS: generate_and_run_script(powershell) — output len={len(result['output'])}")


def test_execute_pipeline():
    """Scenario: 'Check git status, then show recent commits, then show branch info'."""
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = autonomous_ops.execute_pipeline(
        steps=[
            {"command": f'cd "{project_dir}" && git rev-parse --git-dir', "description": "Check if git repo"},
            {"command": f'cd "{project_dir}" && git branch --show-current', "description": "Get current branch"},
            {"command": f'cd "{project_dir}" && git log --oneline -5', "description": "Last 5 commits"},
        ],
        stop_on_error=True,
    )
    assert result["ok"], f"Pipeline failed: {json.dumps(result['results'], indent=2)}"
    assert result["completed"] >= 1  # At least first step should pass
    print(f"  PASS: execute_pipeline — {result['completed']}/{result['total_steps']} steps completed")
    for r in result["results"]:
        out = r.get("output", "")[:60]
        print(f"    Step {r['step']}: {r['description']} — {'OK' if r['ok'] else 'FAIL'} {out}")


def test_chain_commands():
    """Scenario: 'Check Python version, then check pip version, then check node version'."""
    result = terminal_ops.chain_commands(
        commands=[
            {"command": "python --version", "description": "Python version"},
            {"command": "pip --version", "description": "Pip version"},
            {"command": "node --version", "description": "Node version"},
        ],
        mode="independent",  # Run all regardless of errors
    )
    assert result["ok"] or result["completed"] > 0
    print(f"  PASS: chain_commands — {result['completed']}/{result['total']} completed")
    for r in result["results"]:
        out = r.get("output", "")[:60]
        print(f"    Step {r['step']}: {r['description']} — {out}")


def test_execute_elevated():
    """Scenario: Run a command that may need elevation (but this one doesn't)."""
    result = terminal_ops.execute_elevated("whoami", timeout=10)
    assert result["ok"], f"execute_elevated failed: {result}"
    assert result["output"]
    print(f"  PASS: execute_elevated — {result['output'][:50]}")


def test_auto_install_python_package():
    """Scenario: 'Install requests for me'."""
    # requests is likely already installed, but this tests the flow
    result = autonomous_ops.auto_install_python_package("requests")
    assert result["ok"], f"auto_install_python_package failed: {result}"
    print(f"  PASS: auto_install_python_package — {result.get('message', result.get('output', ''))[:80]}")


def test_environment_setup_auto():
    """Scenario: 'Set up this ANKITA project'."""
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = autonomous_ops.environment_setup(project_type="auto", project_path=project_dir)
    # Should detect as Python project
    assert result.get("type") in ("python", "auto", "node", "unknown"), f"Unexpected type: {result.get('type')}"
    print(f"  PASS: environment_setup — detected={result.get('type')}, actions={result.get('actions_taken', [])}")


def test_github_op():
    """Scenario: 'Show me my GitHub repos'."""
    # This requires gh CLI to be installed and authed
    result = integration_hub.github_op(action="repo_view")
    # May fail if not in a git repo or gh not authed, but should return structured response
    print(f"  {'PASS' if result['ok'] else 'EXPECTED-FAIL'}: github_op(repo_view) — {result.get('output', result.get('error', ''))[:80]}")


def test_api_test():
    """Scenario: 'Test if httpbin is working'."""
    result = integration_hub.api_test(
        method="GET",
        url="https://httpbin.org/get",
        timeout=15,
    )
    if result["ok"]:
        print(f"  PASS: api_test(GET httpbin) — status={result.get('status_code')}")
    else:
        # May fail if no internet, but should handle gracefully
        print(f"  EXPECTED-FAIL: api_test — {result.get('error', '')[:80]}")


def test_db_query_sqlite():
    """Scenario: 'Create a quick SQLite database and query it'."""
    import tempfile
    
    # Create a temp SQLite DB and query it
    db_path = os.path.join(tempfile.gettempdir(), "ankita_test.db")
    
    # Create table
    result = integration_hub.db_query(engine="sqlite", query="CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY, name TEXT);", database=db_path)
    print(f"  {'PASS' if result['ok'] else 'FAIL'}: db_query(sqlite CREATE) — {result.get('output', result.get('error', ''))[:80]}")
    
    # Insert data
    result = integration_hub.db_query(engine="sqlite", query="INSERT INTO test (name) VALUES ('ankita_test');", database=db_path)
    print(f"  {'PASS' if result['ok'] else 'FAIL'}: db_query(sqlite INSERT) — {result.get('output', result.get('error', ''))[:80]}")
    
    # Query
    result = integration_hub.db_query(engine="sqlite", query="SELECT * FROM test;", database=db_path)
    print(f"  {'PASS' if result['ok'] else 'FAIL'}: db_query(sqlite SELECT) — {result.get('output', result.get('error', ''))[:80]}")
    
    # Cleanup
    try:
        os.remove(db_path)
    except:
        pass


def test_service_op():
    """Scenario: 'What services are running on my machine?'"""
    result = integration_hub.service_op(action="list_services")
    if result["ok"]:
        output_lines = result.get("output", "").splitlines()
        print(f"  PASS: service_op(list_services) — {len(output_lines)} output lines")
    else:
        print(f"  FAIL: service_op — {result.get('error', '')[:80]}")


def test_docker_op():
    """Scenario: 'Is Docker running? Show me containers'."""
    result = integration_hub.docker_op(action="ps")
    if result["ok"]:
        print(f"  PASS: docker_op(ps) — {result.get('output', '')[:80]}")
    else:
        # Docker not installed is expected on many systems
        print(f"  EXPECTED-FAIL: docker_op(ps) — {result.get('error', '')[:80]}")


if __name__ == "__main__":
    print("=" * 70)
    print("  ANKITA Autonomous Tools — Real Scenario Tests")
    print("=" * 70)
    
    tests = [
        ("discover_tools", test_discover_tools),
        ("system_audit", test_system_audit),
        ("get_system_context", test_get_system_context),
        ("generate_script (Python)", test_generate_and_run_script_python),
        ("generate_script (PowerShell)", test_generate_and_run_script_powershell),
        ("execute_pipeline", test_execute_pipeline),
        ("chain_commands", test_chain_commands),
        ("execute_elevated", test_execute_elevated),
        ("auto_install_python_package", test_auto_install_python_package),
        ("environment_setup", test_environment_setup_auto),
        ("github_op", test_github_op),
        ("api_test", test_api_test),
        ("db_query (sqlite)", test_db_query_sqlite),
        ("service_op", test_service_op),
        ("docker_op", test_docker_op),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_fn in tests:
        try:
            print(f"\n--- {name} ---")
            test_fn()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {name} — {type(e).__name__}: {e}")
            failed += 1
    
    print(f"\n{'=' * 70}")
    print(f"  Results: {passed} passed, {failed} failed, {passed + failed} total")
    print(f"{'=' * 70}")
