from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jarvis_nim import JarvisConfig, NimChatError, chat_once, load_dotenv
from memory_system import MemoryConfig, load_memory_context, memory_system_message, remember_chat
from tools import discover_tools


EXIT_WORDS = {"exit", "quit", "bye"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simple NVIDIA NIM assistant CLI.")
    parser.add_argument("message", nargs="*", help="Optional one-shot message.")
    parser.add_argument("--message", "-m", dest="message_option", help="Optional one-shot message.")
    parser.add_argument("--check-env", action="store_true", help="Check required NVIDIA env without sending a chat request.")
    parser.add_argument("--list-tools", action="store_true", help="List registered local tools.")
    return parser


def print_env_check(config: JarvisConfig, tool_count: int) -> None:
    print(f"NVIDIA_BASE_URL -> {config.chat_url}")
    print(f"NVIDIA_MODEL -> {config.model}")
    print("NVIDIA_API_KEY -> set")
    print(f"Registered tools -> {tool_count}")


def build_messages(config: JarvisConfig, registry, memory_config: MemoryConfig) -> list[dict[str, str]]:
    capability_text = registry.capability_text() if config.auto_tools else ""
    messages = [config.system_message(capability_text)]
    memory_message = memory_system_message(load_memory_context(memory_config))
    if memory_message is not None:
        messages.append(memory_message)
    return messages


def should_print_reply(config: JarvisConfig) -> bool:
    return not config.stream


def one_shot(config: JarvisConfig, text: str, registry, memory_config: MemoryConfig) -> None:
    messages = [*build_messages(config, registry, memory_config), {"role": "user", "content": text}]
    print(f"{config.assistant_name}:")
    reply = chat_once(config, messages, registry)
    if should_print_reply(config):
        print(reply)
    remember_chat(memory_config, config, text, reply)


def interactive(config: JarvisConfig, registry, memory_config: MemoryConfig) -> None:
    messages = build_messages(config, registry, memory_config)

    print(f"{config.assistant_name} NIM chat")
    print(f"Model: {config.model}")
    print(f"Tools: {', '.join(tool.name for tool in registry.visible_tools())}")
    print(f"Auto tools: {'on' if config.auto_tools else 'off'}")
    print("Type exit, quit, or bye to leave.\n")

    while True:
        try:
            text = input(f"{config.user_name}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not text:
            continue
        if text.lower() in EXIT_WORDS:
            return

        messages.append({"role": "user", "content": text})
        print(f"{config.assistant_name}: ", end="", flush=True)
        try:
            reply = chat_once(config, messages, registry)
        except NimChatError as error:
            print(str(error))
            continue
        if should_print_reply(config):
            print(reply)
        messages.append({"role": "assistant", "content": reply})
        remember_chat(memory_config, config, text, reply)


def main() -> int:
    load_dotenv(Path.cwd() / ".env")
    args = build_parser().parse_args()

    try:
        config = JarvisConfig.from_env()
        registry = discover_tools()
        memory_config = MemoryConfig.from_env(Path.cwd())
        load_memory_context(memory_config)
        if args.list_tools:
            print(registry.capability_text())
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


if __name__ == "__main__":
    raise SystemExit(main())
