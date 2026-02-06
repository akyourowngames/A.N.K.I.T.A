"""
Audio Diagnostic Tool - Debug microphone and STT issues.

This script tests:
1. Microphone detection
2. Audio level monitoring 
3. VAD sensitivity
4. Vosk transcription in real-time
"""

import os
import sys
import time
import numpy as np

# Environment setup
os.environ["PASSIVE_DEBUG"] = "1"

try:
    import sounddevice as sd
except ImportError:
    print("ERROR: sounddevice not installed. Run: pip install sounddevice")
    sys.exit(1)

SAMPLE_RATE = 16000


def list_audio_devices():
    """List all available audio devices."""
    print("\n" + "="*60)
    print("AVAILABLE AUDIO DEVICES")
    print("="*60)
    
    devices = sd.query_devices()
    default_input = sd.default.device[0]
    
    for i, device in enumerate(devices):
        if device['max_input_channels'] > 0:
            marker = " <-- DEFAULT" if i == default_input else ""
            print(f"  [{i}] {device['name']}{marker}")
            print(f"      Channels: {device['max_input_channels']}, Sample Rate: {device['default_samplerate']}")
    
    print()
    return default_input


def test_audio_capture(duration=3):
    """Test basic audio capture."""
    print("\n" + "="*60)
    print(f"RECORDING {duration} SECONDS OF AUDIO...")
    print("="*60)
    print("Please speak into your microphone.\n")
    
    try:
        audio = sd.rec(
            int(SAMPLE_RATE * duration),
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype='float32'
        )
        sd.wait()
        audio = audio.flatten()
        
        # Analyze audio
        rms = float(np.sqrt(np.mean(np.square(audio))))
        peak = float(np.max(np.abs(audio)))
        
        print(f"✅ Audio captured successfully!")
        print(f"   Samples: {len(audio)}")
        print(f"   Duration: {len(audio)/SAMPLE_RATE:.2f}s")
        print(f"   RMS Level: {rms:.4f}")
        print(f"   Peak Level: {peak:.4f}")
        
        # Level assessment
        if rms < 0.01:
            print(f"\n⚠️  WARNING: Audio level is VERY LOW!")
            print("   - Check if microphone is muted")
            print("   - Check microphone volume in Windows settings")
            print("   - Try moving closer to the microphone")
        elif rms < 0.05:
            print(f"\n⚠️  Audio level is low but should work")
        else:
            print(f"\n✅ Audio level looks good!")
        
        return audio
        
    except Exception as e:
        print(f"❌ Audio capture failed: {e}")
        return None


def test_vad(audio):
    """Test Voice Activity Detection."""
    print("\n" + "="*60)
    print("TESTING VOICE ACTIVITY DETECTION (VAD)")
    print("="*60)
    
    try:
        import webrtcvad
        vad = webrtcvad.Vad(2)  # Aggressiveness 2
        
        # Convert to int16
        audio_int16 = (audio * 32767).astype(np.int16)
        
        # Check 30ms frames
        frame_size = int(SAMPLE_RATE * 0.03)
        speech_frames = 0
        total_frames = 0
        
        for i in range(0, len(audio_int16) - frame_size, frame_size):
            frame = audio_int16[i:i + frame_size].tobytes()
            try:
                if vad.is_speech(frame, SAMPLE_RATE):
                    speech_frames += 1
            except Exception:
                pass
            total_frames += 1
        
        speech_ratio = speech_frames / total_frames if total_frames > 0 else 0
        
        print(f"✅ VAD analysis complete")
        print(f"   Total frames: {total_frames}")
        print(f"   Speech frames: {speech_frames}")
        print(f"   Speech ratio: {speech_ratio:.1%}")
        
        if speech_ratio < 0.1:
            print(f"\n⚠️  VAD detected very little speech!")
            print("   This might filter out your voice.")
        else:
            print(f"\n✅ VAD detected speech successfully!")
        
        return speech_ratio > 0.1
        
    except ImportError:
        print("⚠️  webrtcvad not installed - VAD disabled")
        return True


def test_vosk(audio):
    """Test Vosk transcription."""
    print("\n" + "="*60)
    print("TESTING VOSK TRANSCRIPTION")
    print("="*60)
    
    try:
        from vosk import Model, KaldiRecognizer
        import json
        
        # Find model
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        model_paths = [
            os.path.join(project_root, "vosk-model-small-en-us-0.15"),
            "vosk-model-small-en-us-0.15",
        ]
        
        model = None
        for path in model_paths:
            if os.path.exists(path):
                print(f"Loading model from: {path}")
                model = Model(path)
                break
        
        if model is None:
            print("❌ Vosk model not found!")
            print("   Run: python scripts/setup_vosk_model.py")
            return False
        
        rec = KaldiRecognizer(model, SAMPLE_RATE)
        
        # Convert to bytes
        audio_bytes = (audio * 32767).astype(np.int16).tobytes()
        
        # Process
        rec.AcceptWaveform(audio_bytes)
        result = json.loads(rec.FinalResult())
        text = result.get("text", "").strip()
        
        print(f"\n📝 Vosk transcription: '{text}'")
        
        if text:
            print(f"\n✅ Vosk is working! It heard: \"{text}\"")
            return True
        else:
            print(f"\n⚠️  Vosk returned empty transcription")
            print("   Try speaking louder or more clearly")
            return False
        
    except Exception as e:
        print(f"❌ Vosk error: {e}")
        return False


def live_audio_monitor():
    """Live audio level monitor."""
    print("\n" + "="*60)
    print("LIVE AUDIO MONITOR (10 seconds)")
    print("="*60)
    print("Watch the level bar as you speak:\n")
    
    # Load Vosk for live transcription
    try:
        from vosk import Model, KaldiRecognizer
        import json
        
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        model_path = os.path.join(project_root, "vosk-model-small-en-us-0.15")
        
        if os.path.exists(model_path):
            model = Model(model_path)
            rec = KaldiRecognizer(model, SAMPLE_RATE)
            rec.SetWords(False)
            vosk_available = True
        else:
            vosk_available = False
    except:
        vosk_available = False
    
    start_time = time.time()
    
    while time.time() - start_time < 10:
        try:
            # Record chunk
            audio = sd.rec(
                int(SAMPLE_RATE * 0.5),  # 0.5 second chunks
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype='float32'
            )
            sd.wait()
            audio = audio.flatten()
            
            # Calculate RMS
            rms = float(np.sqrt(np.mean(np.square(audio))))
            
            # Create visual bar
            bar_length = int(rms * 200)  # Scale for visibility
            bar = "█" * min(bar_length, 50)
            spaces = " " * (50 - len(bar))
            
            # Vosk transcription
            if vosk_available:
                audio_bytes = (audio * 32767).astype(np.int16).tobytes()
                if rec.AcceptWaveform(audio_bytes):
                    result = json.loads(rec.Result())
                    text = result.get("text", "").strip()
                    if text:
                        print(f"\n    📝 Heard: \"{text}\"")
            
            # Print level bar
            level_indicator = "🔴" if rms < 0.01 else "🟡" if rms < 0.05 else "🟢"
            print(f"\r{level_indicator} [{bar}{spaces}] {rms:.4f}", end='', flush=True)
            
        except Exception as e:
            print(f"\rError: {e}", end='')
    
    print("\n")


def main():
    print("="*60)
    print("AUDIO DIAGNOSTIC TOOL")
    print("="*60)
    
    # 1. List devices
    default_device = list_audio_devices()
    
    # 2. Test audio capture
    audio = test_audio_capture(duration=3)
    
    if audio is None:
        print("\n❌ Cannot proceed without audio capture")
        return
    
    # 3. Test VAD
    vad_ok = test_vad(audio)
    
    # 4. Test Vosk
    vosk_ok = test_vosk(audio)
    
    # 5. Live monitor
    print("\n" + "="*60)
    print("Would you like to run a live audio monitor? (y/n)")
    try:
        response = input().strip().lower()
        if response in ('y', 'yes'):
            live_audio_monitor()
    except:
        pass
    
    # Summary
    print("\n" + "="*60)
    print("DIAGNOSTIC SUMMARY")
    print("="*60)
    
    if audio is not None:
        print("✅ Microphone: Working")
    else:
        print("❌ Microphone: Not working")
    
    if vad_ok:
        print("✅ VAD: Detecting speech")
    else:
        print("⚠️  VAD: Not detecting speech (may filter voice)")
    
    if vosk_ok:
        print("✅ Vosk: Transcribing successfully")
    else:
        print("⚠️  Vosk: Not transcribing (check audio level)")
    
    print()
    
    if not vosk_ok:
        print("RECOMMENDATIONS:")
        print("  1. Check Windows Sound Settings -> Recording devices")
        print("  2. Ensure your microphone is not muted")
        print("  3. Try speaking louder/closer to the mic")
        print("  4. Set PASSIVE_DEBUG=1 environment variable for more logs")


if __name__ == "__main__":
    main()
