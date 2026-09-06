import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.models import Message


class Conversation:
    def __init__(self, model: str, system: str = ""):
        self.model = model
        self.system = system.strip()
        self.messages: list[Message] = []
        self.created_at = datetime.now(timezone.utc).isoformat()
        if self.system:
            self.messages.append(Message(role="system", content=self.system))

    def add_user(self, text: str) -> None:
        cleaned = text.strip()
        if cleaned:
            self.messages.append(Message(role="user", content=cleaned))

    def add_assistant(self, text: str) -> None:
        self.messages.append(Message(role="assistant", content=text))

    def clear(self, keep_system: bool = True) -> None:
        system_msg = self.system if keep_system else ""
        self.messages = []
        if keep_system and system_msg:
            self.messages.append(Message(role="system", content=system_msg))

    def set_system(self, text: str) -> None:
        self.system = text.strip()
        self.messages = [m for m in self.messages if m.role != "system"]
        if self.system:
            self.messages.insert(0, Message(role="system", content=self.system))

    def history(self) -> list[Message]:
        return list(self.messages)

    def estimate_tokens(self) -> int:
        total = 0
        for m in self.messages:
            total += max(1, len(m.content) // 4)
        return total

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "system": self.system,
            "created_at": self.created_at,
            "messages": [m.to_dict() for m in self.messages],
        }

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def load(path: Path) -> "Conversation":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        conv = Conversation(model=str(data.get("model", "")), system=str(data.get("system", "") or ""))
        conv.created_at = str(data.get("created_at", conv.created_at))
        conv.messages = [Message.from_dict(m) for m in data.get("messages", []) if isinstance(m, dict)]
        return conv

    @staticmethod
    def default_filename(directory: Path, prefix: str = "chat") -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{prefix}-{stamp}.json"


def load_conversation_or_new(path: Optional[str], model: str, system: str, sessions_dir: Path) -> Conversation:
    if path:
        return Conversation.load(Path(path))
    return Conversation(model=model, system=system)
