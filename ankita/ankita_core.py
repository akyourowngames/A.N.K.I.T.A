"""
Ankita Core - The heart of the system.

This is the SINGLE entry point for all inputs:
- Text input
- Voice input  
- Scheduler events

Run modes:
  python ankita_core.py          → Text mode
  python ankita_core.py --voice  → Voice mode
  python ankita_core.py --both   → Hybrid mode

Brain decides, tools act. Brain never touches OS.
"""

import argparse
from brain.intent_model import classify
from brain.planner import plan
from executor.executor import execute
from llm.llm_client import generate_response, ask_llm, is_question
from memory.memory_manager import add_conversation, add_episode
from memory.recall import resolve_pronouns


# ============== CORE HANDLERS ==============

def handle_intent(intent_result: dict, user_text: str = "") -> str:
    """
    Process an intent result through planner and executor.
    Returns natural language response.
    """
    execution_plan = plan(intent_result)
    result = execute(execution_plan)
    
    # Record episode in memory
    add_episode(
        intent_result["intent"],
        intent_result.get("entities", {}),
        result
    )
    
    # Generate natural response using LLM
    context = {
        "intent": intent_result["intent"],
        "entities": intent_result.get("entities", {}),
        "result": result,
        "user_text": user_text
    }
    response = generate_response(context)
    
    # Record Ankita's response
    add_conversation("ankita", response)
    
    return response


def handle_text(text: str) -> str:
    """
    Process raw text input - classify intent, execute, and respond.
    Returns natural language response.
    """
    # Record user input
    add_conversation("user", text)
    
    # Check for pronoun references ("do it again", "continue that")
    recalled = resolve_pronouns(text)
    if recalled:
        response = handle_intent(recalled, user_text=text)
        print(f"Ankita: {response}")
        return response
    
    # Normal intent classification
    intent_result = classify(text)
    
    # Route to LLM for unknown intents or questions
    if intent_result["intent"] == "unknown" or is_question(text):
        response = ask_llm(text)
        add_conversation("ankita", response)
        print(f"Ankita: {response}")
        return response
    
    # Known intent → execute action
    response = handle_intent(intent_result, user_text=text)
    print(f"Ankita: {response}")
    return response


def handle_event(intent: str, entities: dict = None) -> str:
    """Process a direct event with known intent (used by scheduler)."""
    return handle_intent({
        "intent": intent,
        "entities": entities or {}
    })


# ============== INPUT MODES ==============

def run_text_mode():
    """Text input mode - type commands."""
    print("[Ankita] Text mode. Type command or 'exit' to quit.\n")
    
    while True:
        try:
            text = input("You: ")
            if text.lower() in ["exit", "quit", "bye"]:
                print("[Ankita] Goodbye!")
                break
            handle_text(text)
        except KeyboardInterrupt:
            print("\n[Ankita] Goodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


def run_voice_mode():
    """Voice input mode - speak commands."""
    from voice.mic import record_audio
    from voice.stt import transcribe
    from voice.tts import speak
    
    print("[Ankita] Voice mode. Press Enter to speak, 'exit' to quit.\n")
    
    while True:
        try:
            cmd = input("[Press Enter to speak] ")
            if cmd.lower() in ["exit", "quit", "bye"]:
                speak("Goodbye!")
                break
            
            print("[Listening...]")
            audio_path = record_audio(duration=5)
            text = transcribe(audio_path)
            print(f"[You said]: {text}")
            
            if not text.strip():
                speak("I didn't hear anything.")
                continue
            
            # Get response and speak it
            intent_result = classify(text)
            response = handle_intent(intent_result, user_text=text)
            print(f"Ankita: {response}")
            speak(response)
        except KeyboardInterrupt:
            print("\n[Ankita] Goodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


def run_hybrid_mode():
    """Hybrid mode - Enter for voice, type for text."""
    from voice.mic import record_audio
    from voice.stt import transcribe
    from voice.tts import speak
    
    print("[Ankita] Hybrid mode.")
    print("  Enter (empty) → Voice | Type text → Text | 'exit' → Quit\n")
    
    while True:
        try:
            cmd = input("You: ")
            
            if cmd.lower() in ["exit", "quit", "bye"]:
                speak("Goodbye!")
                break
            
            if cmd.strip() == "":
                # Voice input
                print("[Listening...]")
                audio_path = record_audio(duration=5)
                text = transcribe(audio_path)
                print(f"[You said]: {text}")
                
                if not text.strip():
                    speak("I didn't hear anything.")
                    continue
                
                # Get response and speak it
                intent_result = classify(text)
                response = handle_intent(intent_result, user_text=text)
                print(f"Ankita: {response}")
                speak(response)
            else:
                # Text input (no TTS)
                handle_text(cmd)
        except KeyboardInterrupt:
            print("\n[Ankita] Goodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


# ============== MAIN ==============

def main():
    parser = argparse.ArgumentParser(description="Ankita AI Assistant")
    parser.add_argument("--voice", action="store_true", help="Voice mode")
    parser.add_argument("--both", action="store_true", help="Hybrid mode")
    args = parser.parse_args()
    
    print()
    print("  █████╗ ███╗   ██╗██╗  ██╗██╗████████╗ █████╗ ")
    print(" ██╔══██╗████╗  ██║██║ ██╔╝██║╚══██╔══╝██╔══██╗")
    print(" ███████║██╔██╗ ██║█████╔╝ ██║   ██║   ███████║")
    print(" ██╔══██║██║╚██╗██║██╔═██╗ ██║   ██║   ██╔══██║")
    print(" ██║  ██║██║ ╚████║██║  ██╗██║   ██║   ██║  ██║")
    print(" ╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝   ╚═╝   ╚═╝  ╚═╝")
    print()
    
    if args.voice:
        run_voice_mode()
    elif args.both:
        run_hybrid_mode()
    else:
        run_text_mode()


if __name__ == "__main__":
    main()
