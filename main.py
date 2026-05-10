from __future__ import annotations

import argparse
import sys
from pathlib import Path

from extension_system import ExtensionCatalog, load_extension_catalog
from jarvis_nim import JarvisConfig, NimChatError, chat_once, load_dotenv
from memory_system import MemoryConfig, load_memory_context, memory_system_message, remember_chat
from skill_system import load_skill_context
from tools import discover_tools
from vector_memory import VectorMemoryConfig, load_vector_memory_context
from voice_system import (
    VoiceConfig,
    VoiceError,
    VoiceSpeaker,
    listen_once,
    microphone_level_report,
    microphone_report,
    read_text_or_voice,
    speak_text_blocking,
    synthesize_nvidia_tts,
    transcribe_nvidia_audio_at_rate,
    voice_catalog_text,
    voice_status_text,
    wait_for_output_idle,
)


EXIT_WORDS = {"exit", "quit", "bye"}
SPEECH_OFF_COMMAND = "/speakoff"
SPEECH_ON_COMMAND = "/speakon"


def configure_stream_encoding(stream) -> bool:
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return False
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return False
    return True


def configure_console_output() -> None:
    configure_stream_encoding(sys.stdout)
    configure_stream_encoding(sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simple NVIDIA NIM assistant CLI.")
    parser.add_argument("message", nargs="*", help="Optional one-shot message.")
    parser.add_argument("--message", "-m", dest="message_option", help="Optional one-shot message.")
    parser.add_argument("--check-env", action="store_true", help="Check required NVIDIA env without sending a chat request.")
    parser.add_argument("--check-voice", action="store_true", help="Check STT/TTS voice configuration and local audio packages.")
    parser.add_argument("--list-mics", action="store_true", help="List input microphones available to Jarvis voice mode.")
    parser.add_argument("--voice-levels", action="store_true", help="Measure microphone noise level and the active speech threshold.")
    parser.add_argument("--list-voices", action="store_true", help="List NVIDIA English TTS voices available to the configured endpoint.")
    parser.add_argument("--voice-say", help="Speak text through the configured TTS provider.")
    parser.add_argument("--voice-roundtrip", help="Live test NVIDIA TTS audio through NVIDIA STT without using the microphone.")
    parser.add_argument("--voice-listen-test", action="store_true", help="Listen once from the microphone and print the transcript.")
    parser.add_argument("--list-tools", action="store_true", help="List registered local tools.")
    parser.add_argument("--list-extensions", action="store_true", help="List enabled Jarvis extensions.")
    return parser


def print_env_check(config: JarvisConfig, tool_count: int) -> None:
    print(f"NVIDIA_BASE_URL -> {config.chat_url}")
    print(f"NVIDIA_MODEL -> {config.model}")
    print("NVIDIA_API_KEY -> set")
    print(f"Registered tools -> {tool_count}")


def build_messages(
    config: JarvisConfig,
    registry,
    memory_config: MemoryConfig,
    extension_catalog: ExtensionCatalog,
    user_text: str = "",
) -> list[dict[str, str]]:
    capability_text = build_capability_context(config, registry, extension_catalog)
    messages = [config.system_message(capability_text)]
    memory_message = memory_system_message(load_memory_context(memory_config))
    if memory_message is not None:
        messages.append(memory_message)
    vector_message = vector_memory_system_message(user_text, memory_config, config)
    if vector_message is not None:
        messages.append(vector_message)
    return messages


def vector_memory_system_message(
    user_text: str,
    memory_config: MemoryConfig,
    config: JarvisConfig,
) -> dict[str, str] | None:
    vector_config = VectorMemoryConfig.from_env(Path.cwd())
    context = load_vector_memory_context(user_text, memory_config, vector_config, config)
    if not context.strip():
        return None
    return {"role": "system", "content": context}


def build_capability_context(config: JarvisConfig, registry, extension_catalog: ExtensionCatalog) -> str:
    parts: list[str] = []
    if config.auto_tools:
        parts.append(registry.capability_text())
    extension_prompt = extension_catalog.prompt_context()
    if extension_prompt:
        parts.append("Extension prompt context:\n" + extension_prompt)
    skill_context = load_skill_context(extension_catalog, Path.cwd())
    if skill_context:
        parts.append(skill_context)
    if extension_catalog.extensions:
        parts.append("Enabled extensions:\n" + "\n".join(extension_catalog.status_lines()))
    return "\n\n".join(part for part in parts if part.strip()).strip()


def should_print_reply(config: JarvisConfig) -> bool:
    return not config.stream


def interactive_speech_command(text: str, current_enabled: bool, voice_config: VoiceConfig) -> tuple[bool, bool, str]:
    command = text.strip().casefold()
    if command == SPEECH_OFF_COMMAND:
        return True, False, "Speech output is off."
    if command == SPEECH_ON_COMMAND:
        if not voice_config.tts_enabled:
            return True, False, "Speech output is unavailable because TTS is disabled."
        return True, True, "Speech output is on."
    return False, current_enabled, ""


def one_shot(config: JarvisConfig, text: str, registry, memory_config: MemoryConfig) -> None:
    voice_config = VoiceConfig.from_env()
    extension_catalog = load_extension_catalog()
    messages = [
        *build_messages(config, registry, memory_config, extension_catalog, text),
        {"role": "user", "content": text},
    ]
    print(f"{config.assistant_name}:")
    reply = chat_once(config, messages, registry)
    if should_print_reply(config):
        print(reply)
    if voice_config.tts_speak_oneshot:
        speak_text_blocking(voice_config, reply)
    remember_chat(memory_config, config, text, reply)


def interactive(config: JarvisConfig, registry, memory_config: MemoryConfig) -> None:
    voice_config = VoiceConfig.from_env()
    speaker = VoiceSpeaker(voice_config)
    speech_enabled = voice_config.tts_enabled
    extension_catalog = load_extension_catalog()
    messages = build_messages(config, registry, memory_config, extension_catalog)

    print(f"{config.assistant_name} NIM chat")
    print(f"Model: {config.model}")
    print(f"Tools: {', '.join(tool.name for tool in registry.visible_tools())}")
    print(f"Auto tools: {'on' if config.auto_tools else 'off'}")
    if voice_config.space_trigger and voice_config.stt_enabled:
        print("Voice: press Space on an empty prompt to talk.")
    if voice_config.tts_enabled:
        print(f"Speech: {voice_config.tts_provider} / {voice_config.tts_voice or 'server default'}")
        print("Speech commands: /speakoff, /speakon")
    print("Type exit, quit, or bye to leave.\n")

    try:
        while True:
            try:
                text = read_text_or_voice(
                    f"{config.user_name}: ",
                    voice_config,
                    listener=lambda: listen_once(voice_config),
                    before_listen=lambda: wait_for_output_idle(voice_config, speaker),
                ).strip()
            except VoiceError as error:
                print(f"Voice input failed: {error}")
                continue
            except (EOFError, KeyboardInterrupt):
                print()
                return

            if not text:
                continue
            if text.lower() in EXIT_WORDS:
                return
            handled, speech_enabled, command_reply = interactive_speech_command(text, speech_enabled, voice_config)
            if handled:
                print(f"{config.assistant_name}: {command_reply}")
                continue

            turn_messages = [*messages]
            vector_message = vector_memory_system_message(text, memory_config, config)
            if vector_message is not None:
                turn_messages.append(vector_message)
            turn_messages.append({"role": "user", "content": text})
            print(f"{config.assistant_name}: ", end="", flush=True)
            try:
                reply = chat_once(config, turn_messages, registry)
            except NimChatError as error:
                print(str(error))
                continue
            if should_print_reply(config):
                print(reply)
            if speech_enabled:
                speaker.say(reply)
            messages.append({"role": "user", "content": text})
            messages.append({"role": "assistant", "content": reply})
            remember_chat(memory_config, config, text, reply)
    finally:
        speaker.close()


def main() -> int:
    configure_console_output()
    load_dotenv(Path.cwd() / ".env")
    args = build_parser().parse_args()

    try:
        voice_config = VoiceConfig.from_env()
        if args.check_voice:
            print(voice_status_text(voice_config))
            return 0

        if args.list_mics:
            print(microphone_report())
            return 0

        if args.voice_levels:
            print(microphone_level_report(voice_config))
            return 0

        if args.list_voices:
            print(voice_catalog_text(voice_config))
            return 0

        if args.voice_say:
            speak_text_blocking(voice_config, args.voice_say)
            print("Voice output completed.")
            return 0

        if args.voice_roundtrip:
            audio = synthesize_nvidia_tts(voice_config, args.voice_roundtrip, streaming=False)
            transcript = transcribe_nvidia_audio_at_rate(voice_config, audio, voice_config.tts_sample_rate)
            print(transcript)
            return 0

        if args.voice_listen_test:
            transcript = listen_once(voice_config)
            print(transcript if transcript else "No speech detected.")
            return 0

        config = JarvisConfig.from_env()
        extension_catalog = load_extension_catalog()
        registry = discover_tools(extension_catalog=extension_catalog)
        memory_config = MemoryConfig.from_env(Path.cwd())
        load_memory_context(memory_config)
        if args.list_tools:
            print(registry.capability_text())
            return 0

        if args.list_extensions:
            if extension_catalog.extensions:
                print("Enabled extensions:")
                print("\n".join(extension_catalog.status_lines()))
            else:
                print("Enabled extensions: none")
            return 0

        if args.check_env:
            print_env_check(config, len(registry.visible_tools()))
            return 0

        text = args.message_option or " ".join(args.message).strip()
        if text:
            one_shot(config, text, registry, memory_config)
            return 0

        interactive(config, registry, memory_config)
        return 0
    except NimChatError as error:
        print(str(error), file=sys.stderr)
        return 1
    except VoiceError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
