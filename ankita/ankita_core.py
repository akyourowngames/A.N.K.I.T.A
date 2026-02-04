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
import re

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

    # Early exit for conversational fillers (e.g., "anything else")
    if intent_result["intent"] == "unknown" and any(p in text.lower() for p in ["anything else", "what about", "and then", "what else", "anything more"]):
        response = "Sure—let me know what you’d like to do next."
        add_conversation("ankita", response)
        print(f"Ankita: {response}")
        return response
    
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

    if intent_result.get("intent") == "scheduler.add_job":
        extracted = extract(intent_result["intent"], text)
        if isinstance(extracted, dict):
            merged = dict(extracted)
            merged.update({k: v for k, v in (intent_result.get("entities") or {}).items() if v not in (None, "")})
            intent_result["entities"] = merged

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

    def _voice_to_english(text: str) -> tuple[str, dict]:
        raw = (text or "").strip()
        if not raw:
            return "", {"raw": ""}

        tl = raw.lower().strip()
        has_devanagari = re.search(r"[\u0900-\u097F]", raw) is not None
        # Hinglish trigger words that langdetect frequently mislabels as English
        likely_hinglish = any(w in tl for w in [" jao", " jaao", " kholo", " khol", " band", " chalao", " per ", " pe ", " par ", " krdo", " karo", " kar do"])

        # Quick phrase normalization to produce commands your rule-intents understand
        # Keep it small and deterministic.
        normalized = tl
        # Handle: "chrome per jao" -> "go to chrome"
        normalized = re.sub(r"^(.+?)\s+(?:per|pe|par)\s+jao$", r"go to \1", normalized)
        normalized = re.sub(r"^(.+?)\s+(?:per|pe|par)\s+jaao$", r"go to \1", normalized)
        normalized = re.sub(r"\b(per|pe|par)\s+jao\b", "go to", normalized)
        normalized = re.sub(r"\b(per|pe|par)\s+jayo\b", "go to", normalized)
        normalized = re.sub(r"\bkholo\b", "open", normalized)
        normalized = re.sub(r"\bband\s+karo\b", "close", normalized)
        normalized = re.sub(r"\bband\b", "close", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()

        # If it already became a clean English command, return it.
        if normalized != tl and not has_devanagari:
            return normalized, {"raw": raw, "normalized": normalized, "translated": False}

        # Translate when we see Devanagari or Hinglish patterns.
        should_translate = has_devanagari or likely_hinglish

        lang = None
        if not should_translate:
            try:
                from langdetect import detect

                lang = detect(raw)
            except Exception:
                lang = None
            should_translate = bool(lang and lang != "en")

        if should_translate:
            try:
                from mtranslate import translate

                out = translate(raw, "en")
                out = (out or "").strip()
                out = out if out else raw
                out = re.sub(r"\s+", " ", out).strip()
                return out, {"raw": raw, "lang": lang, "translated": True}
            except Exception:
                return normalized, {"raw": raw, "normalized": normalized, "translated": False}

        return raw, {"raw": raw, "lang": lang, "translated": False}
    
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
            
            text_en, meta = _voice_to_english(text)
            if meta.get("translated") and text_en:
                print(f"[Translated->en]: {text_en}")

            # Get response and speak it
            # IMPORTANT: Use the same pipeline as text mode (pronoun recall + normalization)
            response = handle_text(text_en)
            print(f"Ankita: {response}")
            speak(response)
        except KeyboardInterrupt:
            speak("Goodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


def run_continuous_voice_mode(
    wake_words: list[str] | None = None,
    stop_words: list[str] | None = None,
    command_seconds: int = 5,
):
    from voice.mic import record_audio
    from voice.stt import transcribe
    from voice.tts import speak

    wake_words = wake_words or ["jarvis", "hey jarvis"]
    stop_words = stop_words or ["stop", "sleep", "go idle", "cancel"]

    def _voice_to_english(text: str) -> tuple[str, dict]:
        raw = (text or "").strip()
        if not raw:
            return "", {"raw": ""}

        tl = raw.lower().strip()
        has_devanagari = re.search(r"[\u0900-\u097F]", raw) is not None
        likely_hinglish = any(w in tl for w in [" jao", " jaao", " kholo", " khol", " band", " chalao", " per ", " pe ", " par ", " krdo", " karo", " kar do"])

        normalized = tl
        # Handle: "chrome per jao" -> "go to chrome"
        normalized = re.sub(r"^(.+?)\s+(?:per|pe|par)\s+jao$", r"go to \1", normalized)
        normalized = re.sub(r"^(.+?)\s+(?:per|pe|par)\s+jaao$", r"go to \1", normalized)
        normalized = re.sub(r"\b(per|pe|par)\s+jao\b", "go to", normalized)
        normalized = re.sub(r"\b(per|pe|par)\s+jayo\b", "go to", normalized)
        normalized = re.sub(r"\bkholo\b", "open", normalized)
        normalized = re.sub(r"\bband\s+karo\b", "close", normalized)
        normalized = re.sub(r"\bband\b", "close", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()

        if normalized != tl and not has_devanagari:
            return normalized, {"raw": raw, "normalized": normalized, "translated": False}

        should_translate = has_devanagari or likely_hinglish
        lang = None
        if not should_translate:
            try:
                from langdetect import detect

                lang = detect(raw)
            except Exception:
                lang = None
            should_translate = bool(lang and lang != "en")

        if should_translate:
            try:
                from mtranslate import translate

                out = translate(raw, "en")
                out = (out or "").strip()
                out = out if out else raw
                out = re.sub(r"\s+", " ", out).strip()
                return out, {"raw": raw, "lang": lang, "translated": True}
            except Exception:
                return normalized, {"raw": raw, "normalized": normalized, "translated": False}

        return raw, {"raw": raw, "lang": lang, "translated": False}

    def _is_stop(text: str) -> bool:
        tl = (text or "").strip().lower()
        if not tl:
            return False
        return any(w in tl for w in stop_words)

    def _listen_for_wake() -> bool:
        access_key = os.getenv("PICOVOICE_ACCESS_KEY") or os.getenv("PV_ACCESS_KEY")
        if access_key:
            try:
                import pvporcupine
                import pyaudio
                import struct

                porcupine = pvporcupine.create(access_key=access_key, keywords=["ankita"])
                pa = pyaudio.PyAudio()
                stream = pa.open(
                    rate=porcupine.sample_rate,
                    channels=1,
                    format=pyaudio.paInt16,
                    input=True,
                    frames_per_buffer=porcupine.frame_length,
                )
                try:
                    while True:
                        pcm = stream.read(porcupine.frame_length, exception_on_overflow=False)
                        pcm = struct.unpack_from("h" * porcupine.frame_length, pcm)
                        if porcupine.process(pcm) >= 0:
                            return True
                finally:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:
                        pass
                    try:
                        pa.terminate()
                    except Exception:
                        pass
                    try:
                        porcupine.delete()
                    except Exception:
                        pass
            except Exception:
                pass

        # Optional Vosk wake-word fallback (local/offline) for "hey ankita"
        model_path = os.getenv("VOSK_MODEL_PATH")
        if model_path:
            try:
                import json
                import vosk
                import sounddevice as sd

                model = vosk.Model(model_path)
                rec = vosk.KaldiRecognizer(model, 16000)

                # Use sounddevice to avoid PyAudio build issues on Windows
                with sd.RawInputStream(
                    samplerate=16000,
                    blocksize=8000,
                    dtype="int16",
                    channels=1,
                ) as stream:
                    while True:
                        data_mv, _overflowed = stream.read(4000)
                        data = bytes(data_mv)
                        if not data:
                            continue

                        if rec.AcceptWaveform(data):
                            res = json.loads(rec.Result() or "{}")
                            text = (res.get("text") or "").strip().lower()
                            if any(w in text for w in wake_words):
                                return True
                        else:
                            pres = json.loads(rec.PartialResult() or "{}")
                            p = (pres.get("partial") or "").strip().lower()
                            if any(w in p for w in wake_words):
                                return True
            except Exception:
                pass

        cmd = input("[Idle] Say wake word or press Enter to speak (type 'exit' to quit): ")
        if (cmd or "").strip().lower() in ["exit", "quit", "bye"]:
            return False
        return True

    state = "IDLE"
    speak("Continuous mode enabled.")
    print("[Ankita] Continuous voice mode. Wake word: Jarvis. Stop words: stop/sleep/cancel. Ctrl+C to quit.\n")

    try:
        while True:
            if state == "IDLE":
                ok = _listen_for_wake()
                if not ok:
                    speak("Goodbye!")
                    break
                state = "LISTENING"

            if state == "LISTENING":
                print("[Listening...]")
                audio_path = record_audio(duration=command_seconds)
                raw = transcribe(audio_path)
                print(f"[You said]: {raw}")

                if not (raw or "").strip():
                    speak("I didn't hear anything.")
                    state = "IDLE"
                    continue

                if _is_stop(raw):
                    speak("Okay, going idle.")
                    state = "IDLE"
                    continue

                text_en, meta = _voice_to_english(raw)
                if meta.get("translated") and text_en:
                    print(f"[Translated->en]: {text_en}")

                state = "EXECUTING"
                response = handle_text(text_en)
                print(f"Ankita: {response}")
                speak(response)
                state = "IDLE"

    except KeyboardInterrupt:
        try:
            speak("Goodbye!")
        except Exception:
            pass


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
    parser.add_argument("--continuous", action="store_true", help="Continuous voice mode (wake word + stop word)")
    args = parser.parse_args()
    
    print()
    print("  █████╗ ███╗   ██╗██╗  ██╗██╗████████╗ █████╗ ")
    print(" ██╔══██╗████╗  ██║██║ ██╔╝██║╚══██╔══╝██╔══██╗")
    print(" ███████║██╔██╗ ██║█████╔╝ ██║   ██║   ███████║")
    print(" ██╔══██║██║╚██╗██║██╔═██╗ ██║   ██║   ██╔══██║")
    print(" ██║  ██║██║ ╚████║██║  ██╗██║   ██║   ██║  ██║")
    print(" ╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝   ╚═╝   ╚═╝  ╚═╝")
    print()
    
    if args.continuous:
        run_continuous_voice_mode()
    elif args.voice:
        run_voice_mode()
    elif args.both:
        run_hybrid_mode()
    else:
        run_text_mode()


if __name__ == "__main__":
    main()
