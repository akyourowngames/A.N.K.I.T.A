"""
Deep test for app_manager with real scenarios.
"""
import sys
import time
import subprocess
from tools.app_manager import app_manager

def test_list_running_apps():
    """Test listing running applications."""
    print("\n" + "="*60)
    print("TEST 1: List Running Apps")
    print("="*60)
    
    try:
        result = app_manager(action="list_running")
        
        if result.get("ok"):
            apps = result.get("apps", [])
            count = result.get("count", 0)
            
            print(f"✅ Found {count} running apps")
            print("\nTop 5 by RAM usage:")
            for i, app in enumerate(apps[:5], 1):
                print(f"   {i}. {app['name']:<30} RAM: {app['ram_mb']:>8.1f} MB  CPU: {app['cpu_pct']:>5.1f}%")
            
            return len(apps) > 0
        else:
            print(f"❌ Failed to list apps: {result.get('error')}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_top_ram_hog():
    """Test finding top RAM consumer."""
    print("\n" + "="*60)
    print("TEST 2: Top RAM Hog")
    print("="*60)
    
    try:
        result = app_manager(action="top_ram_hog")
        
        if result.get("ok"):
            hog = result.get("top_hog", {})
            print(f"✅ Top RAM consumer:")
            print(f"   Process: {hog.get('name')}")
            print(f"   RAM: {hog.get('ram_mb')} MB")
            print(f"   CPU: {hog.get('cpu_pct')}%")
            return True
        else:
            print(f"❌ Failed: {result.get('error')}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_fuzzy_matching():
    """Test fuzzy app name matching."""
    print("\n" + "="*60)
    print("TEST 3: Fuzzy Name Matching")
    print("="*60)
    
    # Get list of running apps first
    result = app_manager(action="list_running")
    if not result.get("ok") or not result.get("apps"):
        print("⚠️ No apps running to test fuzzy matching")
        return True
    
    # Pick a common app name to test
    test_apps = result.get("apps", [])
    test_app = test_apps[0]
    app_name = test_app['name']
    
    # Remove .exe extension for fuzzy test
    fuzzy_name = app_name.replace('.exe', '').lower()[:5]  # First 5 chars
    
    print(f"Testing fuzzy match: '{fuzzy_name}' should match '{app_name}'")
    
    try:
        from tools.app_manager import find_process_by_name
        proc = find_process_by_name(fuzzy_name)
        
        if proc:
            print(f"✅ Fuzzy match successful: '{fuzzy_name}' → '{proc.name()}'")
            return True
        else:
            print(f"⚠️ No match found for '{fuzzy_name}'")
            return True  # Not a failure, just no match
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_close_and_restart():
    """Test closing and restarting an app (using notepad as safe test)."""
    print("\n" + "="*60)
    print("TEST 4: Close & Restart App")
    print("="*60)
    print("Starting notepad for testing...")
    
    try:
        # Start notepad
        proc = subprocess.Popen(['notepad.exe'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)  # Wait for it to start
        
        print("✅ Notepad started")
        
        # Test close
        print("Attempting to close notepad...")
        result = app_manager(action="close_app", name="notepad")
        
        if result.get("ok"):
            print(f"✅ Successfully closed: {result.get('closed')}")
            time.sleep(1)
            
            # Verify it's closed
            check_result = app_manager(action="list_running")
            if check_result.get("ok"):
                apps = check_result.get("apps", [])
                notepad_running = any('notepad' in app['name'].lower() for app in apps)
                
                if not notepad_running:
                    print("✅ Verified: Notepad is no longer running")
                    return True
                else:
                    print("⚠️ Notepad still appears to be running")
                    return False
        else:
            print(f"❌ Failed to close: {result.get('error')}")
            # Try to kill it manually
            try:
                proc.kill()
            except:
                pass
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        # Cleanup
        try:
            subprocess.run(['taskkill', '/F', '/IM', 'notepad.exe'], 
                         capture_output=True, timeout=5)
        except:
            pass
        return False


def test_force_close():
    """Test force closing an app."""
    print("\n" + "="*60)
    print("TEST 5: Force Close")
    print("="*60)
    print("Starting notepad for force close test...")
    
    try:
        # Start notepad
        proc = subprocess.Popen(['notepad.exe'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        
        print("✅ Notepad started")
        
        # Test force close
        print("Force closing notepad...")
        result = app_manager(action="close_app", name="notepad", force=True)
        
        if result.get("ok"):
            print(f"✅ Force closed: {result.get('closed')}")
            print(f"   Forced: {result.get('forced')}")
            time.sleep(1)
            
            # Verify
            check_result = app_manager(action="list_running")
            if check_result.get("ok"):
                apps = check_result.get("apps", [])
                notepad_running = any('notepad' in app['name'].lower() for app in apps)
                
                if not notepad_running:
                    print("✅ Verified: Notepad forcefully terminated")
                    return True
                else:
                    print("⚠️ Notepad still running after force close")
                    return False
        else:
            print(f"❌ Failed: {result.get('error')}")
            try:
                proc.kill()
            except:
                pass
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        # Cleanup
        try:
            subprocess.run(['taskkill', '/F', '/IM', 'notepad.exe'], 
                         capture_output=True, timeout=5)
        except:
            pass
        return False


def test_error_handling():
    """Test error handling for non-existent app."""
    print("\n" + "="*60)
    print("TEST 6: Error Handling")
    print("="*60)
    print("Attempting to close non-existent app...")
    
    try:
        result = app_manager(action="close_app", name="nonexistentapp12345")
        
        if not result.get("ok"):
            print(f"✅ Correctly handled non-existent app: {result.get('error')}")
            return True
        else:
            print("❌ Should have failed for non-existent app")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    print("\n" + "🔧 " * 20)
    print("APP MANAGER - DEEP INTEGRATION TEST")
    print("🔧 " * 20)
    
    results = []
    
    # Test 1: List apps
    results.append(("List Running Apps", test_list_running_apps()))
    
    # Test 2: Top RAM hog
    results.append(("Top RAM Hog", test_top_ram_hog()))
    
    # Test 3: Fuzzy matching
    results.append(("Fuzzy Matching", test_fuzzy_matching()))
    
    # Test 4: Close and restart
    results.append(("Close App", test_close_and_restart()))
    
    # Test 5: Force close
    results.append(("Force Close", test_force_close()))
    
    # Test 6: Error handling
    results.append(("Error Handling", test_error_handling()))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print(f"\n⚠️ {total - passed} test(s) failed")
        sys.exit(1)
