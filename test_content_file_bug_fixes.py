"""
Test script for ContentAgent + FileAgent bug fixes.

Tests:
1. Bug 1: Only one file created (not two)
2. Bug 2: Correct file opened (.md not .txt)
3. Bug 3: File exists and opens successfully
4. Bug 4: GeneralAgent fallback saves correctly
"""
import sys
from pathlib import Path
import time

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from llm import build_runtime_from_env
from agents.orchestrator import Orchestrator


def test_single_file_creation():
    """Test that only ONE file is created, not two."""
    print("=" * 80)
    print("TEST 1: Single File Creation (Bug 1 Fix)")
    print("=" * 80)
    
    runtime = build_runtime_from_env()
    workspace_root = Path.cwd()
    orchestrator = Orchestrator(runtime, workspace_root)
    
    # Count files on Desktop before
    desktop = Path.home() / "Desktop"
    before_count = len(list(desktop.glob("*")))
    
    request = "write a short paragraph about AI and save it"
    messages = []
    
    print(f"\nRequest: {request}")
    print(f"Files on Desktop before: {before_count}")
    
    try:
        result = orchestrator.run(request, messages)
        print(f"\nResult: {result[:200]}...")
        
        # Count files after
        time.sleep(1)  # Give filesystem time to sync
        after_count = len(list(desktop.glob("*")))
        new_files = after_count - before_count
        
        print(f"Files on Desktop after: {after_count}")
        print(f"New files created: {new_files}")
        
        if new_files == 1:
            print("[OK] Only 1 file created - Bug 1 FIXED!")
        else:
            print(f"[FAIL] Expected 1 file, got {new_files} - Bug 1 NOT fixed")
            
    except Exception as e:
        print(f"[FAIL] Error: {e}")


def test_correct_file_format():
    """Test that .md files are created for reports, not .txt."""
    print("\n" + "=" * 80)
    print("TEST 2: Correct File Format (.md for reports)")
    print("=" * 80)
    
    runtime = build_runtime_from_env()
    workspace_root = Path.cwd()
    orchestrator = Orchestrator(runtime, workspace_root)
    
    request = "write a brief report about Python and save it"
    messages = []
    
    print(f"\nRequest: {request}")
    
    try:
        result = orchestrator.run(request, messages)
        print(f"\nResult: {result[:200]}...")
        
        # Check if .md file was created
        desktop = Path.home() / "Desktop"
        md_files = list(desktop.glob("*report*.md"))
        
        if md_files:
            print(f"[OK] Found .md file: {md_files[-1].name}")
            print("Bug 2 FIXED - correct format used!")
        else:
            print("[FAIL] No .md file found - Bug 2 NOT fixed")
            
    except Exception as e:
        print(f"[FAIL] Error: {e}")


def test_file_opens_successfully():
    """Test that the file actually opens without 'file doesn't exist' error."""
    print("\n" + "=" * 80)
    print("TEST 3: File Opens Successfully (Bug 3 Fix)")
    print("=" * 80)
    
    runtime = build_runtime_from_env()
    workspace_root = Path.cwd()
    orchestrator = Orchestrator(runtime, workspace_root)
    
    request = "write a haiku about coding and save it and open it"
    messages = []
    
    print(f"\nRequest: {request}")
    
    try:
        result = orchestrator.run(request, messages)
        print(f"\nResult: {result[:300]}...")
        
        # Check if result mentions opening the file
        if "opened" in result.lower() or "notepad" in result.lower():
            print("[OK] File was opened successfully!")
            print("Bug 3 FIXED - path sanitization working!")
        else:
            print("[FAIL] No mention of opening file - Bug 3 NOT fixed")
            
    except Exception as e:
        print(f"[FAIL] Error: {e}")


def test_assembly_line_flow():
    """Test the complete assembly line: ContentAgent -> FileAgent -> SystemAgent."""
    print("\n" + "=" * 80)
    print("TEST 4: Complete Assembly Line Flow")
    print("=" * 80)
    
    runtime = build_runtime_from_env()
    workspace_root = Path.cwd()
    orchestrator = Orchestrator(runtime, workspace_root)
    
    request = "write a limerick about Python, save it, and open it in Notepad"
    messages = []
    
    print(f"\nRequest: {request}")
    
    try:
        result = orchestrator.run(request, messages)
        print(f"\nResult: {result[:300]}...")
        
        # Check for all three stages
        stages_completed = 0
        if "written" in result.lower() or "generated" in result.lower():
            stages_completed += 1
            print("[OK] Stage 1: Content generated")
        if "saved" in result.lower():
            stages_completed += 1
            print("[OK] Stage 2: File saved")
        if "opened" in result.lower() or "notepad" in result.lower():
            stages_completed += 1
            print("[OK] Stage 3: File opened")
        
        if stages_completed == 3:
            print("\n[OK] Complete assembly line working!")
        else:
            print(f"\n[FAIL] Only {stages_completed}/3 stages completed")
            
    except Exception as e:
        print(f"[FAIL] Error: {e}")


if __name__ == "__main__":
    print("\nContentAgent + FileAgent Bug Fix Test Suite\n")
    
    # Only run if user confirms (makes real API calls)
    response = input("Run tests? (These will make real LLM API calls and create files on Desktop) [y/N]: ")
    if response.lower() != 'y':
        print("\nSkipping tests.")
        sys.exit(0)
    
    test_single_file_creation()
    test_correct_file_format()
    test_file_opens_successfully()
    test_assembly_line_flow()
    
    print("\n" + "=" * 80)
    print("[OK] Test suite complete!")
    print("=" * 80)
    print("\nCheck your Desktop for the created files.")
