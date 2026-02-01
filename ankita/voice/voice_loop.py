import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voice.mic import record_audio
from voice.stt import transcribe
from voice.tts import speak
from brain.intent_model import classify
from brain.planner import plan
from executor.executor import execute

def run():
    print("[Ankita Voice] Ready. Press Enter to speak...")
    
    while True:
        try:
            input()  # Wait for Enter key
            
            # Record
            audio_path = record_audio(duration=5)
            
            # Transcribe
            text = transcribe(audio_path)
            print(f"[You said]: {text}")
            
            if not text.strip():
                print("[Ankita] I didn't hear anything.")
                continue
            
            if text.lower().strip() in ["exit", "quit", "stop"]:
                print("[Ankita] Goodbye!")
                break
            
            # Process through brain
            intent_result = classify(text)
            execution_plan = plan(intent_result)
            execute(execution_plan)
            
            # Speak confirmation
            speak("Done!")
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[Error]: {e}")

if __name__ == "__main__":
    run()
