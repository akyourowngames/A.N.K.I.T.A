"""
Comprehensive tests for FileAgent Phase 2 tools.

Tests all 5 new advanced file operations:
1. pc_search - Search files across entire PC
2. trash_path - Move files to recycle bin
3. disk_analysis - Analyze disk usage
4. diff_files - Compare two files
5. bulk_op - Batch operations on multiple files
"""
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from tools import fs_ops


def test_pc_search():
    """Test PC-wide file search."""
    print("\n=== TEST 1: pc_search ===")
    
    # Search for Python files
    result = fs_ops.pc_search(query="*.py", max_results=10)
    
    assert "query" in result
    assert "count" in result
    assert "results" in result
    assert isinstance(result["results"], list)
    
    print(f"✓ Found {result['count']} Python files")
    if result["results"]:
        print(f"  First result: {result['results'][0]['name']}")
    
    # Search with file type filter
    result2 = fs_ops.pc_search(query="test", file_types=[".py"], max_results=5)
    assert result2["count"] >= 0
    print(f"✓ Found {result2['count']} test Python files")
    
    print("✓ pc_search works correctly")


def test_trash_path(workspace_root: Path):
    """Test moving files to recycle bin."""
    print("\n=== TEST 2: trash_path ===")
    
    # Create a test file
    test_file = workspace_root / "test_trash_file.txt"
    test_file.write_text("This file will be trashed")
    
    assert test_file.exists()
    
    # Trash the file
    result = fs_ops.trash_path(workspace_root, "test_trash_file.txt", unrestricted=False)
    
    assert "path" in result
    assert result["trashed"] is True
    assert "method" in result
    assert not test_file.exists()
    
    print(f"✓ File trashed using method: {result['method']}")
    print("✓ trash_path works correctly")


def test_disk_analysis(workspace_root: Path):
    """Test disk usage analysis."""
    print("\n=== TEST 3: disk_analysis ===")
    
    # Analyze current workspace
    result = fs_ops.disk_analysis(workspace_root, ".", unrestricted=False)
    
    assert "path" in result
    assert "total_size_bytes" in result
    assert "total_size_mb" in result
    assert "total_size_gb" in result
    assert "subdirectories" in result
    assert isinstance(result["subdirectories"], list)
    
    print(f"✓ Workspace size: {result['total_size_mb']} MB")
    print(f"✓ Found {len(result['subdirectories'])} subdirectories")
    if result["subdirectories"]:
        largest = result["subdirectories"][0]
        print(f"  Largest: {largest['name']} ({largest['size_mb']} MB)")
    
    print("✓ disk_analysis works correctly")


def test_diff_files(workspace_root: Path):
    """Test file comparison."""
    print("\n=== TEST 4: diff_files ===")
    
    # Create two test files with differences
    file1 = workspace_root / "test_diff1.txt"
    file2 = workspace_root / "test_diff2.txt"
    
    file1.write_text("Line 1\nLine 2\nLine 3\n")
    file2.write_text("Line 1\nLine 2 modified\nLine 3\nLine 4\n")
    
    # Compare files
    result = fs_ops.diff_files(workspace_root, "test_diff1.txt", "test_diff2.txt", unrestricted=False)
    
    assert "file1" in result
    assert "file2" in result
    assert "identical" in result
    assert result["identical"] is False
    assert "additions" in result
    assert "deletions" in result
    assert "diff" in result
    
    print(f"✓ Files are different: {result['additions']} additions, {result['deletions']} deletions")
    print(f"✓ Diff preview: {len(result['diff'])} chars")
    
    # Test identical files
    file3 = workspace_root / "test_diff3.txt"
    file3.write_text("Line 1\nLine 2\nLine 3\n")
    
    result2 = fs_ops.diff_files(workspace_root, "test_diff1.txt", "test_diff3.txt", unrestricted=False)
    assert result2["identical"] is True
    print("✓ Identical files detected correctly")
    
    # Cleanup
    file1.unlink()
    file2.unlink()
    file3.unlink()
    
    print("✓ diff_files works correctly")


def test_bulk_op(workspace_root: Path):
    """Test batch operations."""
    print("\n=== TEST 5: bulk_op ===")
    
    # Create test files
    test_dir = workspace_root / "test_bulk"
    test_dir.mkdir(exist_ok=True)
    
    files = []
    for i in range(5):
        f = test_dir / f"file{i}.txt"
        f.write_text(f"Content {i}")
        files.append(f"test_bulk/file{i}.txt")
    
    # Test bulk copy
    dest_dir = workspace_root / "test_bulk_dest"
    dest_dir.mkdir(exist_ok=True)
    
    result = fs_ops.bulk_op(
        workspace_root,
        operation="copy",
        paths=files[:3],  # Copy first 3 files
        destination="test_bulk_dest",
        unrestricted=False
    )
    
    assert result["operation"] == "copy"
    assert result["total"] == 3
    assert result["succeeded"] == 3
    assert result["failed"] == 0
    assert len(result["results"]) == 3
    
    print(f"✓ Bulk copy: {result['succeeded']}/{result['total']} succeeded")
    
    # Verify files were copied
    for i in range(3):
        assert (dest_dir / f"file{i}.txt").exists()
    
    # Test bulk delete
    result2 = fs_ops.bulk_op(
        workspace_root,
        operation="delete",
        paths=[f"test_bulk_dest/file{i}.txt" for i in range(3)],
        unrestricted=False
    )
    
    assert result2["succeeded"] == 3
    print(f"✓ Bulk delete: {result2['succeeded']}/{result2['total']} succeeded")
    
    # Test bulk trash
    result3 = fs_ops.bulk_op(
        workspace_root,
        operation="trash",
        paths=files,
        unrestricted=False
    )
    
    assert result3["succeeded"] == 5
    print(f"✓ Bulk trash: {result3['succeeded']}/{result3['total']} succeeded")
    
    # Cleanup
    import shutil
    if test_dir.exists():
        shutil.rmtree(test_dir)
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    
    print("✓ bulk_op works correctly")


def test_unrestricted_access():
    """Test unrestricted PC access for Phase 2 tools."""
    print("\n=== TEST 6: Unrestricted Access ===")
    
    # Test disk_analysis on home directory
    home = Path.home()
    result = fs_ops.disk_analysis(Path.cwd(), str(home), unrestricted=True)
    
    assert "total_size_mb" in result
    print(f"✓ Home directory size: {result['total_size_mb']} MB")
    
    # Test diff_files with absolute paths
    # Create temp files in home directory
    temp1 = home / "temp_test1.txt"
    temp2 = home / "temp_test2.txt"
    
    temp1.write_text("Test content 1")
    temp2.write_text("Test content 2")
    
    result2 = fs_ops.diff_files(Path.cwd(), str(temp1), str(temp2), unrestricted=True)
    assert result2["identical"] is False
    print("✓ Unrestricted diff_files works")
    
    # Cleanup
    temp1.unlink()
    temp2.unlink()
    
    print("✓ Unrestricted access works correctly")


def run_all_tests():
    """Run all Phase 2 tests."""
    print("=" * 60)
    print("FileAgent Phase 2 Tools - Comprehensive Test Suite")
    print("=" * 60)
    
    workspace_root = Path.cwd()
    
    try:
        test_pc_search()
        test_trash_path(workspace_root)
        test_disk_analysis(workspace_root)
        test_diff_files(workspace_root)
        test_bulk_op(workspace_root)
        test_unrestricted_access()
        
        print("\n" + "=" * 60)
        print("✓ ALL PHASE 2 TESTS PASSED!")
        print("=" * 60)
        return True
        
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
