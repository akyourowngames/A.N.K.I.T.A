from __future__ import annotations

import argparse
import sys
import threading
from dataclasses import replace
from pathlib import Path

from core.brain import Brain
from core.speech import (
    MicrophoneListener,
    SpeechConfig,
    SpeechToText,
    TTSConfig,
    TextToSpeech,
    create_speech_to_text,
    create_text_to_speech,
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
    parser.add_argument("--mute", action="store_true", help="Start with AI voice output muted.")
    parser.add_argument("--speak", action="store_true", help="Start with AI voice output enabled.")
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parent
    if args.list_mics:
        for line in list_input_devices():
            print(line)
        return

    brain = Brain.create(project_root)
    speech_config = SpeechConfig.from_env(project_root)
    tts_config = TTSConfig.from_env(project_root)
    if args.mute:
        tts_config = replace(tts_config, enabled=False)
    if args.speak:
        tts_config = replace(tts_config, enabled=True)
    voice_output = VoiceOutput(tts_config)

    print(
        f"{brain.ai_name} is ready. Type 'exit' to stop, '/listen' to speak once, "
        f"'/voice' for listening mode, '/mute' to mute, or '/speak' to hear replies."
    )
    try:
        if args.listen or args.listen_once:
            _voice_loop(brain, speech_config, voice_output, once=args.listen_once)
            return

        while True:
            user_text = input(f"{brain.user_name}> ").strip()
            if user_text.lower() in {"exit", "quit"}:
                print(f"{brain.ai_name}> Bye.")
                break
            if _handle_tts_command(user_text, voice_output):
                continue
            if user_text.lower() == "/listen":
                spoken_text = _listen_once(brain, speech_config)
                if spoken_text and spoken_text.lower() in {"exit", "quit"}:
                    print(f"{brain.ai_name}> Bye.")
                    break
                if spoken_text and spoken_text.lower() == "stop listening":
                    continue
                if spoken_text:
                    _answer(brain, spoken_text, voice_output)
                continue
            if user_text.lower() == "/voice":
                _voice_loop(brain, speech_config, voice_output)
                continue
            if not user_text:
                continue

            _answer(brain, user_text, voice_output)
    except KeyboardInterrupt:
        print("\nStopped.")


class VoiceOutput:
    def __init__(self, config: TTSConfig):
        self.config = config
        self.enabled = config.enabled
        self.speaker: TextToSpeech | None = None
        self._speaker_lock = threading.Lock()
        self._audio_lock = threading.Lock()
        if self.enabled:
            self.preload_async()

    def status(self) -> str:
        state = "on" if self.enabled else "muted"
        return (
            f"Voice output is {state}. Voice={self.config.voice}, "
            f"rate={self.config.rate}, pitch={self.config.pitch}."
        )

    def mute(self) -> None:
        self.enabled = False

    def unmute(self) -> bool:
        self.enabled = True
        return self._ensure_loaded()

    def set_voice(self, voice: str) -> None:
        with self._speaker_lock:
            self.config = replace(self.config, voice=voice)
            self.speaker = None

    def set_rate(self, rate: str) -> None:
        with self._speaker_lock:
            self.config = replace(self.config, rate=rate)
            self.speaker = None

    def set_volume(self, volume: str) -> None:
        with self._speaker_lock:
            self.config = replace(self.config, volume=volume)
            self.speaker = None

    def set_pitch(self, pitch: str) -> None:
        with self._speaker_lock:
            self.config = replace(self.config, pitch=pitch)
            self.speaker = None

    def preload_async(self) -> None:
        threading.Thread(target=self._ensure_loaded, daemon=True).start()

    def speak_async(self, text: str) -> threading.Thread | None:
        if not self.enabled or not text.strip():
            return None
        thread = threading.Thread(target=self.speak, args=(text,), daemon=True)
        thread.start()
        return thread

    def speak(self, text: str) -> None:
        if not self.enabled or not text.strip():
            return
        if not self._ensure_loaded():
            return
        try:
            with self._speaker_lock:
                speaker = self.speaker
            if speaker is not None:
                with self._audio_lock:
                    speaker.speak(text)
        except Exception as error:
            print(f"Voice error: {error}")

    def _ensure_loaded(self) -> bool:
        with self._speaker_lock:
            if self.speaker is not None:
                return True
            try:
                self.speaker = create_text_to_speech(self.config)
                return True
            except Exception as error:
                self.enabled = False
                print(f"Voice error: {error}")
                return False


def _answer(
    brain: Brain,
    user_text: str,
    voice_output: VoiceOutput | None = None,
    *,
    wait_for_voice: bool = False,
) -> None:
    print(f"{brain.ai_name}> ", end="", flush=True)
    reply_parts: list[str] = []
    try:
        for chunk in brain.answer_stream(user_text):
            print(chunk, end="", flush=True)
            reply_parts.append(chunk)
    except Exception as error:
        print(f"Error: {error}", end="", flush=True)
    print()
    voice_thread = voice_output.speak_async("".join(reply_parts)) if voice_output is not None else None
    if wait_for_voice and voice_thread is not None:
        voice_thread.join()


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


def _handle_tts_command(user_text: str, voice_output: VoiceOutput) -> bool:
    command = user_text.strip()
    lowered = command.lower()
    if lowered in {"/mute", "/tts off", "/tts mute"}:
        voice_output.mute()
        print("Voice output muted.")
        return True
    if lowered in {"/speak", "/tts on", "/tts speak", "/unmute"}:
        if voice_output.unmute():
            print("Voice output on.")
        return True
    if lowered in {"/tts", "/tts status"}:
        print(voice_output.status())
        return True
    if lowered == "/tts faster":
        voice_output.set_rate("+34%")
        print("Voice rate changed to +34%.")
        return True
    if lowered == "/tts slower":
        voice_output.set_rate("+12%")
        print("Voice rate changed to +12%.")
        return True
    if lowered == "/tts loud":
        voice_output.set_volume("+100%")
        print("Voice volume changed to +100%.")
        return True
    if lowered.startswith("/tts voice "):
        voice = _voice_alias(command.split(maxsplit=2)[2].strip())
        voice_output.set_voice(voice)
        print(f"Voice changed to {voice}.")
        return True
    if lowered.startswith("/tts rate "):
        rate = command.split(maxsplit=2)[2].strip()
        voice_output.set_rate(rate)
        print(f"Voice rate changed to {rate}.")
        return True
    if lowered.startswith("/tts volume "):
        volume = command.split(maxsplit=2)[2].strip()
        voice_output.set_volume(volume)
        print(f"Voice volume changed to {volume}.")
        return True
    if lowered.startswith("/tts pitch "):
        pitch = command.split(maxsplit=2)[2].strip()
        voice_output.set_pitch(pitch)
        print(f"Voice pitch changed to {pitch}.")
        return True
    return False


def _voice_alias(value: str) -> str:
    aliases = {
        "male": "Magpie-Multilingual.EN-US.Jason",
        "man": "Magpie-Multilingual.EN-US.Jason",
        "heavy": "Magpie-Multilingual.EN-US.Jason",
        "deep": "Magpie-Multilingual.EN-US.Jason",
        "jarvis": "Magpie-Multilingual.EN-US.Jason",
        "ray": "Magpie-Multilingual.EN-US.Ray",
        "jason": "Magpie-Multilingual.EN-US.Jason",
        "leo": "Magpie-Multilingual.EN-US.Leo",
        "diego": "Magpie-Multilingual.EN-US.Diego",
        "female": "Magpie-Multilingual.EN-US.Aria",
        "woman": "Magpie-Multilingual.EN-US.Aria",
        "aria": "Magpie-Multilingual.EN-US.Aria",
    }
    return aliases.get(value.strip().lower(), value)


def _handle_spoken_tts_command(spoken_text: str, voice_output: VoiceOutput) -> bool:
    normalized = spoken_text.strip().lower().strip(" .!?")
    if normalized in {"mute yourself", "be quiet", "stop speaking", "mute voice", "voice mute"}:
        voice_output.mute()
        print("Voice output muted.")
        return True
    if normalized in {"speak again", "start speaking", "unmute yourself", "voice on"}:
        if voice_output.unmute():
            print("Voice output on.")
        return True
    if normalized in {"talk faster", "speak faster"}:
        voice_output.set_rate("+34%")
        print("Voice rate changed to +34%.")
        return True
    if normalized in {"talk louder", "speak louder", "louder"}:
        voice_output.set_volume("+100%")
        print("Voice volume changed to +100%.")
        return True
    return False


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


def _voice_loop(brain: Brain, config: SpeechConfig, voice_output: VoiceOutput, once: bool = False) -> None:
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
        spoken_command = spoken_text.strip().lower().strip(" .!?")
        if spoken_command in {"exit", "quit"}:
            print(f"{brain.ai_name}> Bye.")
            return
        if spoken_command == "stop listening":
            print("Listening mode off.")
            return
        if _handle_spoken_tts_command(spoken_text, voice_output):
            if once:
                return
            continue
        _answer(brain, spoken_text, voice_output, wait_for_voice=True)
        if once:
            return


if __name__ == "__main__":
    main()
