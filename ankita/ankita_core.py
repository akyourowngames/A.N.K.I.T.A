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
1. Rules     → instant keyword match
2. Gemma     → local LLM (fast, private)  
3. Cloud LLM → Groq fallback (smart)
4. Conversation      → natural chat fallback
"""

import os
import argparse
import re
import sys
import json
import socket
import subprocess
import time
from datetime import datetime

# Load .env file for API keys
from dotenv import load_dotenv
load_dotenv()


from brain.intent_model import classify
from brain.semantic_intent import semantic_classify
from brain.planner import plan
from executor.executor import execute
from llm.llm_client import generate_response, ask_llm, is_question
from llm.intent_fallback import llm_classify
from memory.memory_manager import add_conversation, add_episode, last_episode
from memory.recall import resolve_pronouns
from brain.entity_normalizer import normalize
from brain.entity_extractor import extract
from brain.text_normalizer import normalize_text
from memory.ltm_manager import (
    get_correction,
    get_preference,
    get_preference_confidence,
    find_time_habits,
    mark_suggested_today,
    mark_suggestion_dismissed_today,
    observe_success,
    set_correction,
    was_suggested_today,
)


_UI_STATE_ADDR = ("127.0.0.1", 50555)
_UI_CMD_ADDR = ("127.0.0.1", 50556)
_ui_state_sock: socket.socket | None = None
_ui_cmd_sock: socket.socket | None = None
_ui_sleeping: bool = False
_pending_followup: dict | None = None
_pending_suggestion: dict | None = None
_suggestion_shown_this_session: bool = False


def _jarvis_clarify(text: str) -> str:
    return f"Sir, kindly confirm: {text}"


def _jarvis_ack(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return "Yes sir."
    return f"Yes sir. {t}"


def _jarvis_fail(text: str) -> str:
    t = (text or "Failed").strip()
    return f"{t}, sir." if not t.lower().endswith(", sir.") else t


def _print_ankita_stream(text: str, chunk_chars: int = 6, delay_s: float = 0.015) -> None:
    t = "" if text is None else str(text)
    sys.stdout.write("Ankita: ")
    sys.stdout.flush()
    if not t:
        sys.stdout.write("\n")
        sys.stdout.flush()
        return
    for i in range(0, len(t), int(chunk_chars)):
        sys.stdout.write(t[i : i + int(chunk_chars)])
        sys.stdout.flush()
        time.sleep(float(delay_s))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _is_affirmative(t: str) -> bool:
    tl = (t or "").strip().lower()
    return tl in ("yes", "y", "yeah", "yep", "ok", "okay", "sure", "do it")


def _is_negative(t: str) -> bool:
    tl = (t or "").strip().lower()
    return tl in ("no", "n", "nope", "nah", "cancel", "stop")


def _maybe_make_suggestion(intent_result: dict) -> str | None:
    """Return a suggestion string or None. Suggest-only, never auto-act."""
    global _pending_suggestion, _suggestion_shown_this_session
    if _suggestion_shown_this_session:
        return None

    now = datetime.now()
    habits = find_time_habits(now.hour)
    if not habits:
        return None

    # Pick best habit by confidence then count
    scored = []
    for h in habits:
        if not isinstance(h, dict):
            continue
        key = str(h.get("key", "")).strip()
        if not key or was_suggested_today(key):
            continue
        try:
            conf = float(h.get("confidence", 0.0) or 0.0)
            cnt = int(h.get("count", 0) or 0)
        except Exception:
            continue
        if conf < 0.75 or cnt < 3:
            continue
        scored.append((conf, cnt, h))

    if not scored:
        return None

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    h = scored[0][2]
    key = str(h.get("key"))
    action = str(h.get("action", "")).strip()
    target = str(h.get("target", "")).strip()

    if action == "open_app" and target:
        _pending_suggestion = {
            "key": key,
            "intent": "system.app.open",
            "entities": {"action": "open", "app": target},
        }
        _suggestion_shown_this_session = True
        mark_suggested_today(key, {"type": "time_based", "target": target, "action": action})
        return f"Sir, you usually open {target} around this time. Would you like me to open it?"

    if action == "focus_app" and target:
        _pending_suggestion = {
            "key": key,
            "intent": "system.app.focus",
            "entities": {"action": "focus", "app": target},
        }
        _suggestion_shown_this_session = True
        mark_suggested_today(key, {"type": "time_based", "target": target, "action": action})
        return f"Sir, you typically switch to {target} around this time. Would you like me to focus it?"

    return None


def _ensure_ui_state_sock() -> socket.socket:
    global _ui_state_sock
    if _ui_state_sock is None:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setblocking(False)
        _ui_state_sock = s
    return _ui_state_sock


def publish_ui_state(state: str, extra: dict | None = None) -> None:
    try:
        payload = {"type": "state", "state": str(state)}
        if extra:
            payload["extra"] = extra
        data = json.dumps(payload).encode("utf-8")
        _ensure_ui_state_sock().sendto(data, _UI_STATE_ADDR)
    except Exception:
        return


def _ensure_ui_cmd_sock() -> socket.socket:
    global _ui_cmd_sock
    if _ui_cmd_sock is None:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(_UI_CMD_ADDR)
        except Exception:
            pass
        s.setblocking(False)
        _ui_cmd_sock = s
    return _ui_cmd_sock


def poll_ui_commands() -> list[dict]:
    cmds: list[dict] = []
    try:
        s = _ensure_ui_cmd_sock()
        while True:
            try:
                data, _addr = s.recvfrom(65535)
            except BlockingIOError:
                break
            except Exception:
                break
            try:
                msg = json.loads((data or b"").decode("utf-8"))
                if isinstance(msg, dict):
                    cmds.append(msg)
            except Exception:
                continue
    except Exception:
        return cmds
    return cmds


def _maybe_start_bubble(args: argparse.Namespace) -> None:
    if getattr(args, "no_bubble", False):
        return
    bubble_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "floating_bubble.py")
    if not os.path.exists(bubble_path):
        return
    try:
        subprocess.Popen([sys.executable, bubble_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return


# ============== CORE HANDLERS ==============

def handle_intent(intent_result: dict, user_text: str = "") -> str:
    """
    Process an intent result through planner and executor.
    Returns natural language response.
    """
    publish_ui_state("EXECUTING")
    execution_plan = plan(intent_result)

    # Message-only plans are memory-only / internal responses.
    # Return directly to keep them authoritative and avoid polluting episodic memory.
    if isinstance(execution_plan, dict) and "message" in execution_plan:
        response = str(execution_plan.get("message", ""))
        add_conversation("ankita", response)
        publish_ui_state("IDLE")
        return response

    result = execute(execution_plan)
    
    # Record episode in memory
    if isinstance(result, dict) and result.get("status") == "success":
        add_episode(
            intent_result["intent"],
            intent_result.get("entities", {}),
            result
        )
        observe_success(intent_result["intent"], intent_result.get("entities", {}), result)

    # Deterministic responses for system tools (avoid LLM fluff; surface real errors)
    if str(intent_result.get("intent", "")).startswith("system."):
        if isinstance(result, dict) and result.get("status") == "success":
            first = None
            if isinstance(result.get("results"), list) and result["results"]:
                first = result["results"][0]
            if isinstance(first, dict):
                if "message" in first:
                    msg = str(first.get("message"))
                    if intent_result.get("_soft_confirm"):
                        msg = msg + " — say 'change' if you meant something else."
                    publish_ui_state("IDLE")
                    return _jarvis_ack(msg)
                if "value" in first:
                    val = f"{intent_result['intent']}: {first.get('value')}"
                    publish_ui_state("IDLE")
                    return _jarvis_ack(val)
            publish_ui_state("IDLE")
            return _jarvis_ack("Task completed")

        # fail/error path
        last = result.get("last_result") if isinstance(result, dict) else None
        if isinstance(last, dict):
            reason = str(last.get("reason", "Failed"))
            err = str(last.get("error", "")).strip()
            publish_ui_state("IDLE")
            return _jarvis_fail(reason + (f" ({err})" if err else ""))
        publish_ui_state("IDLE")
        return _jarvis_fail("Failed")
    
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
    publish_ui_state("IDLE")
    return response


def handle_text(text: str, source: str = "user") -> str:
    """Process raw text input and return a natural language response."""
    # Record user input
    if _ui_sleeping:
        publish_ui_state("SLEEP")
        return ""

    publish_ui_state("LISTENING")
    add_conversation(source, text)

    global _pending_followup
    global _pending_suggestion
    tnorm = normalize_text(text)

    # Handle suggestion accept/dismiss (text mode only; never interrupt voice)
    if source == "user" and _pending_suggestion is not None:
        if _is_affirmative(tnorm):
            pending = _pending_suggestion
            _pending_suggestion = None
            intent_result = {"intent": pending.get("intent"), "entities": pending.get("entities", {})}
            intent_result["entities"] = normalize(intent_result["intent"], intent_result.get("entities", {}), text)
            print(f"DEBUG: normalized entities -> {intent_result['entities']}")
            response = handle_intent(intent_result, user_text=text)
            _print_ankita_stream(response)
            publish_ui_state("IDLE")
            return response

        if _is_negative(tnorm):
            key = str(_pending_suggestion.get("key", ""))
            _pending_suggestion = None
            if key:
                mark_suggestion_dismissed_today(key)
            publish_ui_state("IDLE")
            response = _jarvis_ack("Understood")
            add_conversation("ankita", response)
            _print_ankita_stream(response)
            return response
    if _pending_followup is not None:
        pending = _pending_followup
        _pending_followup = None
        if pending.get("type") == "choose_browser" and pending.get("intent") in ("system.app.open", "system.app.focus"):
            if any(w in tnorm for w in ["chrome", "google chrome"]):
                intent_result = {"intent": pending["intent"], "entities": {"action": pending.get("action"), "app": "chrome"}}
                intent_result["entities"] = normalize(intent_result["intent"], intent_result.get("entities", {}), text)
                print(f"DEBUG: normalized entities -> {intent_result['entities']}")
                response = handle_intent(intent_result, user_text=text)
                _print_ankita_stream(response)
                publish_ui_state("IDLE")
                return response
            if any(w in tnorm for w in ["edge", "ms edge", "microsoft edge"]):
                intent_result = {"intent": pending["intent"], "entities": {"action": pending.get("action"), "app": "edge"}}
                intent_result["entities"] = normalize(intent_result["intent"], intent_result.get("entities", {}), text)
                print(f"DEBUG: normalized entities -> {intent_result['entities']}")
                response = handle_intent(intent_result, user_text=text)
                _print_ankita_stream(response)
                publish_ui_state("IDLE")
                return response
            publish_ui_state("IDLE")
            return _jarvis_clarify("Chrome or Edge")

    if tnorm.startswith("no") or tnorm.startswith("not"):
        prev = last_episode()
        if isinstance(prev, dict) and prev.get("intent") in ("system.app.open", "system.app.focus"):
            if any(w in tnorm for w in ["chrome", "google chrome"]):
                set_correction("preferred_browser", "chrome")
            elif any(w in tnorm for w in ["edge", "ms edge", "microsoft edge"]):
                set_correction("preferred_browser", "edge")
    
    
    recalled = resolve_pronouns(text)
    if recalled:
        response = handle_intent(recalled, user_text=text)
        _print_ankita_stream(response)
        publish_ui_state("IDLE")
        return response

    def _looks_like_action(t: str) -> bool:
        if not t:
            return False
        action_prefixes = (
            "open ",
            "launch ",
            "start ",
            "close ",
            "quit ",
            "switch ",
            "switch to ",
            "focus ",
            "go to ",
            "play ",
            "write ",
            "note ",
            "set ",
            "turn ",
            "enable ",
            "disable ",
            "mute",
            "unmute",
            "minimize",
            "maximize",
            "restore",
            "show desktop",
        )
        if t.startswith(action_prefixes):
            return True
        action_keywords = (
            "bluetooth",
            "wifi",
            "volume",
            "brightness",
            "screenshot",
            "shutdown",
            "restart",
            "sleep",
            "timer",
            "remind",
        )
        return any(k in t for k in action_keywords)

    def _needs_realtime(t: str) -> bool:
        if not t:
            return False
        keywords = (
            "latest",
            "today",
            "now",
            "current",
            "news",
            "price",
            "rate",
            "score",
            "weather",
            "update",
            "trending",
        )
        if any(k in t for k in keywords):
            return True
        if t.startswith(("what's the", "whats the", "what is the", "who is", "when is", "where is")) and any(
            k in t for k in ("price", "news", "score", "weather")
        ):
            return True
        return False

    intent_result = classify(text)

    if intent_result["intent"].startswith("conversation."):
        from llm.llm_client import _get_conversational_response
        response = _get_conversational_response(text)
        add_conversation("ankita", response)
        publish_ui_state("IDLE")
        _print_ankita_stream(response)
        return response

    if intent_result["intent"] == "unknown" and not _looks_like_action(tnorm):
        if _needs_realtime(tnorm):
            response = handle_intent({"intent": "web.search", "entities": {"query": text, "max_results": 5}}, user_text=text)
            publish_ui_state("IDLE")
            _print_ankita_stream(response)
            return response

        response = ask_llm(text)
        add_conversation("ankita", response)
        publish_ui_state("IDLE")
        _print_ankita_stream(response)
        return response

    if intent_result["intent"] == "unknown":
        semantic_result = semantic_classify(text)
        if semantic_result.get("intent") != "unknown":
            intent_result = semantic_result

    if intent_result["intent"] == "unknown":
        intent_result = llm_classify(text)

    if intent_result["intent"] == "unknown":
        response = ask_llm(text)
        add_conversation("ankita", response)
        publish_ui_state("IDLE")
        _print_ankita_stream(response)
        return response
    

    # If fallback classifiers returned an intent but no entities, extract deterministically
    if not intent_result.get("entities"):
        intent_result["entities"] = extract(intent_result["intent"], text)

    if intent_result.get("intent") in ("system.app.open", "system.app.focus"):
        app = (intent_result.get("entities") or {}).get("app")
        action = (intent_result.get("entities") or {}).get("action")
        if isinstance(app, str) and app.strip().lower() in ("browser", "web browser"):
            corr = get_correction("preferred_browser")
            if corr in ("chrome", "edge"):
                intent_result["entities"]["app"] = corr
            else:
                pref = get_preference("preferred_browser")
                conf = get_preference_confidence("preferred_browser")
                if pref in ("chrome", "edge") and conf >= 0.75:
                    intent_result["entities"]["app"] = pref
                elif pref in ("chrome", "edge") and conf >= 0.6:
                    intent_result["entities"]["app"] = pref
                    intent_result["_soft_confirm"] = True
                else:
                    _pending_followup = {"type": "choose_browser", "intent": intent_result.get("intent"), "action": action}
                    publish_ui_state("IDLE")
                    response = _jarvis_clarify("Chrome or Edge")
                    add_conversation("ankita", response)
                    _print_ankita_stream(response)
                    return response

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

    # Proactive suggestions (text mode only): suggest, don't act
    if source == "user":
        suggestion = _maybe_make_suggestion(intent_result)
        if suggestion:
            response = f"{response}\n{suggestion}"

    _print_ankita_stream(response)
    publish_ui_state("IDLE")
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
    
    publish_ui_state("IDLE")
    while True:
        try:
            for cmd in poll_ui_commands():
                if cmd.get("type") == "command" and cmd.get("command") == "toggle_sleep":
                    global _ui_sleeping
                    _ui_sleeping = not _ui_sleeping
                    publish_ui_state("SLEEP" if _ui_sleeping else "IDLE")
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
    
    publish_ui_state("IDLE")
    print("[Ankita] Voice mode. Press Enter to speak, 'exit' to quit.\n")
    
    while True:
        try:
            for cmd_msg in poll_ui_commands():
                if cmd_msg.get("type") == "command" and cmd_msg.get("command") == "toggle_sleep":
                    global _ui_sleeping
                    _ui_sleeping = not _ui_sleeping
                    publish_ui_state("SLEEP" if _ui_sleeping else "IDLE")
                if cmd_msg.get("type") == "command" and cmd_msg.get("command") == "open_panel":
                    print("[Ankita] UI panel requested")

            if _ui_sleeping:
                publish_ui_state("SLEEP")
                try:
                    from time import sleep

                    sleep(0.2)
                except Exception:
                    pass
                continue

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
            text_en, meta = _voice_to_english(text)
            if meta.get("translated") and text_en:
                print(f"[Translated->en]: {text_en}")

            response = handle_text(text_en)
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

    _vosk_warned: dict[str, bool] = {}

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
        vosk_enabled = (os.getenv("VOSK_WAKE_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")
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
        if model_path and (vosk_enabled or not access_key):
            try:
                import json
                import vosk
                import sounddevice as sd

                if not os.path.exists(model_path):
                    if not _vosk_warned.get("missing_model"):
                        _vosk_warned["missing_model"] = True
                        print(f"[Wake/Vosk] VOSK_MODEL_PATH not found: {model_path}")
                    return False

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
                if not _vosk_warned.get("vosk_error"):
                    _vosk_warned["vosk_error"] = True
                    print("[Wake/Vosk] Not active. Ensure deps installed: vosk, sounddevice, and a working microphone.")
                return False

        cmd = input("[Idle] Say wake word or press Enter to speak (type 'exit' to quit): ")
        if (cmd or "").strip().lower() in ["exit", "quit", "bye"]:
            return False
        return True

    state = "IDLE"
    publish_ui_state(state)
    speak("Continuous mode enabled.")
    print("[Ankita] Continuous voice mode. Wake word: Jarvis. Stop words: stop/sleep/cancel. Ctrl+C to quit.\n")

    try:
        while True:
            for cmd in poll_ui_commands():
                if cmd.get("type") == "command" and cmd.get("command") == "toggle_sleep":
                    global _ui_sleeping
                    _ui_sleeping = not _ui_sleeping
                    publish_ui_state("SLEEP" if _ui_sleeping else "IDLE")
                if cmd.get("type") == "command" and cmd.get("command") == "open_panel":
                    print("[Ankita] UI panel requested")
            if _ui_sleeping:
                state = "SLEEP"
                publish_ui_state(state)
                try:
                    from time import sleep
                    sleep(0.2)
                except Exception:
                    pass
                continue

            if state == "IDLE":
                publish_ui_state("WAKE_ACTIVE")
                ok = _listen_for_wake()
                if not ok:
                    speak("Goodbye!")
                    break
                state = "LISTENING"
                publish_ui_state(state)

            if state == "LISTENING":
                publish_ui_state(state)
                print("[Listening...]")
                audio_path = record_audio(duration=command_seconds)
                raw = transcribe(audio_path)
                print(f"[You said]: {raw}")

                if not (raw or "").strip():
                    speak("I didn't hear anything.")
                    state = "IDLE"
                    publish_ui_state(state)
                    continue

                if _is_stop(raw):
                    speak("Okay, going idle.")
                    state = "IDLE"
                    publish_ui_state(state)
                    continue

                text_en, meta = _voice_to_english(raw)
                if meta.get("translated") and text_en:
                    print(f"[Translated->en]: {text_en}")

                state = "EXECUTING"
                publish_ui_state(state)
                response = handle_text(text_en)
                speak(response)
                state = "IDLE"
                publish_ui_state(state)

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
    
    publish_ui_state("IDLE")
    print("[Ankita] Hybrid mode.")
    print("  Enter (empty) → Voice | Type text → Text | 'exit' → Quit\n")
    
    while True:
        try:
            for cmd_msg in poll_ui_commands():
                if cmd_msg.get("type") == "command" and cmd_msg.get("command") == "toggle_sleep":
                    global _ui_sleeping
                    _ui_sleeping = not _ui_sleeping
                    publish_ui_state("SLEEP" if _ui_sleeping else "IDLE")
                if cmd_msg.get("type") == "command" and cmd_msg.get("command") == "open_panel":
                    print("[Ankita] UI panel requested")

            if _ui_sleeping:
                publish_ui_state("SLEEP")
                try:
                    from time import sleep

                    sleep(0.2)
                except Exception:
                    pass
                continue

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
                text_en, meta = _voice_to_english(text)
                if meta.get("translated") and text_en:
                    print(f"[Translated->en]: {text_en}")

                response = handle_text(text_en)
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


# ============== SOCIAL ASSISTANT MODE ==============

def run_voice_enrollment():
    """Enroll owner voice for social assistant authentication."""
    from voice.mic import record_audio
    from voice.stt import transcribe
    from voice.tts import speak
    from context.owner_auth import get_owner_auth
    import numpy as np
    import wave
    
    print("\n" + "="*50)
    print("  OWNER VOICE ENROLLMENT")
    print("="*50)
    print("\nThis will record your voice to enable owner-only commands.")
    print("You'll speak 3 phrases to create your voice signature.\n")
    
    auth = get_owner_auth()
    
    if auth.is_enrolled:
        speak("You already have a voice signature. Do you want to re-enroll?")
        response = input("Re-enroll? (yes/no): ").strip().lower()
        if response not in ("yes", "y"):
            speak("Keeping existing voice signature.")
            return
        auth.delete_enrollment()
    
    phrases = [
        "Hello Ankita, this is my voice",
        "I am the owner of this assistant",
        "Only I can control Ankita's responses",
    ]
    
    samples = []
    
    for i, phrase in enumerate(phrases, 1):
        print(f"\n[{i}/3] Please say: \"{phrase}\"")
        speak(f"Phrase {i}. Please say: {phrase}")
        
        input("Press Enter when ready...")
        print("[Recording...]")
        
        audio_path = record_audio(duration=5)
        
        # Load audio as numpy array
        with wave.open(audio_path, 'rb') as wf:
            frames = wf.readframes(wf.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        
        # Verify we got something
        text = transcribe(audio_path)
        if text:
            print(f"[Heard]: {text}")
            samples.append(audio)
        else:
            print("[Warning] Didn't hear anything, but continuing...")
            samples.append(audio)
    
    print("\n[Processing voice signature...]")
    success, message = auth.enroll(samples)
    
    if success:
        speak("Voice enrollment successful! I will only respond to your commands.")
        print(f"\n✓ {message}")
        print("\nYou can now use --social mode with owner-only commands.")
    else:
        speak("Voice enrollment failed. Please try again.")
        print(f"\n✗ {message}")


def run_social_mode():
    """
    Social assistant mode - context-aware, owner-controlled.
    
    Features:
    - Passive listening in group conversations
    - Session context memory
    - Owner-only command triggers
    - Standby/active modes
    """
    from voice.tts import speak
    from context import Mode, TriggerCommand, get_context_manager
    
    manager = get_context_manager()
    
    print("\n" + "="*50)
    print("  SOCIAL ASSISTANT MODE")
    print("="*50)
    
    # Check owner enrollment
    if not manager.is_owner_enrolled:
        print("\n⚠ Owner voice not enrolled!")
        print("  Run: python ankita_core.py --enroll-voice")
        print("  (Continuing without owner verification)\n")
    else:
        print("\n✓ Owner voice recognized")
    
    print("""
Commands (OWNER ONLY):
  "Ankita active"   → Start listening and recording context
  "Ankita standby"  → Pause (stop recording)
  "Ankita answer"   → Respond using context
  "Ankita stop"     → Exit social mode

Status: Starting in STANDBY mode...
""")
    
    def on_answer(context: str):
        """Handle "Ankita answer" command."""
        print(f"\n[Context]: {context[:200]}...")
        
        # Get last question if available
        question = manager.get_last_question()
        if question:
            prompt = f"Based on this conversation context:\n{context}\n\nAnswer this question: {question}"
        else:
            prompt = f"Based on this conversation context:\n{context}\n\nProvide a helpful response."
        
        # Use existing LLM to generate response
        response = ask_llm(prompt)
        
        print(f"\n[Ankita]: {response}")
        speak(response)
        
        # Add our response to context
        manager.add_context("ankita", response, is_owner=False)
    
    def on_mode_change(mode: Mode):
        """Handle mode changes."""
        if mode == Mode.ACTIVE:
            speak("Now listening and recording context.")
        elif mode == Mode.STANDBY:
            speak("Standby mode. Context cleared.")
        elif mode == Mode.OFF:
            speak("Social mode disabled.")
    
    manager.set_answer_callback(on_answer)
    manager.set_mode_callback(on_mode_change)
    
    try:
        manager.start()
        speak("Social assistant ready. Say Ankita active to begin.")
        
        # Keep running until stopped
        while manager.mode != Mode.OFF:
            try:
                time.sleep(0.5)
                
                # Check for UI commands
                for cmd in poll_ui_commands():
                    if cmd.get("type") == "command" and cmd.get("command") == "toggle_sleep":
                        global _ui_sleeping
                        _ui_sleeping = not _ui_sleeping
                        if _ui_sleeping:
                            manager.set_mode(Mode.STANDBY)
                        else:
                            manager.set_mode(Mode.ACTIVE)
                            
            except KeyboardInterrupt:
                break
                
    except Exception as e:
        print(f"[Social Mode Error]: {e}")
    finally:
        manager.stop()
        speak("Social assistant stopped.")


# ============== MAIN ==============

def main():
    parser = argparse.ArgumentParser(description="Ankita AI Assistant")
    parser.add_argument("--voice", action="store_true", help="Voice mode")
    parser.add_argument("--both", action="store_true", help="Hybrid mode")
    parser.add_argument("--continuous", action="store_true", help="Continuous voice mode (wake word + stop word)")
    parser.add_argument("--social", action="store_true", help="Social assistant mode (group context, owner-controlled)")
    parser.add_argument("--enroll-voice", action="store_true", help="Enroll owner voice for social mode")
    parser.add_argument("--no-bubble", action="store_true", help="Disable floating bubble UI")
    args = parser.parse_args()

    _maybe_start_bubble(args)
    
    print()
    print("  █████╗ ███╗   ██╗██╗  ██╗██╗████████╗ █████╗ ")
    print(" ██╔══██╗████╗  ██║██║ ██╔╝██║╚══██╔══╝██╔══██╗")
    print(" ███████║██╔██╗ ██║█████╔╝ ██║   ██║   ███████║")
    print(" ██╔══██║██║╚██╗██║██╔═██╗ ██║   ██║   ██╔══██║")
    print(" ██║  ██║██║ ╚████║██║  ██╗██║   ██║   ██║  ██║")
    print(" ╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝   ╚═╝   ╚═╝  ╚═╝")
    print()
    
    if args.enroll_voice:
        run_voice_enrollment()
    elif args.social:
        run_social_mode()
    elif args.continuous:
        run_continuous_voice_mode()
    elif args.voice:
        run_voice_mode()
    elif args.both:
        run_hybrid_mode()
    else:
        run_text_mode()


if __name__ == "__main__":
    main()
