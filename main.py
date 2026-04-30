from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.brain import Brain
from core.speech import (
    MicrophoneListener,
    SpeechConfig,
    SpeechToText,
    create_speech_to_text,
    list_input_devices,
    speech_to_english,
)


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Chat with your personal AI assistant.")
    parser.add_argument("--listen", "-l", action="store_true", help="Start directly in hands-free listening mode.")
    parser.add_argument("--listen-once", action="store_true", help="Listen for one spoken prompt, answer, then exit.")
    parser.add_argument("--list-mics", action="store_true", help="List available microphone input devices.")
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parent
    if args.list_mics:
        for line in list_input_devices():
            print(line)
        return

    brain = Brain.create(project_root)
    speech_config = SpeechConfig.from_env(project_root)

    print(f"{brain.ai_name} is ready. Type 'exit' to stop, '/listen' to speak once, or '/voice' for listening mode.")
    try:
        if args.listen or args.listen_once:
            _voice_loop(brain, speech_config, once=args.listen_once)
            return

        while True:
            user_text = input(f"{brain.user_name}> ").strip()
            if user_text.lower() in {"exit", "quit"}:
                print(f"{brain.ai_name}> Bye.")
                break
            if user_text.lower() == "/listen":
                spoken_text = _listen_once(brain, speech_config)
                if spoken_text and spoken_text.lower() in {"exit", "quit"}:
                    print(f"{brain.ai_name}> Bye.")
                    break
                if spoken_text and spoken_text.lower() == "stop listening":
                    continue
                if spoken_text:
                    _answer(brain, spoken_text)
                continue
            if user_text.lower() == "/voice":
                _voice_loop(brain, speech_config)
                continue
            if not user_text:
                continue

            _answer(brain, user_text)
    except KeyboardInterrupt:
        print("\nStopped.")


def _answer(brain: Brain, user_text: str) -> None:
    print(f"{brain.ai_name}> ", end="", flush=True)
    try:
        for chunk in brain.answer_stream(user_text):
            print(chunk, end="", flush=True)
    except Exception as error:
        print(f"Error: {error}", end="", flush=True)
    print()


def _listen_once(brain: Brain, config: SpeechConfig, speech: SpeechToText | None = None) -> str:
    audio_path: Path | None = None
    try:
        if speech is None:
            speech = _load_speech_engine(config)
            if speech is None:
                return ""
        listener = MicrophoneListener(config)
        print("Listening... speak naturally in any language. Pause when you are done.")
        audio_path = listener.listen_to_wav()
        text = speech_to_english(audio_path, speech, brain.llm, config).strip()
    except Exception as error:
        print(f"Speech error: {error}")
        return ""
    finally:
        if audio_path is not None:
            audio_path.unlink(missing_ok=True)

    if text:
        print(f"{brain.user_name} (speech)> {text}")
    else:
        print("Speech error: I could not detect any speech.")
    return text


def _load_speech_engine(config: SpeechConfig) -> SpeechToText | None:
    if config.provider in {"local", "faster_whisper"}:
        print(f"Loading local speech model '{config.local_model}'...")
    else:
        print("Loading speech engine...")
    try:
        return create_speech_to_text(config)
    except Exception as error:
        print(f"Speech error: {error}")
        return None


def _voice_loop(brain: Brain, config: SpeechConfig, once: bool = False) -> None:
    print("Listening mode is on. Say 'exit' or 'stop listening' to leave voice mode.")
    speech = _load_speech_engine(config)
    if speech is None:
        return
    empty_count = 0
    while True:
        spoken_text = _listen_once(brain, config, speech)
        if not spoken_text:
            if once:
                return
            empty_count += 1
            if empty_count >= 3:
                print("Still not hearing speech. Run 'python main.py --list-mics' and set STT_INPUT_DEVICE if needed.")
                empty_count = 0
            continue
        empty_count = 0
        if spoken_text.lower() in {"exit", "quit"}:
            print(f"{brain.ai_name}> Bye.")
            return
        if spoken_text.lower() == "stop listening":
            print("Listening mode off.")
            return
        _answer(brain, spoken_text)
        if once:
            return


if __name__ == "__main__":
    main()
