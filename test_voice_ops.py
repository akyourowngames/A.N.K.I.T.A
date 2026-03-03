"""
Deep test for voice_ops with real scenarios.
"""
import sys
import time
from tools.voice_ops import voice_control

def test_list_voices():
    """Test listing available TTS voices."""
    print("\n" + "="*60)
    print("TEST 1: List Available Voices")
    print("="*60)
    
    try:
        result = voice_control(action="list_voices")
        
        if result.get("ok"):
            voices = result.get("voices", [])
            count = result.get("count", 0)
            
            print(f"✅ Found {count} TTS voice(s)")
            for i, voice in enumerate(voices, 1):
                print(f"   {i}. {voice}")
            
            return count > 0
        else:
            print(f"❌ Failed: {result.get('error')}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_speak_basic():
    """Test basic text-to-speech."""
    print("\n" + "="*60)
    print("TEST 2: Basic Speech")
    print("="*60)
    print("Speaking: 'Hello, this is a test'")
    print("(You should hear audio output)")
    
    try:
        result = voice_control(
            action="speak",
            text="Hello, this is a test",
            rate=150,
            volume=100
        )
        
        if result.get("ok"):
            print(f"✅ Speech successful")
            print(f"   Text: {result.get('spoke')}")
            print(f"   Rate: {result.get('rate')}")
            print(f"   Volume: {result.get('volume')}")
            return True
        else:
            print(f"❌ Failed: {result.get('error')}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_speak_fast():
    """Test fast speech rate."""
    print("\n" + "="*60)
    print("TEST 3: Fast Speech Rate")
    print("="*60)
    print("Speaking fast: 'This is a fast speech test'")
    
    try:
        result = voice_control(
            action="speak",
            text="This is a fast speech test",
            rate=200,  # Fast
            volume=100
        )
        
        if result.get("ok"):
            print(f"✅ Fast speech successful")
            return True
        else:
            print(f"❌ Failed: {result.get('error')}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_speak_slow():
    """Test slow speech rate."""
    print("\n" + "="*60)
    print("TEST 4: Slow Speech Rate")
    print("="*60)
    print("Speaking slowly: 'This is a slow speech test'")
    
    try:
        result = voice_control(
            action="speak",
            text="This is a slow speech test",
            rate=100,  # Slow
            volume=100
        )
        
        if result.get("ok"):
            print(f"✅ Slow speech successful")
            return True
        else:
            print(f"❌ Failed: {result.get('error')}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_speak_quiet():
    """Test low volume."""
    print("\n" + "="*60)
    print("TEST 5: Low Volume")
    print("="*60)
    print("Speaking quietly: 'This is a quiet test'")
    
    try:
        result = voice_control(
            action="speak",
            text="This is a quiet test",
            rate=150,
            volume=30  # Quiet
        )
        
        if result.get("ok"):
            print(f"✅ Quiet speech successful")
            return True
        else:
            print(f"❌ Failed: {result.get('error')}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_special_characters():
    """Test speech with special characters."""
    print("\n" + "="*60)
    print("TEST 6: Special Characters")
    print("="*60)
    
    test_text = "Testing special chars: quotes, apostrophes, and symbols!"
    print(f"Speaking: '{test_text}'")
    
    try:
        result = voice_control(
            action="speak",
            text=test_text,
            rate=150,
            volume=100
        )
        
        if result.get("ok"):
            print(f"✅ Special characters handled correctly")
            return True
        else:
            print(f"❌ Failed: {result.get('error')}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_long_text():
    """Test speech with longer text."""
    print("\n" + "="*60)
    print("TEST 7: Long Text")
    print("="*60)
    
    long_text = (
        "This is a longer text to test the text to speech system. "
        "It contains multiple sentences and should be spoken clearly. "
        "The system should handle this without any issues."
    )
    print(f"Speaking long text ({len(long_text)} characters)...")
    
    try:
        result = voice_control(
            action="speak",
            text=long_text,
            rate=150,
            volume=100
        )
        
        if result.get("ok"):
            print(f"✅ Long text spoken successfully")
            return True
        else:
            print(f"❌ Failed: {result.get('error')}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_error_handling():
    """Test error handling for invalid action."""
    print("\n" + "="*60)
    print("TEST 8: Error Handling")
    print("="*60)
    print("Testing invalid action...")
    
    try:
        result = voice_control(action="invalid_action")
        
        if not result.get("ok"):
            print(f"✅ Correctly rejected invalid action: {result.get('error')}")
            return True
        else:
            print("❌ Should have rejected invalid action")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    print("\n" + "🔊 " * 20)
    print("VOICE CONTROL - DEEP INTEGRATION TEST")
    print("🔊 " * 20)
    print("\n⚠️  NOTE: You should hear audio output during these tests")
    print("If you don't hear anything, check your system volume\n")
    
    time.sleep(2)  # Give user time to read
    
    results = []
    
    # Test 1: List voices
    results.append(("List Voices", test_list_voices()))
    time.sleep(1)
    
    # Test 2: Basic speech
    results.append(("Basic Speech", test_speak_basic()))
    time.sleep(2)
    
    # Test 3: Fast speech
    results.append(("Fast Speech", test_speak_fast()))
    time.sleep(2)
    
    # Test 4: Slow speech
    results.append(("Slow Speech", test_speak_slow()))
    time.sleep(2)
    
    # Test 5: Quiet speech
    results.append(("Low Volume", test_speak_quiet()))
    time.sleep(2)
    
    # Test 6: Special characters
    results.append(("Special Characters", test_special_characters()))
    time.sleep(2)
    
    # Test 7: Long text
    results.append(("Long Text", test_long_text()))
    time.sleep(2)
    
    # Test 8: Error handling
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
