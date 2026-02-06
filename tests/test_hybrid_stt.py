"""
Test the Hybrid STT Setup (Vosk + Faster-Whisper)

This script verifies that:
1. Vosk is properly loaded for passive listening
2. Faster-Whisper is properly loaded for commands
3. The audio pipeline works correctly

Usage:
    python test_hybrid_stt.py
"""

import os
import sys
import time
import numpy as np

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ankita.context import Mode, get_context_manager, get_command_listener
from ankita.context.passive_listener import get_passive_listener


def test_vosk_availability():
    """Test if Vosk is available."""
    print("\n" + "="*50)
    print("TEST 1: Vosk Model Loading")
    print("="*50)
    
    listener = get_passive_listener()
    vosk = listener._load_vosk()
    
    if vosk is not None:
        print("✅ Vosk model loaded successfully!")
        print("   This will be used for passive listening (zero hallucination)")
        return True
    else:
        print("❌ Vosk not available")
        print("   Install with: pip install vosk")
        print("   Download model from: https://alphacephei.com/vosk/models")
        print("   Recommended: vosk-model-small-en-us-0.15")
        return False


def test_whisper_availability():
    """Test if Faster-Whisper is available."""
    print("\n" + "="*50)
    print("TEST 2: Faster-Whisper Model Loading")
    print("="*50)
    
    cmd_listener = get_command_listener()
    model = cmd_listener._load_model()
    
    if model is not None:
        print("✅ Faster-Whisper model loaded successfully!")
        print("   This will be used for command transcription (high accuracy)")
        return True
    else:
        print("❌ Faster-Whisper not available")
        print("   Install with: pip install faster-whisper")
        return False


def test_vad_availability():
    """Test if VAD is available."""
    print("\n" + "="*50)
    print("TEST 3: Voice Activity Detection (WebRTC VAD)")
    print("="*50)
    
    listener = get_passive_listener()
    vad = listener._load_vad()
    
    if vad is not None:
        print("✅ WebRTC VAD loaded successfully!")
        print("   This filters out non-speech audio")
        return True
    else:
        print("⚠️  WebRTC VAD not available")
        print("   Install with: pip install webrtcvad")
        print("   (Optional but recommended)")
        return False


def test_silent_audio():
    """Test that silent audio produces no transcription."""
    print("\n" + "="*50)
    print("TEST 4: Silent Audio (Hallucination Test)")
    print("="*50)
    
    listener = get_passive_listener()
    
    # Create 3 seconds of silence
    silence = np.zeros(16000 * 3, dtype=np.float32)
    
    # Add tiny noise (like a real mic)
    silence += np.random.normal(0, 0.001, len(silence)).astype(np.float32)
    
    print("Testing with 3 seconds of near-silence...")
    
    # Test Vosk
    vosk_result = listener._transcribe_passive(silence)
    
    if not vosk_result:
        print("✅ Vosk correctly returned empty for silence!")
    else:
        print(f"⚠️  Vosk returned: '{vosk_result}' (this should be empty)")
    
    return not bool(vosk_result)


def test_simulated_speech():
    """Test with simulated speech-like audio."""
    print("\n" + "="*50)
    print("TEST 5: Simulated Audio Processing")
    print("="*50)
    
    listener = get_passive_listener()
    
    # Create audio with varying amplitude (simulating speech patterns)
    duration = 2
    t = np.linspace(0, duration, int(16000 * duration))
    
    # Mix of frequencies that might trigger VAD
    audio = (
        0.3 * np.sin(2 * np.pi * 200 * t) +  # Low freq
        0.2 * np.sin(2 * np.pi * 500 * t) +  # Mid freq
        0.1 * np.sin(2 * np.pi * 1000 * t)   # Higher freq
    ).astype(np.float32)
    
    # Add envelope
    envelope = np.abs(np.sin(2 * np.pi * 2 * t))
    audio = audio * envelope
    
    print("Processing 2 seconds of simulated audio...")
    
    result = listener._transcribe_passive(audio)
    print(f"Result: '{result}' (may be empty if VAD filters it)")
    
    return True


def run_live_test():
    """Run a live microphone test."""
    print("\n" + "="*50)
    print("TEST 6: Live Microphone Test (5 seconds)")
    print("="*50)
    
    try:
        import sounddevice as sd
        print("Recording 5 seconds of audio...")
        print("Please speak something like 'Hello Ankita' or 'The weather is nice today'")
        print()
        
        audio = sd.rec(
            int(16000 * 5),
            samplerate=16000,
            channels=1,
            dtype='float32'
        )
        sd.wait()
        audio = audio.flatten()
        
        listener = get_passive_listener()
        
        print("Transcribing with Vosk (passive)...")
        vosk_result = listener._transcribe_passive(audio)
        print(f"Vosk result: '{vosk_result}'")
        
        print("\nTranscribing with Whisper (command)...")
        cmd_listener = get_command_listener()
        whisper_result = cmd_listener.transcribe_command(audio)
        print(f"Whisper result: '{whisper_result}'")
        
        return True
        
    except ImportError:
        print("❌ sounddevice not installed")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    print("="*60)
    print("HYBRID STT TEST SUITE")
    print("Testing Vosk (passive) + Faster-Whisper (commands)")
    print("="*60)
    
    results = []
    
    # Run tests
    results.append(("Vosk Loading", test_vosk_availability()))
    results.append(("Whisper Loading", test_whisper_availability()))
    results.append(("VAD Loading", test_vad_availability()))
    results.append(("Silence Test", test_silent_audio()))
    results.append(("Simulated Audio", test_simulated_speech()))
    
    # Ask for live test
    print("\n" + "="*50)
    print("OPTIONAL: Live Microphone Test")
    print("="*50)
    print("Would you like to run a live microphone test? (y/n)")
    
    try:
        response = input().strip().lower()
        if response in ('y', 'yes'):
            results.append(("Live Test", run_live_test()))
    except (EOFError, KeyboardInterrupt):
        pass
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False
    
    print()
    if all_passed:
        print("🎉 All tests passed! Hybrid STT is ready.")
    else:
        print("⚠️  Some tests failed. Check the output above for details.")
    
    print()
    print("HYBRID STT ARCHITECTURE:")
    print("  • Passive Listening → Vosk (zero hallucination)")
    print("  • Triggered Commands → Faster-Whisper (high accuracy)")
    print("  • Context Storage → Vosk output only (honest memory)")
    print()


if __name__ == "__main__":
    main()
