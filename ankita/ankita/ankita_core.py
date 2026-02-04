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

CLASSIFICATION STACK:
1. Rules (keywords)  - instant, deterministic
2. Gemma (local)     - fast, private  
3. Cloud LLM (Groq)  - smart, reliable
4. Conversation      - natural chat fallback
"""

import os
import argparse

# Load .env file for API keys
from dotenv import load_dotenv
load_dotenv()


from brain.intent_model import classify
from brain.gemma_intent import gemma_classify
from brain.planner import plan
from executor.executor import execute
from llm.llm_client import generate_response, ask_llm, is_question
from llm.intent_fallback import llm_classify
from memory.memory_manager import add_conversation, add_episode
from memory.recall import resolve_pronouns
from brain.entity_normalizer import normalize
from brain.entity_extractor import extract


# ============== CORE HANDLERS ==============

def handle_intent(intent_result: dict, user_text: str = "") -> str:
    """
    Process an intent result through planner and executor.
    Returns natural language response.
    """
    execution_plan = plan(intent_result)

    # Message-only plans are memory-only / internal responses.
    # Return directly to keep them authoritative and avoid polluting episodic memory.
    if isinstance(execution_plan, dict) and "message" in execution_plan:
        response = str(execution_plan.get("message", ""))
        add_conversation("ankita", response)
        return response

    result = execute(execution_plan)
    
    # Record episode in memory
    if isinstance(result, dict) and result.get("status") == "success":
        add_episode(
            intent_result["intent"],
            intent_result.get("entities", {}),
            result
        )

    # Deterministic responses for system tools (avoid LLM fluff; surface real errors)
    if str(intent_result.get("intent", "")).startswith("system."):
        if isinstance(result, dict) and result.get("status") == "success":
            first = None
            if isinstance(result.get("results"), list) and result["results"]:
                first = result["results"][0]
            if isinstance(first, dict):
                if "message" in first:
                    return str(first.get("message"))
                if "value" in first:
                    return f"{intent_result['intent']}: {first.get('value')}"
            return "Done."

        # fail/error path
        last = result.get("last_result") if isinstance(result, dict) else None
        if isinstance(last, dict):
            reason = str(last.get("reason", "Failed"))
            err = str(last.get("error", "")).strip()
            return reason + (f" ({err})" if err else "")
        return "Failed."
    
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


def handle_text(text: str, source: str = "user") -> str:
    """
    Process raw text input through the 3-layer brain stack.
    
    BRAIN STACK:
    1. Rules     → instant keyword match
    2. Gemma     → local LLM (fast, private)
    3. Cloud LLM → Groq fallback (smart)
    4. Chat      → natural conversation
    
    Returns natural language response.
    """
    # Record user input
    add_conversation(source, text)
    
    # Check for pronoun references ("do it again", "continue that")
    recalled = resolve_pronouns(text)
    if recalled:
        response = handle_intent(recalled, user_text=text)
        print(f"Ankita: {response}")
        return response
    
    # ===== THE 3-LAYER BRAIN STACK =====
    intent_result = {"intent": "unknown", "entities": {}}
    
    # LAYER 1: Rules (instant, deterministic)
    intent_result = classify(text)
    
    # LAYER 2: Gemma LOCAL (fast, private)
    if intent_result["intent"] == "unknown":
        gemma_result = gemma_classify(text)
        if gemma_result["intent"] != "unknown":
            intent_result = gemma_result
    
    # LAYER 3: Cloud LLM fallback (smart, reliable)
    # Always attempt intent classification if rules+Gemma fail.
    # This allows phrasing like "can you turn bluetooth off?" to still trigger tools.
    if intent_result["intent"] == "unknown":
        intent_result = llm_classify(text)
    
    # LAYER 4: Natural conversation (no action needed)
    # Only chat if the intent is still unknown after LLM classification.
    if intent_result["intent"] == "unknown":
        response = ask_llm(text)
        add_conversation("ankita", response)
        print(f"Ankita: {response}")
        return response
    

    # If fallback classifiers returned an intent but no entities, extract deterministically
    if not intent_result.get("entities"):
        intent_result["entities"] = extract(intent_result["intent"], text)

    # ===== ENTITY NORMALIZATION LAYER =====
    intent_result["entities"] = normalize(
        intent_result["intent"],
        intent_result.get("entities", {}),
        text
    )
    print(f"DEBUG: normalized entities -> {intent_result['entities']}")

    # ===== EXECUTE ACTION =====
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
            # IMPORTANT: Use the same pipeline as text mode (pronoun recall + normalization)
            response = handle_text(text)
            print(f"Ankita: {response}")
            speak(response)
        except KeyboardInterrupt:
            speak("Goodbye!")
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
                # IMPORTANT: Use the same pipeline as text mode (pronoun recall + normalization)
                response = handle_text(text)
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
