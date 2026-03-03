"""
Quick test to verify new tools are properly integrated.
"""
from pathlib import Path
from tools.engine import TOOL_SPECS, _call

def test_tool_specs():
    """Verify all new tools are registered in TOOL_SPECS."""
    tool_names = {spec["function"]["name"] for spec in TOOL_SPECS}
    
    new_tools = [
        "camera_control",
        "app_manager",
        "voice_control",
        "system_health",
        "file_sync"
    ]
    
    print("Checking tool registration...")
    for tool in new_tools:
        if tool in tool_names:
            print(f"✅ {tool} - registered")
        else:
            print(f"❌ {tool} - NOT FOUND")
    
    print(f"\nTotal tools registered: {len(tool_names)}")
    return all(tool in tool_names for tool in new_tools)


def test_tool_calls():
    """Test that tool calls can be dispatched."""
    workspace_root = Path.cwd()
    
    test_cases = [
        ("app_manager", {"action": "list_running"}),
        ("system_health", {"action": "disk_health"}),
        ("voice_control", {"action": "list_voices"}),
    ]
    
    print("\nTesting tool dispatch...")
    for tool_name, args in test_cases:
        try:
            result = _call(tool_name, args, workspace_root)
            status = "✅" if result.get("ok") else "⚠️"
            print(f"{status} {tool_name}({args['action']}) - {result.get('ok', False)}")
        except Exception as e:
            print(f"❌ {tool_name}({args['action']}) - Error: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("ANKITA New Tools Integration Test")
    print("=" * 60)
    
    specs_ok = test_tool_specs()
    test_tool_calls()
    
    print("\n" + "=" * 60)
    if specs_ok:
        print("✅ All new tools successfully integrated!")
    else:
        print("⚠️ Some tools missing from registration")
    print("=" * 60)
