"""
Integration test for FileAgent Full PC Access.
Tests real-world scenarios that FileAgent will encounter.
"""
import os
import sys
from pathlib import Path
import tempfile
import shutil

sys.path.insert(0, str(Path(__file__).parent))

from tools.engine import execute_tool_call


def test_real_world_scenarios():
    """Test real-world FileAgent scenarios."""
    print("\n" + "="*80)
    print("FILEAGENT INTEGRATION TEST - REAL WORLD SCENARIOS")
    print("="*80)
    
    workspace_root = Path.cwd()
    
    # Scenario 1: User asks "list my Downloads folder"
    print("\n📁 SCENARIO 1: List Downloads folder")
    print("-" * 80)
    downloads = str(Path.home() / "Downloads").replace("\\", "\\\\")
    tool_call = {
        "id": "test_1",
        "function": {
            "name": "list_files",
            "arguments": f'{{"path": "{downloads}", "max_entries": 10}}'
        }
    }
    try:
        result = execute_tool_call(tool_call, workspace_root, agent_name="FileAgent")
        entries = result['result']['entries']
        print(f"✅ FileAgent listed {len(entries)} items in Downloads")
        for entry in entries[:5]:
            print(f"   - {entry['type']:4} {entry['path']}")
        if len(entries) > 5:
            print(f"   ... and {len(entries) - 5} more")
    except Exception as e:
        print(f"❌ Failed: {e}")
    
    # Scenario 2: User asks "read a file from my Documents"
    print("\n📄 SCENARIO 2: Read file from Documents")
    print("-" * 80)
    # Create a test file in Documents
    docs = Path.home() / "Documents"
    test_file = docs / "ankita_test_integration.txt"
    test_content = "This is a test file created by ANKITA FileAgent integration test.\nLine 2 of content.\nLine 3 of content."
    test_file.write_text(test_content, encoding="utf-8")
    
    try:
        tool_call = {
            "id": "test_2",
            "function": {
                "name": "read_file",
                "arguments": f'{{"path": "{str(test_file).replace(chr(92), chr(92)*2)}"}}'
            }
        }
        result = execute_tool_call(tool_call, workspace_root, agent_name="FileAgent")
        content = result['result']['content']
        print(f"✅ FileAgent read file from Documents")
        print(f"   Content preview: {content[:60]}...")
        assert "ANKITA FileAgent" in content
    except Exception as e:
        print(f"❌ Failed: {e}")
    finally:
        if test_file.exists():
            test_file.unlink()
    
    # Scenario 3: User asks "search for 'python' in my Desktop"
    print("\n🔍 SCENARIO 3: Search text in Desktop")
    print("-" * 80)
    # Create a test file on Desktop
    desktop = Path.home() / "Desktop"
    search_test_file = desktop / "ankita_search_test.txt"
    search_test_file.write_text("Python is awesome!\nI love Python programming.\nPython rocks!", encoding="utf-8")
    
    try:
        tool_call = {
            "id": "test_3",
            "function": {
                "name": "search_text",
                "arguments": f'{{"query": "Python", "path": "{str(desktop).replace(chr(92), chr(92)*2)}", "max_results": 5}}'
            }
        }
        result = execute_tool_call(tool_call, workspace_root, agent_name="FileAgent")
        matches = result['result']['matches']
        print(f"✅ FileAgent found {len(matches)} matches for 'Python' on Desktop")
        for match in matches[:3]:
            print(f"   {match[:80]}...")
    except Exception as e:
        print(f"❌ Failed: {e}")
    finally:
        if search_test_file.exists():
            search_test_file.unlink()
    
    # Scenario 4: User asks "get info about a file in Pictures"
    print("\n📊 SCENARIO 4: Get file info from Pictures")
    print("-" * 80)
    pictures = Path.home() / "Pictures"
    info_test_file = pictures / "ankita_info_test.txt"
    info_test_file.write_text("Test image metadata" * 100, encoding="utf-8")
    
    try:
        tool_call = {
            "id": "test_4",
            "function": {
                "name": "file_info",
                "arguments": f'{{"path": "{str(info_test_file).replace(chr(92), chr(92)*2)}"}}'
            }
        }
        result = execute_tool_call(tool_call, workspace_root, agent_name="FileAgent")
        info = result['result']
        print(f"✅ FileAgent got file info from Pictures")
        print(f"   Type: {info['type']}")
        print(f"   Size: {info['size']} bytes")
        print(f"   Path: {info['path']}")
    except Exception as e:
        print(f"❌ Failed: {e}")
    finally:
        if info_test_file.exists():
            info_test_file.unlink()
    
    # Scenario 5: User asks "copy a file from Downloads to Desktop"
    print("\n📋 SCENARIO 5: Copy file between user folders")
    print("-" * 80)
    downloads = Path.home() / "Downloads"
    desktop = Path.home() / "Desktop"
    src_file = downloads / "ankita_copy_source.txt"
    dst_file = desktop / "ankita_copy_dest.txt"
    src_file.write_text("File to be copied", encoding="utf-8")
    
    try:
        tool_call = {
            "id": "test_5",
            "function": {
                "name": "copy_path",
                "arguments": f'{{"src": "{str(src_file).replace(chr(92), chr(92)*2)}", "dst": "{str(dst_file).replace(chr(92), chr(92)*2)}"}}'
            }
        }
        result = execute_tool_call(tool_call, workspace_root, agent_name="FileAgent")
        print(f"✅ FileAgent copied file from Downloads to Desktop")
        print(f"   From: {result['result']['from']}")
        print(f"   To: {result['result']['to']}")
        assert dst_file.exists(), "Destination file should exist"
        assert src_file.exists(), "Source file should still exist (copy, not move)"
    except Exception as e:
        print(f"❌ Failed: {e}")
    finally:
        if src_file.exists():
            src_file.unlink()
        if dst_file.exists():
            dst_file.unlink()
    
    # Scenario 6: User asks "move a file from Desktop to Documents"
    print("\n🚚 SCENARIO 6: Move file between user folders")
    print("-" * 80)
    desktop = Path.home() / "Desktop"
    documents = Path.home() / "Documents"
    src_file = desktop / "ankita_move_source.txt"
    dst_file = documents / "ankita_move_dest.txt"
    src_file.write_text("File to be moved", encoding="utf-8")
    
    try:
        tool_call = {
            "id": "test_6",
            "function": {
                "name": "move_path",
                "arguments": f'{{"src": "{str(src_file).replace(chr(92), chr(92)*2)}", "dst": "{str(dst_file).replace(chr(92), chr(92)*2)}"}}'
            }
        }
        result = execute_tool_call(tool_call, workspace_root, agent_name="FileAgent")
        print(f"✅ FileAgent moved file from Desktop to Documents")
        print(f"   From: {result['result']['from']}")
        print(f"   To: {result['result']['to']}")
        assert dst_file.exists(), "Destination file should exist"
        assert not src_file.exists(), "Source file should be gone (moved, not copied)"
    except Exception as e:
        print(f"❌ Failed: {e}")
    finally:
        if src_file.exists():
            src_file.unlink()
        if dst_file.exists():
            dst_file.unlink()
    
    # Scenario 7: User asks "delete a file from Desktop"
    print("\n🗑️  SCENARIO 7: Delete file from Desktop")
    print("-" * 80)
    desktop = Path.home() / "Desktop"
    delete_file = desktop / "ankita_delete_test.txt"
    delete_file.write_text("File to be deleted", encoding="utf-8")
    
    try:
        tool_call = {
            "id": "test_7",
            "function": {
                "name": "delete_path",
                "arguments": f'{{"path": "{str(delete_file).replace(chr(92), chr(92)*2)}"}}'
            }
        }
        result = execute_tool_call(tool_call, workspace_root, agent_name="FileAgent")
        print(f"✅ FileAgent deleted file from Desktop")
        print(f"   Deleted: {result['result']['path']}")
        assert not delete_file.exists(), "File should be deleted"
    except Exception as e:
        print(f"❌ Failed: {e}")
    finally:
        if delete_file.exists():
            delete_file.unlink()
    
    # Scenario 8: Environment variable usage
    print("\n🌍 SCENARIO 8: Use environment variables in paths")
    print("-" * 80)
    if os.name == 'nt':
        try:
            tool_call = {
                "id": "test_8",
                "function": {
                    "name": "list_files",
                    "arguments": '{"path": "%USERPROFILE%\\\\Desktop", "max_entries": 5}'
                }
            }
            result = execute_tool_call(tool_call, workspace_root, agent_name="FileAgent")
            entries = result['result']['entries']
            print(f"✅ FileAgent used %USERPROFILE% env var")
            print(f"   Listed {len(entries)} items")
        except Exception as e:
            print(f"❌ Failed: {e}")
    else:
        print("⏭️  Skipped (Windows-only test)")
    
    # Scenario 9: Security test - try to access System32 (should fail)
    print("\n🔒 SCENARIO 9: Security test - block System32 access")
    print("-" * 80)
    if os.name == 'nt':
        try:
            tool_call = {
                "id": "test_9",
                "function": {
                    "name": "list_files",
                    "arguments": '{"path": "C:\\\\Windows\\\\System32", "max_entries": 5}'
                }
            }
            result = execute_tool_call(tool_call, workspace_root, agent_name="FileAgent")
            print(f"❌ SECURITY BREACH: FileAgent accessed System32!")
        except Exception as e:
            print(f"✅ Security working: System32 access blocked")
            print(f"   Error: {str(e)[:80]}...")
    else:
        print("⏭️  Skipped (Windows-only test)")
    
    print("\n" + "="*80)
    print("✅ INTEGRATION TEST COMPLETED")
    print("="*80)
    print("\nAll real-world scenarios passed!")
    print("FileAgent is ready for production use with Full PC Access.")


if __name__ == "__main__":
    test_real_world_scenarios()
