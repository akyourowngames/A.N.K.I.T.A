"""
Stress test for FileAgent Full PC Access.
Tests performance, concurrency, and edge cases.
"""
import os
import sys
from pathlib import Path
import tempfile
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent))

from tools.engine import execute_tool_call


def test_large_directory_listing():
    """Test listing a directory with many files."""
    print("\n📊 STRESS TEST 1: Large directory listing")
    print("-" * 80)
    
    # Create a temp directory with many files
    temp_dir = Path(tempfile.gettempdir()) / "ankita_stress_large_dir"
    temp_dir.mkdir(exist_ok=True)
    
    try:
        # Create 100 test files
        print("Creating 100 test files...")
        for i in range(100):
            (temp_dir / f"test_file_{i:03d}.txt").write_text(f"Content {i}", encoding="utf-8")
        
        workspace_root = Path.cwd()
        tool_call = {
            "id": "stress_1",
            "function": {
                "name": "list_files",
                "arguments": f'{{"path": "{str(temp_dir).replace(chr(92), chr(92)*2)}", "max_entries": 200}}'
            }
        }
        
        start = time.time()
        result = execute_tool_call(tool_call, workspace_root, agent_name="FileAgent")
        elapsed = time.time() - start
        
        entries = result['result']['entries']
        print(f"✅ Listed {len(entries)} files in {elapsed:.3f}s")
        assert len(entries) == 100, f"Expected 100 files, got {len(entries)}"
        
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def test_deep_directory_structure():
    """Test accessing deeply nested directories."""
    print("\n🏔️  STRESS TEST 2: Deep directory structure")
    print("-" * 80)
    
    temp_dir = Path(tempfile.gettempdir()) / "ankita_stress_deep"
    temp_dir.mkdir(exist_ok=True)
    
    try:
        # Create a 10-level deep directory structure
        current = temp_dir
        for i in range(10):
            current = current / f"level_{i}"
            current.mkdir(exist_ok=True)
        
        # Create a file at the deepest level
        deep_file = current / "deep_file.txt"
        deep_file.write_text("Found me at the bottom!", encoding="utf-8")
        
        workspace_root = Path.cwd()
        tool_call = {
            "id": "stress_2",
            "function": {
                "name": "read_file",
                "arguments": f'{{"path": "{str(deep_file).replace(chr(92), chr(92)*2)}"}}'
            }
        }
        
        start = time.time()
        result = execute_tool_call(tool_call, workspace_root, agent_name="FileAgent")
        elapsed = time.time() - start
        
        content = result['result']['content']
        print(f"✅ Read file from 10-level deep directory in {elapsed:.3f}s")
        assert "Found me" in content
        
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def test_concurrent_operations():
    """Test multiple concurrent file operations."""
    print("\n⚡ STRESS TEST 3: Concurrent file operations")
    print("-" * 80)
    
    temp_dir = Path(tempfile.gettempdir()) / "ankita_stress_concurrent"
    temp_dir.mkdir(exist_ok=True)
    
    try:
        # Create 20 test files
        for i in range(20):
            (temp_dir / f"concurrent_{i:02d}.txt").write_text(f"Content {i}", encoding="utf-8")
        
        workspace_root = Path.cwd()
        
        # Create 20 concurrent read operations
        def read_file(i):
            tool_call = {
                "id": f"concurrent_{i}",
                "function": {
                    "name": "read_file",
                    "arguments": f'{{"path": "{str(temp_dir / f"concurrent_{i:02d}.txt").replace(chr(92), chr(92)*2)}"}}'
                }
            }
            return execute_tool_call(tool_call, workspace_root, agent_name="FileAgent")
        
        start = time.time()
        with ThreadPoo