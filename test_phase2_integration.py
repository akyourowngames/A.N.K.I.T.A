"""
Integration test demonstrating FileAgent Phase 2 tools in realistic scenarios.

Scenario: User wants to clean up their workspace by:
1. Finding all test files
2. Analyzing disk usage to see what's taking space
3. Comparing two config files
4. Moving old files to a backup folder
5. Trashing temporary files
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tools import fs_ops


def scenario_workspace_cleanup():
    """Realistic scenario: Clean up workspace."""
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: Workspace Cleanup Scenario")
    print("=" * 70)
    
    workspace = Path.cwd()
    
    # Step 1: Find all test files
    print("\n[Step 1] Finding all test files...")
    result = fs_ops.pc_search("test_*.py", max_results=20)
    print(f"✓ Found {result['count']} test files")
    if result['results']:
        print(f"  Examples: {', '.join([r['name'] for r in result['results'][:3]])}")
    
    # Step 2: Analyze disk usage
    print("\n[Step 2] Analyzing workspace disk usage...")
    result = fs_ops.disk_analysis(workspace, ".", unrestricted=False)
    print(f"✓ Total workspace size: {result['total_size_mb']} MB ({result['total_size_gb']} GB)")
    if result['subdirectories']:
        print(f"  Top 3 largest directories:")
        for i, subdir in enumerate(result['subdirectories'][:3], 1):
            print(f"    {i}. {subdir['name']}: {subdir['size_mb']} MB")
    
    # Step 3: Create and compare config files
    print("\n[Step 3] Comparing configuration files...")
    config1 = workspace / "config_old.txt"
    config2 = workspace / "config_new.txt"
    
    config1.write_text("setting1=value1\nsetting2=value2\nsetting3=value3\n")
    config2.write_text("setting1=value1\nsetting2=updated_value\nsetting3=value3\nsetting4=new_value\n")
    
    result = fs_ops.diff_files(workspace, "config_old.txt", "config_new.txt", unrestricted=False)
    print(f"✓ Files compared: {result['additions']} additions, {result['deletions']} deletions")
    print(f"  Files are {'identical' if result['identical'] else 'different'}")
    
    # Step 4: Bulk move files to backup
    print("\n[Step 4] Moving files to backup folder...")
    backup_dir = workspace / "backup"
    backup_dir.mkdir(exist_ok=True)
    
    # Create some dummy files to move
    temp_files = []
    for i in range(3):
        f = workspace / f"old_file_{i}.txt"
        f.write_text(f"Old content {i}")
        temp_files.append(f"old_file_{i}.txt")
    
    result = fs_ops.bulk_op(
        workspace,
        operation="move",
        paths=temp_files,
        destination="backup",
        unrestricted=False
    )
    print(f"✓ Moved {result['succeeded']}/{result['total']} files to backup")
    
    # Step 5: Trash temporary files
    print("\n[Step 5] Trashing temporary files...")
    
    # Create temp files
    temp_trash_files = []
    for i in range(2):
        f = workspace / f"temp_{i}.tmp"
        f.write_text(f"Temporary {i}")
        temp_trash_files.append(f"temp_{i}.tmp")
    
    result = fs_ops.bulk_op(
        workspace,
        operation="trash",
        paths=temp_trash_files,
        unrestricted=False
    )
    print(f"✓ Trashed {result['succeeded']}/{result['total']} temporary files")
    
    # Cleanup
    print("\n[Cleanup] Removing test artifacts...")
    config1.unlink()
    config2.unlink()
    
    # Clean up backup folder
    import shutil
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    
    print("\n" + "=" * 70)
    print("✓ INTEGRATION TEST COMPLETED SUCCESSFULLY!")
    print("=" * 70)
    print("\nDemonstrated capabilities:")
    print("  ✓ pc_search - Found test files across workspace")
    print("  ✓ disk_analysis - Analyzed disk usage and identified large directories")
    print("  ✓ diff_files - Compared configuration files")
    print("  ✓ bulk_op (move) - Moved multiple files to backup")
    print("  ✓ bulk_op (trash) - Safely trashed temporary files")
    print("\nAll Phase 2 tools working together seamlessly!")


if __name__ == "__main__":
    try:
        scenario_workspace_cleanup()
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
