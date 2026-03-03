"""Quick test of the bug fixes"""
from tools.content_ops import write_and_save_content
from pathlib import Path

print("Testing content_ops.py fixes...\n")

# Test 1: Check already_saved flag
print("Test 1: already_saved flag")
result = write_and_save_content(Path.cwd(), "test topic", "paragraph", "")
print(f"  already_saved: {result.get('already_saved')}")
print(f"  Status: {'PASS' if result.get('already_saved') == True else 'FAIL'}\n")

# Test 2: Check .md format for reports
print("Test 2: .md format for reports")
result = write_and_save_content(Path.cwd(), "test report", "report", "")
path = result.get('absolute_path', '')
ext = path.split('.')[-1] if path else ''
print(f"  Extension: {ext}")
print(f"  Status: {'PASS' if ext == 'md' else 'FAIL'}\n")

# Test 3: Check .txt format for poems
print("Test 3: .txt format for poems")
result = write_and_save_content(Path.cwd(), "test poem", "poem", "")
path = result.get('absolute_path', '')
ext = path.split('.')[-1] if path else ''
print(f"  Extension: {ext}")
print(f"  Status: {'PASS' if ext == 'txt' else 'FAIL'}\n")

# Test 4: Check path normalization (backslashes)
print("Test 4: Path normalization")
result = write_and_save_content(Path.cwd(), "test path", "note", "")
path = result.get('absolute_path', '')
has_backslash = '\\' in path
has_forward_slash = '/' in path
print(f"  Path: {path[:50]}...")
print(f"  Has backslashes: {has_backslash}")
print(f"  Has forward slashes: {has_forward_slash}")
print(f"  Status: {'PASS' if has_backslash and not has_forward_slash else 'FAIL'}\n")

print("All content_ops.py tests complete!")
