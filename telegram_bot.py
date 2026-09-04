from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.brain import Brain
from core.telegram_audio import AudioTranscript, FasterWhisperAudioTranscriber
from tool.local_files import FILE_TYPE_GROUPS, SKIPPED_DIRECTORIES, TEXT_EXTENSIONS
from tool.local_paths import KNOWN_FOLDER_ALIASES, ensure_allowed_path, format_allowed_roots, resolve_local_path


API_ROOT = "https://api.telegram.org/bot{token}/{method}"
FILE_API_ROOT = "https://api.telegram.org/file/bot{token}/{path}"
MAX_TELEGRAM_MESSAGE = 3900


@dataclass(frozen=True)
class TelegramAttachment:
    file_id: str
    unique_id: str
    file_name: str
    kind: str
    mime_type: str
    file_size: int


@dataclass(frozen=True)
class TelegramConfig:
    download_root: Path
    export_root: Path
    max_send_mb: float
    max_batch_send: int
    list_limit: int
    search_limit: int
    search_depth: int
    upload_timeout_seconds: int
    request_timeout_seconds: int
    typing_actions: bool

    @classmethod
    def from_env(cls, project_root: Path) -> "TelegramConfig":
        download_root = _env_path("TELEGRAM_DOWNLOAD_DIR", project_root / "memory" / "store" / "telegram_downloads")
        export_root = _env_path("TELEGRAM_EXPORT_DIR", project_root / "memory" / "store" / "telegram_exports")
        return cls(
            download_root=download_root,
            export_root=export_root,
            max_send_mb=max(1.0, _env_float("TELEGRAM_MAX_SEND_MB", 50.0)),
            max_batch_send=max(1, _env_int("TELEGRAM_MAX_BATCH_SEND", 5)),
            list_limit=max(1, _env_int("TELEGRAM_LIST_LIMIT", 25)),
            search_limit=max(1, _env_int("TELEGRAM_SEARCH_LIMIT", 20)),
            search_depth=max(1, _env_int("TELEGRAM_SEARCH_DEPTH", 4)),
            upload_timeout_seconds=max(10, _env_int("TELEGRAM_UPLOAD_TIMEOUT_SECONDS", 180)),
            request_timeout_seconds=max(10, _env_int("TELEGRAM_REQUEST_TIMEOUT_SECONDS", 35)),
            typing_actions=_env_bool("TELEGRAM_TYPING_ACTIONS", True),
        )


class TelegramBot:
    def __init__(
        self,
        brain: Brain,
        token: str,
        allowed_chat_id: str = "",
        config: TelegramConfig | None = None,
        transcriber: FasterWhisperAudioTranscriber | None = None,
    ) -> None:
        self.brain = brain
        self.token = token
        self.allowed_chat_id = allowed_chat_id.strip()
        self.offset = 0
        self.config = config or TelegramConfig.from_env(brain.paths.root)
        self.transcriber = transcriber or FasterWhisperAudioTranscriber.from_env(brain.paths.root)
        self.file_choices: dict[str, list[Path]] = {}

    def run(self, poll_seconds: float = 1.0) -> None:
        print("Telegram bot bridge is running. Press Ctrl+C to stop.")
        while True:
            try:
                for update in self.get_updates():
                    self.handle_update(update)
            except KeyboardInterrupt:
                raise
            except Exception as error:
                print(f"Telegram polling error: {error}")
                time.sleep(max(poll_seconds, 3.0))
            time.sleep(poll_seconds)

    def get_updates(self) -> list[dict[str, Any]]:
        params = {"timeout": 25, "offset": self.offset}
        response = self._request("getUpdates", params)
        updates = response.get("result", [])
        if updates:
            self.offset = max(update["update_id"] for update in updates) + 1
        return updates

    def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "")
        if not chat_id:
            return
        if self.allowed_chat_id and chat_id != self.allowed_chat_id:
            self.send_message(chat_id, "This JARVIS bridge is private.")
            return

        text = str(message.get("text") or message.get("caption") or "").strip()
        attachment = self._attachment_from_message(message)
        if attachment is not None:
            self.handle_attachment(chat_id, attachment, text)
            return

        if not text:
            return
        if self.handle_telegram_text(chat_id, text):
            return

        self.send_chat_action(chat_id, "typing")
        try:
            reply = self.brain.answer(text).strip() or "Done, sir."
        except Exception as error:
            reply = f"Sorry sir, Telegram bridge error: {error}"
        self.send_message(chat_id, reply)
        self._send_artifacts_from_reply(chat_id, text, reply)

    def handle_telegram_text(self, chat_id: str, text: str) -> bool:
        command = text.strip()
        lowered = command.casefold()
        if self._looks_like_soft_ack(command):
            self.send_message(chat_id, self._soft_ack_text(command))
            return True
        if lowered in {"/start", "/help", "help", "what can you do", "what can you do on telegram"}:
            self.send_message(chat_id, self.help_text())
            return True
        if lowered in {"/features", "features"}:
            self.send_message(chat_id, self.features_text())
            return True
        if lowered in {"/status", "status"}:
            self.send_message(chat_id, self.status_text())
            return True
        if lowered in {"/roots", "/folders", "where can you browse"}:
            self.send_message(chat_id, format_allowed_roots())
            return True
        if lowered in {"/choices", "/where", "/cache"}:
            self.send_message(chat_id, self._choices_text(chat_id))
            return True
        if lowered == "/transcribe_status":
            self.send_message(chat_id, "Telegram audio transcription is " + self.transcriber.status() + ".")
            return True

        slash, argument = _slash_command(command)
        if slash in {"/files", "/ls", "/list"}:
            self._send_file_listing(chat_id, argument)
            return True
        if slash == "/recent":
            self._send_recent_files(chat_id, argument)
            return True
        if slash == "/search":
            self._send_file_search(chat_id, argument)
            return True
        if slash == "/read":
            self._send_file_read(chat_id, argument)
            return True
        if slash in {"/stat", "/info"}:
            self._send_file_stat(chat_id, argument)
            return True
        if slash in {"/send", "/get", "/download"}:
            self._send_requested_files(chat_id, argument, as_photo=False)
            return True
        if slash in {"/photo", "/image"}:
            self._send_requested_files(chat_id, argument, as_photo=True)
            return True

        if self._looks_like_read_request(command):
            self._send_file_read(chat_id, self._reference_argument_from_text(command))
            return True
        if self._looks_like_info_request(command):
            self._send_file_stat(chat_id, self._reference_argument_from_text(command))
            return True
        if self._looks_like_list_request(command):
            self._send_file_listing(chat_id, self._path_hint_from_text(command))
            return True
        if self._looks_like_recent_request(command):
            self._send_recent_files(chat_id, self._path_hint_from_text(command))
            return True
        if self._looks_like_search_request(command):
            self._send_file_search(chat_id, self._search_argument_from_text(command))
            return True
        if self._looks_like_send_request(command):
            self._send_requested_files(chat_id, self._send_argument_from_text(command), as_photo=False)
            return True
        return False

    def handle_attachment(self, chat_id: str, attachment: TelegramAttachment, caption: str = "") -> None:
        try:
            self.send_chat_action(chat_id, "typing")
            local_path = self.download_attachment(chat_id, attachment)
            self._remember_choices(chat_id, [local_path])
        except Exception as error:
            self.send_message(chat_id, f"Sorry sir, I could not download that Telegram file: {error}")
            return

        if self._is_transcribable_attachment(attachment, local_path):
            self._handle_audio_attachment(chat_id, local_path, caption)
            return

        summary = [
            "Saved Telegram file.",
            f"Name: {local_path.name}",
            f"Path: {local_path}",
            "Use /send 1 to send it back, /read 1 for text files, or ask normally about it.",
        ]
        self.send_message(chat_id, "\n".join(summary))

    def _handle_audio_attachment(self, chat_id: str, audio_path: Path, caption: str) -> None:
        try:
            self.send_chat_action(chat_id, "typing")
            self.send_message(chat_id, f"Transcribing {audio_path.name} locally...")
            transcript = self.transcriber.transcribe_file(audio_path)
        except Exception as error:
            self.send_message(chat_id, f"Sorry sir, audio transcription failed: {error}")
            return

        if not transcript.text:
            self.send_message(chat_id, "I could not hear clear speech in that audio.")
            return

        self.send_message(chat_id, self._transcript_text(transcript))
        audio_text = caption.strip() + "\n" + transcript.text if caption.strip() else transcript.text
        if self.handle_telegram_text(chat_id, transcript.text):
            return

        self.send_chat_action(chat_id, "typing")
        try:
            reply = self.brain.answer(audio_text).strip() or "Done, sir."
        except Exception as error:
            reply = f"Sorry sir, Telegram audio bridge error: {error}"
        self.send_message(chat_id, reply)

    def help_text(self) -> str:
        tools = self._tool_names_text()
        lines = [
            "JARVIS Telegram bridge is online.",
            "Talk normally: send desktop.ini, show desktop files, find invoice in downloads, read the first one, play music, search online deeply, check weather, open apps, draft mail, or ask calendar questions.",
            "Voice notes and audio files are transcribed locally with faster-whisper when installed.",
        ]
        if tools:
            lines.append("Connected tools: " + tools)
        return "\n".join(lines)

    def features_text(self) -> str:
        features = [
            "1. Normal Brain chat from Telegram.",
            "2. Private chat allow-list with TELEGRAM_ALLOWED_CHAT_ID.",
            "3. Natural folder listing with numbered choices.",
            "4. Natural file listing like 'list files in desktop'.",
            "5. Natural fixed-string local file search.",
            "6. /recent modified-file view.",
            "7. Natural number-or-path document upload.",
            "8. Folder auto-zip before upload.",
            "9. /read text file preview.",
            "10. /stat file metadata.",
            "11. Incoming Telegram file download to local memory store.",
            "12. Voice/audio/video-note transcription in any Whisper-supported language.",
            "13. Audio transcript can trigger file commands or normal Brain replies.",
            "14. Current numbered file cache for normal follow-ups.",
            "15. Typing/upload chat actions so Telegram feels alive.",
        ]
        return "\n".join(features)

    def status_text(self) -> str:
        choices = sum(len(items) for items in self.file_choices.values())
        roots_mode = "restricted" if os.getenv("LOCAL_FILE_RESTRICT_TO_ALLOWED_PATHS", "false").strip().lower() in {"1", "true", "yes", "on"} else "open"
        return "\n".join(
            [
                "Telegram bridge status:",
                f"Audio transcription: {self.transcriber.status()}",
                f"Local files: {roots_mode} roots",
                f"Download folder: {self.config.download_root}",
                f"Export folder: {self.config.export_root}",
                f"Max send size: {self.config.max_send_mb:.1f} MB",
                f"Cached choices in this process: {choices}",
            ]
        )

    def send_message(self, chat_id: str, text: str) -> None:
        for chunk in split_message(text):
            self._request("sendMessage", {"chat_id": chat_id, "text": chunk})

    def send_chat_action(self, chat_id: str, action: str) -> None:
        if not self.config.typing_actions:
            return
        try:
            self._request("sendChatAction", {"chat_id": chat_id, "action": action})
        except Exception:
            return

    def send_document(self, chat_id: str, path: Path, caption: str = "") -> None:
        target = path
        if target.is_dir():
            target = self._zip_folder(target)
        self._check_send_size(target)
        self.send_chat_action(chat_id, "upload_document")
        params = {"chat_id": chat_id}
        if caption:
            params["caption"] = caption
        self._request(
            "sendDocument",
            params,
            files={"document": target},
            timeout=self.config.upload_timeout_seconds,
        )

    def send_photo(self, chat_id: str, path: Path, caption: str = "") -> None:
        self._check_send_size(path)
        self.send_chat_action(chat_id, "upload_photo")
        params = {"chat_id": chat_id}
        if caption:
            params["caption"] = caption
        self._request(
            "sendPhoto",
            params,
            files={"photo": path},
            timeout=self.config.upload_timeout_seconds,
        )

    def download_attachment(self, chat_id: str, attachment: TelegramAttachment) -> Path:
        response = self._request("getFile", {"file_id": attachment.file_id})
        file_path = str((response.get("result") or {}).get("file_path") or "")
        if not file_path:
            raise RuntimeError("Telegram did not return a downloadable file path.")
        url = FILE_API_ROOT.format(token=self.token, path=urllib.parse.quote(file_path, safe="/"))
        folder = self.config.download_root / _safe_filename(chat_id)
        folder.mkdir(parents=True, exist_ok=True)
        file_name = _safe_filename(attachment.file_name or Path(file_path).name or attachment.file_id)
        unique = _safe_filename(attachment.unique_id or attachment.file_id)
        target = _unique_path(folder / f"{unique}-{file_name}")
        with urllib.request.urlopen(url, timeout=self.config.request_timeout_seconds) as response_body:
            target.write_bytes(response_body.read())
        return target

    def _request(
        self,
        method: str,
        params: dict[str, Any],
        files: dict[str, Path] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        url = API_ROOT.format(token=self.token, method=method)
        if files:
            data, content_type = encode_multipart_form_data(params, files)
            request = urllib.request.Request(
                url,
                data=data,
                method="POST",
                headers={"Content-Type": content_type},
            )
        else:
            data = urllib.parse.urlencode(params).encode("utf-8")
            request = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(request, timeout=timeout or self.config.request_timeout_seconds) as response:
            body = response.read().decode("utf-8")
        payload = json.loads(body)
        if not payload.get("ok"):
            raise RuntimeError(payload)
        return payload

    def _send_file_listing(self, chat_id: str, path_text: str) -> None:
        target = self._target_folder(path_text)
        if not target.exists():
            self.send_message(chat_id, f"Path does not exist: {target}")
            return
        if target.is_file():
            self._remember_choices(chat_id, [target])
            self.send_message(chat_id, self._file_line(1, target, target.parent))
            return

        entries = self._sort_entries(self._safe_children(target))[: self.config.list_limit]
        self._remember_choices(chat_id, entries)
        lines = [f"{self._folder_label(target)} has {len(entries)} visible item(s):"]
        if not entries:
            lines.append("(empty or no visible files)")
        for index, item in enumerate(entries, start=1):
            lines.append(self._file_line(index, item, target))
        self.send_message(chat_id, "\n".join(lines))

    def _send_recent_files(self, chat_id: str, path_text: str) -> None:
        target = self._target_folder(path_text)
        if not target.exists():
            self.send_message(chat_id, f"Path does not exist: {target}")
            return
        entries = [item for item in self._walk_files(target, self.config.search_depth) if item.is_file()]
        entries.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
        entries = entries[: self.config.list_limit]
        self._remember_choices(chat_id, entries)
        lines = [f"Recent files under {self._folder_label(target)}:"]
        if not entries:
            lines.append("(no files found)")
        for index, item in enumerate(entries, start=1):
            lines.append(self._file_line(index, item, target))
        self.send_message(chat_id, "\n".join(lines))

    def _send_file_search(self, chat_id: str, argument: str) -> None:
        query, path_text = self._split_search_argument(argument)
        if not query:
            self.send_message(chat_id, "Use /search words in Desktop or /search words.")
            return
        target = self._target_folder(path_text)
        if not target.exists():
            self.send_message(chat_id, f"Path does not exist: {target}")
            return
        matches = self._search_files(target, query)
        self._remember_choices(chat_id, matches)
        lines = [f"Matches for {query} under {self._folder_label(target)}:"]
        if not matches:
            lines.append("(no matching local files)")
        for index, item in enumerate(matches, start=1):
            lines.append(self._file_line(index, item, target))
        self.send_message(chat_id, "\n".join(lines))

    def _send_file_read(self, chat_id: str, argument: str) -> None:
        try:
            targets = self._targets_from_argument(chat_id, argument)
        except Exception as error:
            self.send_message(chat_id, f"Could not resolve file: {error}")
            return
        if not targets:
            self.send_message(chat_id, "I need a file reference to read.")
            return
        target = targets[0]
        if target.is_dir():
            self._send_file_listing(chat_id, str(target))
            return
        if not self._is_readable_text(target):
            self.send_message(chat_id, f"{target.name} is not a text-like file, so I can send it instead.")
            return
        max_chars = max(1000, _env_int("TELEGRAM_READ_MAX_CHARS", 3500))
        text = target.read_text(encoding="utf-8", errors="replace")
        body = text[:max_chars]
        suffix = f"\n\n... truncated after {max_chars} characters" if len(text) > max_chars else ""
        self.send_message(chat_id, f"File: {target}\n\n{body}{suffix}")

    def _send_file_stat(self, chat_id: str, argument: str) -> None:
        try:
            targets = self._targets_from_argument(chat_id, argument)
        except Exception as error:
            self.send_message(chat_id, f"Could not resolve file: {error}")
            return
        if not targets:
            self.send_message(chat_id, "I need a file or folder reference to inspect.")
            return
        target = targets[0]
        stat = target.stat()
        kind = "folder" if target.is_dir() else "file"
        lines = [
            f"Path: {target}",
            f"Kind: {kind}",
            f"Size: {_human_size(_folder_size(target) if target.is_dir() else stat.st_size)}",
            f"Modified: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))}",
        ]
        self.send_message(chat_id, "\n".join(lines))

    def _send_requested_files(self, chat_id: str, argument: str, as_photo: bool) -> None:
        try:
            targets = self._targets_from_argument(chat_id, argument)
        except Exception as error:
            self.send_message(chat_id, f"Could not resolve file to send: {error}")
            return
        if not targets:
            self.send_message(chat_id, "I need a file reference to send.")
            return

        sent = 0
        for target in targets[: self.config.max_batch_send]:
            try:
                caption = f"{target.name}"
                if as_photo and target.suffix.lower() in FILE_TYPE_GROUPS["image"] and target.is_file():
                    self.send_photo(chat_id, target, caption)
                else:
                    self.send_document(chat_id, target, caption)
                sent += 1
            except Exception as error:
                self.send_message(chat_id, f"Could not send {target}: {error}")
        if len(targets) > self.config.max_batch_send:
            self.send_message(chat_id, f"Sent {sent}; batch limited to {self.config.max_batch_send} files.")

    def _choices_text(self, chat_id: str) -> str:
        choices = self.file_choices.get(chat_id, [])
        if not choices:
            return "No numbered file choices yet. Ask me to show a folder or find a file first."
        lines = ["Current numbered choices:"]
        for index, item in enumerate(choices[: self.config.list_limit], start=1):
            lines.append(self._file_line(index, item, item.parent))
        return "\n".join(lines)

    def _target_folder(self, path_text: str) -> Path:
        hint = path_text.strip() or os.getenv("LOCAL_FILE_DEFAULT_PATH", "").strip()
        return ensure_allowed_path(hint) if hint else resolve_local_path("")

    def _safe_children(self, target: Path) -> list[Path]:
        try:
            items = list(target.iterdir())
        except OSError:
            return []
        visible: list[Path] = []
        for item in items:
            if item.name.startswith("."):
                continue
            if item.is_dir() and item.name in SKIPPED_DIRECTORIES:
                continue
            visible.append(item)
        return visible

    def _walk_files(self, target: Path, max_depth: int) -> list[Path]:
        if target.is_file():
            return [target]
        results: list[Path] = []
        pending: list[tuple[Path, int]] = [(target, 0)]
        while pending and len(results) < self.config.search_limit * 4:
            current, depth = pending.pop(0)
            if depth >= max_depth:
                continue
            for item in self._safe_children(current):
                results.append(item)
                if item.is_dir() and item.name not in SKIPPED_DIRECTORIES:
                    pending.append((item, depth + 1))
        return results

    def _search_files(self, target: Path, query: str) -> list[Path]:
        needle = query.casefold()
        matches: list[Path] = []
        for item in self._walk_files(target, self.config.search_depth):
            if needle in item.name.casefold():
                matches.append(item)
            elif item.is_file() and self._is_readable_text(item) and self._file_contains(item, needle):
                matches.append(item)
            if len(matches) >= self.config.search_limit:
                break
        return matches

    def _file_contains(self, path: Path, needle: str) -> bool:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return needle in text.casefold()

    def _targets_from_argument(self, chat_id: str, argument: str) -> list[Path]:
        cleaned = argument.strip().strip('"').strip("'")
        choices = self.file_choices.get(chat_id, [])
        if not cleaned:
            return choices[:1]
        if cleaned.casefold() in {"it", "this", "that", "file"}:
            return choices[:1]
        if cleaned.casefold() in {"all", "everything"}:
            return choices
        number = _first_number(cleaned)
        if number is not None and choices:
            index = number - 1
            if 0 <= index < len(choices):
                return [choices[index]]
        for choice in choices:
            if cleaned.casefold() in choice.name.casefold():
                return [choice]
            cleaned_words = set(_words(cleaned))
            if cleaned_words and cleaned_words.issubset(set(_words(choice.name))):
                return [choice]
        target = self._resolve_path_or_name(cleaned, choices)
        if not target.exists():
            raise FileNotFoundError(target)
        return [target]

    def _remember_choices(self, chat_id: str, choices: list[Path]) -> None:
        self.file_choices[chat_id] = choices

    def _sort_entries(self, entries: list[Path]) -> list[Path]:
        return sorted(entries, key=lambda item: (item.is_file(), item.name.casefold()))

    def _file_line(self, index: int, item: Path, root: Path) -> str:
        kind = "D" if item.is_dir() else "F"
        label = item.name if not _is_relative_to(item, root) else str(item.relative_to(root))
        if item.is_dir():
            return f"{index}. [{kind}] {label}"
        size = _human_size(item.stat().st_size) if item.exists() else "unknown size"
        return f"{index}. [{kind}] {label} - {size}"

    def _zip_folder(self, folder: Path) -> Path:
        self.config.export_root.mkdir(parents=True, exist_ok=True)
        archive_name = _safe_filename(folder.name or "folder") + "-" + str(int(time.time())) + ".zip"
        archive_path = _unique_path(self.config.export_root / archive_name)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in self._walk_folder_for_zip(folder):
                if item.is_file():
                    archive.write(item, item.relative_to(folder))
        return archive_path

    def _walk_folder_for_zip(self, folder: Path) -> list[Path]:
        results: list[Path] = []
        pending = [folder]
        while pending:
            current = pending.pop(0)
            for item in self._safe_children(current):
                if item.is_dir() and item.name not in SKIPPED_DIRECTORIES:
                    pending.append(item)
                elif item.is_file():
                    results.append(item)
        return results

    def _check_send_size(self, path: Path) -> None:
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > self.config.max_send_mb:
            raise RuntimeError(f"{path.name} is {size_mb:.1f} MB, above TELEGRAM_MAX_SEND_MB={self.config.max_send_mb:.1f}.")

    def _attachment_from_message(self, message: dict[str, Any]) -> TelegramAttachment | None:
        for kind in ("voice", "audio", "document", "video_note", "video"):
            payload = message.get(kind)
            if isinstance(payload, dict) and payload.get("file_id"):
                return _attachment_from_payload(kind, payload)
        photos = message.get("photo")
        if isinstance(photos, list) and photos:
            photo = photos[-1]
            if isinstance(photo, dict) and photo.get("file_id"):
                return _attachment_from_payload("photo", photo)
        return None

    def _is_transcribable_attachment(self, attachment: TelegramAttachment, path: Path) -> bool:
        if attachment.kind in {"voice", "audio", "video_note"}:
            return True
        if attachment.mime_type.startswith("audio/") or attachment.mime_type.startswith("video/"):
            return True
        return path.suffix.lower() in FILE_TYPE_GROUPS["audio"] or path.suffix.lower() in FILE_TYPE_GROUPS["video"]

    def _transcript_text(self, transcript: AudioTranscript) -> str:
        language = transcript.language or "auto"
        confidence = f"{transcript.language_probability:.2f}" if transcript.language_probability else "unknown"
        return "\n".join(
            [
                f"Transcript ({language}, confidence {confidence}, {transcript.duration_seconds:.1f}s):",
                transcript.text,
            ]
        )

    def _is_readable_text(self, path: Path) -> bool:
        if path.suffix.lower() in TEXT_EXTENSIONS:
            return True
        try:
            sample = path.read_bytes()[:2048]
        except OSError:
            return False
        if b"\x00" in sample:
            return False
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True

    def _looks_like_soft_ack(self, text: str) -> bool:
        words = _words(text)
        if not words:
            return False
        if len(words) <= 4 and "thank" in words:
            return True
        if len(words) <= 4 and "thanks" in words:
            return True
        if len(words) <= 5 and "thnx" in words:
            return True
        if len(words) <= 4 and {"ok", "okay"} & set(words) and {"thanks", "thank", "thnx"} & set(words):
            return True
        return False

    def _soft_ack_text(self, text: str) -> str:
        if "nah" in set(_words(text)) or "no" in set(_words(text)):
            return "No problem."
        return "Anytime."

    def _looks_like_read_request(self, text: str) -> bool:
        words = _words(text)
        if not words:
            return False
        return ("read" in words or "preview" in words or "content" in words) and (
            "it" in words
            or "this" in words
            or "that" in words
            or "file" in words
            or "content" in words
            or _first_number(text) is not None
        )

    def _looks_like_info_request(self, text: str) -> bool:
        words = _words(text)
        return ("info" in words or "details" in words or "size" in words or "metadata" in words) and (
            "file" in words or "folder" in words or "it" in words or "this" in words or _first_number(text) is not None
        )

    def _looks_like_list_request(self, text: str) -> bool:
        words = _words(text)
        return ("list" in words or "show" in words or "browse" in words) and (
            "files" in words or "file" in words or "folder" in words or "folders" in words
        )

    def _looks_like_recent_request(self, text: str) -> bool:
        words = _words(text)
        return "recent" in words and ("files" in words or "file" in words)

    def _looks_like_search_request(self, text: str) -> bool:
        words = _words(text)
        return ("search" in words or "find" in words) and ("file" in words or "files" in words)

    def _looks_like_send_request(self, text: str) -> bool:
        words = _words(text)
        if "send" not in words and "upload" not in words:
            return False
        if {"email", "mail", "gmail", "message", "sms"} & set(words):
            return False
        if bool({"file", "files", "folder", "document", "photo", "image", "it", "this", "that"} & set(words)):
            return True
        if _first_number(text) is not None:
            return True
        if self._known_file_suffix_in_text(text):
            return True
        return len(words) > 1 and words[0] in {"send", "upload"}

    def _path_hint_from_text(self, text: str) -> str:
        lowered = text.casefold()
        for marker in (" in ", " under ", " from ", " inside "):
            index = lowered.rfind(marker)
            if index >= 0:
                tail = text[index + len(marker) :].strip().strip(" .,:;!?\"'")
                if tail:
                    path = Path(tail).expanduser().resolve(strict=False)
                    if path.exists():
                        return tail
        words = set(_words(text))
        for alias in sorted(KNOWN_FOLDER_ALIASES, key=len, reverse=True):
            alias_words = set(_words(alias))
            if alias_words and alias_words.issubset(words):
                return alias
        return ""

    def _search_argument_from_text(self, text: str) -> str:
        lowered = text.casefold()
        for marker in ("search", "find"):
            index = lowered.find(marker)
            if index >= 0:
                return text[index + len(marker) :].strip()
        return text

    def _send_argument_from_text(self, text: str) -> str:
        number = _first_number(text)
        if number is not None:
            return str(number)
        words = _words(text)
        if "it" in words or "this" in words or "that" in words:
            return "it"
        lowered = text.casefold()
        marker_index = lowered.find("send")
        marker_length = len("send")
        if marker_index < 0:
            marker_index = lowered.find("upload")
            marker_length = len("upload")
        if marker_index < 0:
            return ""
        tail = text[marker_index + marker_length :].strip()
        folder_hint = self._path_hint_from_text(tail)
        if folder_hint and ("from" in words or "in" in words) and not self._known_file_suffix_in_text(tail):
            return folder_hint
        filler = {"me", "the", "a", "an", "file", "files", "folder", "document", "over", "telegram", "please", "pls", "to", "from", "in"}
        kept = [word for word in tail.split() if word.casefold().strip(".,;:!?") not in filler]
        return " ".join(kept).strip()

    def _reference_argument_from_text(self, text: str) -> str:
        number = _first_number(text)
        if number is not None:
            return str(number)
        words = _words(text)
        if "it" in words or "this" in words or "that" in words:
            return "it"
        for choice in self.file_choices.values():
            for path in choice:
                if path.name.casefold() in text.casefold():
                    return path.name
        suffix = self._known_file_suffix_in_text(text)
        if suffix:
            return suffix
        return ""

    def _resolve_path_or_name(self, cleaned: str, choices: list[Path]) -> Path:
        target = ensure_allowed_path(cleaned)
        if target.exists():
            return target

        alias_path = self._path_from_known_alias(cleaned)
        if alias_path is not None and alias_path.exists():
            return alias_path

        search_roots = []
        for choice in choices:
            search_roots.append(choice.parent if choice.is_file() else choice)
        search_roots.extend(resolve_local_path(alias) for alias in KNOWN_FOLDER_ALIASES)
        seen: set[str] = set()
        for root in search_roots:
            key = str(root).casefold()
            if key in seen or not root.exists():
                continue
            seen.add(key)
            match = self._first_name_match(root, cleaned)
            if match is not None:
                return match
        return target

    def _first_name_match(self, root: Path, text: str) -> Path | None:
        needle = text.casefold()
        needle_words = set(_words(text))
        for item in self._walk_files(root, self.config.search_depth):
            if needle in item.name.casefold():
                return item
            if needle_words and needle_words.issubset(set(_words(item.name))):
                return item
        return None

    def _path_from_known_alias(self, text: str) -> Path | None:
        hint = self._path_hint_from_text(text)
        if not hint:
            return None
        text_words = set(_words(text))
        hint_words = set(_words(hint))
        filler = {"file", "files", "folder", "folders", "directory", "directories"}
        if text_words - filler != hint_words:
            return None
        return resolve_local_path(hint)

    def _known_file_suffix_in_text(self, text: str) -> str:
        lowered = text.casefold()
        for extensions in FILE_TYPE_GROUPS.values():
            for extension in extensions:
                index = lowered.find(extension)
                if index > 0:
                    start = index
                    while start > 0 and not text[start - 1].isspace():
                        start -= 1
                    end = index + len(extension)
                    while end < len(text) and not text[end].isspace():
                        end += 1
                    return text[start:end].strip(" .,:;!?\"'")
        return ""

    def _send_artifacts_from_reply(self, chat_id: str, user_text: str, reply: str) -> None:
        if not self._looks_like_artifact_request(user_text):
            return
        paths = self._existing_paths_from_text(reply)
        if not paths:
            return
        self._remember_choices(chat_id, paths)
        for path in paths[: self.config.max_batch_send]:
            try:
                if path.suffix.lower() in FILE_TYPE_GROUPS["image"]:
                    self.send_photo(chat_id, path, path.name)
                else:
                    self.send_document(chat_id, path, path.name)
            except Exception as error:
                self.send_message(chat_id, f"Generated {path.name}, but Telegram upload failed: {error}")

    def _looks_like_artifact_request(self, text: str) -> bool:
        words = set(_words(text))
        return bool({"generate", "create", "make", "draw", "image", "picture", "photo", "file"} & words)

    def _existing_paths_from_text(self, text: str) -> list[Path]:
        paths: list[Path] = []
        for raw_line in text.splitlines():
            line = raw_line.strip().lstrip("-").strip()
            if line.casefold().startswith("path:"):
                line = line.split(":", 1)[1].strip()
            candidates = [line]
            if " - " in line:
                candidates.extend(part.strip() for part in line.split(" - "))
            for candidate in candidates:
                cleaned = candidate.strip().strip("`").strip('"').strip("'")
                if not cleaned:
                    continue
                path = Path(cleaned).expanduser().resolve(strict=False)
                if path.exists() and path.is_file() and path not in paths:
                    paths.append(path)
        return paths

    def _folder_label(self, path: Path) -> str:
        for alias, folder_name in KNOWN_FOLDER_ALIASES.items():
            alias_path = Path.home() if not folder_name else Path.home() / folder_name
            if path.resolve(strict=False) == alias_path.resolve(strict=False):
                return alias.title()
        return str(path)

    def _tool_names_text(self) -> str:
        specs = getattr(getattr(self.brain, "tools", None), "specs", None)
        if not callable(specs):
            return ""
        names = [str(spec.name).replace("_", " ") for spec in specs()]
        return ", ".join(names)

    def _split_search_argument(self, argument: str) -> tuple[str, str]:
        text = argument.strip()
        if not text:
            return "", ""
        lowered = text.casefold()
        marker = " in "
        index = lowered.rfind(marker)
        if index < 0:
            return _clean_search_query(text), self._path_hint_from_text(text)
        return _clean_search_query(text[:index]), text[index + len(marker) :].strip()


def split_message(text: str) -> list[str]:
    if len(text) <= MAX_TELEGRAM_MESSAGE:
        return [text]
    chunks = []
    remaining = text
    while remaining:
        chunks.append(remaining[:MAX_TELEGRAM_MESSAGE])
        remaining = remaining[MAX_TELEGRAM_MESSAGE:]
    return chunks


def main() -> None:
    project_root = Path(__file__).resolve().parent
    load_env(project_root / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env before running telegram_bot.py")
    allowed_chat_id = os.getenv("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
    brain = Brain.create(project_root)
    bot = TelegramBot(brain, token, allowed_chat_id, TelegramConfig.from_env(project_root))
    bot.run()


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip().lstrip("\ufeff"), value.strip().strip('"').strip("'"))

def encode_multipart_form_data(params: dict[str, Any], files: dict[str, Path]) -> tuple[bytes, str]:
    boundary = "----jarvis-telegram-" + uuid.uuid4().hex
    body = bytearray()
    for key, value in params.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    for field, path in files.items():
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="{field}"; '
                f'filename="{path.name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        body.extend(path.read_bytes())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _slash_command(text: str) -> tuple[str, str]:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return "", ""
    parts = stripped.split(maxsplit=1)
    command = parts[0].casefold()
    argument = parts[1] if len(parts) > 1 else ""
    return command, argument


def _attachment_from_payload(kind: str, payload: dict[str, Any]) -> TelegramAttachment:
    file_id = str(payload.get("file_id") or "")
    unique_id = str(payload.get("file_unique_id") or file_id)
    mime_type = str(payload.get("mime_type") or "")
    file_name = str(payload.get("file_name") or "").strip()
    if not file_name:
        extension = mimetypes.guess_extension(mime_type) or _default_extension(kind)
        file_name = unique_id + extension
    return TelegramAttachment(
        file_id=file_id,
        unique_id=unique_id,
        file_name=file_name,
        kind=kind,
        mime_type=mime_type,
        file_size=int(payload.get("file_size") or 0),
    )


def _default_extension(kind: str) -> str:
    if kind == "photo":
        return ".jpg"
    if kind in {"video", "video_note"}:
        return ".mp4"
    if kind == "voice":
        return ".ogg"
    return ".bin"


def _safe_filename(value: str) -> str:
    cleaned = []
    for char in value:
        if char.isalnum() or char in {" ", ".", "-", "_"}:
            cleaned.append(char)
        else:
            cleaned.append("_")
    name = "".join(cleaned).strip().strip(".")
    return name or "file"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "bytes":
                return f"{int(value)} bytes"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} bytes"


def _folder_size(folder: Path) -> int:
    total = 0
    for item in folder.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _words(text: str) -> list[str]:
    words: list[str] = []
    current: list[str] = []
    for char in text.casefold():
        if char.isalnum():
            current.append(char)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return words


def _first_number(text: str) -> int | None:
    for word in _words(text):
        if word.isdigit():
            return int(word)
    ordinals = {
        "first": 1,
        "second": 2,
        "third": 3,
        "fourth": 4,
        "fifth": 5,
    }
    for word in _words(text):
        if word in ordinals:
            return ordinals[word]
    return None


def _clean_search_query(text: str) -> str:
    words = [word for word in text.strip().split() if word.casefold() not in {"file", "files", "folder", "folders"}]
    return " ".join(words).strip()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    if not value:
        return default.resolve(strict=False)
    return Path(value).expanduser().resolve(strict=False)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    main()
