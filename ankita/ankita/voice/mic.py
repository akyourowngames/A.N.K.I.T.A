import sounddevice as sd
import numpy as np
import wave
import os
import tempfile

SAMPLE_RATE = 16000
DURATION = 5  # seconds

def record_audio(duration=DURATION):
    print(f"[Voice] Listening for {duration} seconds...")
    audio = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype='int16')
    sd.wait()
    print("[Voice] Done recording.")
    
    # Save to temp file
    temp_path = os.path.join(tempfile.gettempdir(), "ankita_voice.wav")
    with wave.open(temp_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    
    return temp_path
