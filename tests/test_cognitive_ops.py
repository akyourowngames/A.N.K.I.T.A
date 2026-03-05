"""
ANKITA Cognitive Ops — Real-World Scenario Tests
Tests: resolve_error, smart_retry, workspace_scan, plan_and_execute,
       code_analysis, project_scaffold, process_watch, translate_command,
       self_extend, execute_extension, list_extensions
"""
import importlib
import json
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Direct import to bypass the heavy tools/__init__.py chain
cognitive_ops = importlib.import_module("tools.cognitive_ops")

PASS = 0
FAIL = 0

def test(name, ok, detail=""):
    global PASS, FAIL
    status = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(f"  {status}: {name} — {detail[:120]}")

print("=" * 70)
print("  ANKITA Cognitive Ops — Real Scenario Tests")
print("=" * 70)

# ── 1. resolve_error — Known error patterns ──
print("\n--- resolve_error (missing module) ---")
result = cognitive_ops.resolve_error(
    error_text="Traceback (most recent call last):\n  File 'app.py', line 1\nModuleNotFoundError: No module named 'requests'",
    command="python app.py",
)
test("resolve_error(missing module)",
     result.get("matched") and "missing_module" in str(result.get("analysis", [])),
     f"matched={result.get('matched')}, analysis={str(result.get('analysis', ''))[:100]}")

print("\n--- resolve_error (permission denied) ---")
result = cognitive_ops.resolve_error(
    error_text="Access is denied.\nError: Cannot write to C:\\Windows\\System32\\config",
    command="copy file.txt C:\\Windows\\System32\\",
)
test("resolve_error(permission)",
     result.get("matched") and "permission" in str(result.get("analysis", [])),
     f"category=permission, matched={result.get('matched')}")

print("\n--- resolve_error (git conflict) ---")
result = cognitive_ops.resolve_error(
    error_text="CONFLICT (content): Merge conflict in README.md\nAutomatic merge failed; fix conflicts and then commit",
)
test("resolve_error(git merge conflict)",
     result.get("matched") and "merge_conflict" in str(result.get("analysis", [])),
     f"matched={result.get('matched')}")

print("\n--- resolve_error (port conflict) ---")
result = cognitive_ops.resolve_error(
    error_text="Error: port is already allocated: bind for 0.0.0.0:3000 failed",
    command="docker run -p 3000:3000 myapp",
)
test("resolve_error(port conflict)",
     result.get("matched") and "port_conflict" in str(result.get("analysis", [])),
     f"matched={result.get('matched')}")

print("\n--- resolve_error (unknown error) ---")
result = cognitive_ops.resolve_error(
    error_text="Some completely unknown error xyz123",
)
test("resolve_error(unknown)",
     not result.get("matched"),
     f"matched={result.get('matched')}, has_suggestions={bool(result.get('suggestions'))}")

# ── 2. smart_retry — Self-healing execution ──
print("\n--- smart_retry (simple success) ---")
result = cognitive_ops.smart_retry(command="echo hello world", max_retries=1, timeout=10)
test("smart_retry(echo)",
     result.get("ok") and result.get("succeeded_on_attempt") == 1,
     f"ok={result.get('ok')}, attempt={result.get('succeeded_on_attempt')}")

print("\n--- smart_retry (guaranteed failure) ---")
result = cognitive_ops.smart_retry(
    command="this_command_does_not_exist_12345",
    max_retries=2, timeout=10, auto_fix=False,
)
test("smart_retry(nonexistent cmd)",
     not result.get("ok") and result.get("total_attempts", 0) >= 2,
     f"ok={result.get('ok')}, attempts={result.get('total_attempts')}")

# ── 3. workspace_scan — Deep project intelligence ──
print("\n--- workspace_scan (ANKITA itself) ---")
ankita_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
result = cognitive_ops.workspace_scan(path=ankita_root)
test("workspace_scan(ANKITA)",
     result.get("ok") and "python" in result.get("tech_stack", []) and result.get("is_git_repo"),
     f"stack={result.get('tech_stack')}, files={result.get('total_files')}, "
     f"branch={result.get('git_branch')}, summary={result.get('summary','')[:80]}")

# ── 4. plan_and_execute — Multi-step with verification ──
print("\n--- plan_and_execute (3-step success) ---")
result = cognitive_ops.plan_and_execute(
    goal="System info check",
    steps=[
        {"command": "python --version", "description": "Check Python"},
        {"command": "node --version", "description": "Check Node"},
        {"command": "git --version", "description": "Check Git"},
    ],
    verify_command="echo all_checks_passed",
)
test("plan_and_execute(3 steps + verify)",
     result.get("ok") and result.get("succeeded") == 3 and result.get("verification", {}).get("ok"),
     f"ok={result.get('ok')}, succeeded={result.get('succeeded')}/{result.get('total_steps')}, "
     f"verified={result.get('verification', {}).get('ok')}, elapsed={result.get('elapsed_seconds')}s")

print("\n--- plan_and_execute (partial failure, no stop) ---")
result = cognitive_ops.plan_and_execute(
    goal="Partial test",
    steps=[
        {"command": "echo step1_ok", "description": "Step 1"},
        {"command": "nonexistent_cmd_xyz", "description": "Step 2 (will fail)", "retries": 1},
        {"command": "echo step3_ok", "description": "Step 3"},
    ],
    stop_on_error=False,
)
test("plan_and_execute(partial failure)",
     not result.get("ok") and result.get("succeeded", 0) >= 2 and result.get("failed", 0) >= 1,
     f"succeeded={result.get('succeeded')}, failed={result.get('failed')}")

# ── 5. code_analysis — Security scan ──
print("\n--- code_analysis (ANKITA security scan) ---")
result = cognitive_ops.code_analysis(path=ankita_root, focus="security")
test("code_analysis(security)",
     result.get("ok") and "builtin_security_scan" in result.get("results", {}),
     f"scanned={result.get('results',{}).get('builtin_security_scan',{}).get('files_scanned',0)} files, "
     f"issues={result.get('results',{}).get('builtin_security_scan',{}).get('issues_found',0)}")

# ── 6. project_scaffold — Create a project ──
print("\n--- project_scaffold (python-cli) ---")
scaffold_dir = os.path.join(tempfile.gettempdir(), "ankita_test_scaffold")
if os.path.exists(scaffold_dir):
    shutil.rmtree(scaffold_dir)
result = cognitive_ops.project_scaffold(
    template="python-cli",
    name="test-cli-app",
    path=scaffold_dir,
    auto_setup=False,  # Skip dep install for speed
)
test("project_scaffold(python-cli)",
     result.get("ok") and os.path.exists(os.path.join(scaffold_dir, "main.py")),
     f"files={result.get('files_created')}, path={result.get('path')}")
# Cleanup
if os.path.exists(scaffold_dir):
    shutil.rmtree(scaffold_dir)

print("\n--- project_scaffold (unknown template) ---")
result = cognitive_ops.project_scaffold(template="unknown-xyz", name="test")
test("project_scaffold(unknown)",
     not result.get("ok") and "available" in result,
     f"available={result.get('available')}")

# ── 7. translate_command ──
print("\n--- translate_command (ls -la -> Windows) ---")
result = cognitive_ops.translate_command(command="ls -la", from_platform="linux")
test("translate_command(ls -la)",
     result.get("ok") and "Get-ChildItem" in result.get("translated", ""),
     f"translated={result.get('translated')}")

print("\n--- translate_command (apt install -> Windows) ---")
result = cognitive_ops.translate_command(command="apt install nginx", from_platform="linux")
test("translate_command(apt install)",
     result.get("ok") and "winget" in result.get("translated", ""),
     f"translated={result.get('translated')}")

print("\n--- translate_command (grep -> Windows) ---")
result = cognitive_ops.translate_command(command="grep pattern file.txt", from_platform="linux")
test("translate_command(grep)",
     result.get("ok") and "Select-String" in result.get("translated", ""),
     f"translated={result.get('translated')}")

# ── 8. self_extend + execute_extension + list_extensions ──
print("\n--- self_extend (create tool) ---")
result = cognitive_ops.self_extend(
    name="hello_test_tool",
    description="A test tool that returns a greeting",
    code='def hello_test_tool(name="World"):\n    return {"greeting": f"Hello {name}!"}\n',
)
test("self_extend(hello_test_tool)",
     result.get("ok") and result.get("registered"),
     f"registered={result.get('registered')}, file={result.get('file','')[-30:]}")

print("\n--- execute_extension ---")
result = cognitive_ops.execute_extension(name="hello_test_tool", args={"name": "ANKITA"})
test("execute_extension(hello_test_tool)",
     result.get("ok") and "ANKITA" in str(result.get("result", "")),
     f"result={result.get('result')}")

print("\n--- list_extensions ---")
result = cognitive_ops.list_extensions()
test("list_extensions",
     result.get("ok") and "hello_test_tool" in result.get("extensions", {}),
     f"count={result.get('count')}, has_hello={bool(result.get('extensions',{}).get('hello_test_tool'))}")

# Cleanup test extension
ext_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "extensions", "hello_test_tool.py")
if os.path.exists(ext_file):
    os.remove(ext_file)

# ── 9. process_watch ──
print("\n--- process_watch (echo with pattern) ---")
result = cognitive_ops.process_watch(
    command='echo "Server listening on port 3000"',
    duration=10,
    success_pattern="listening on port",
)
test("process_watch(echo+pattern)",
     result.get("ok") or result.get("pattern_matched") == "success",
     f"matched={result.get('pattern_matched')}, line={result.get('matched_line','')[:60]}")

# ── SUMMARY ──
print("\n" + "=" * 70)
print(f"  Results: {PASS} passed, {FAIL} failed, {PASS+FAIL} total")
print("=" * 70)

sys.exit(1 if FAIL > 0 else 0)
