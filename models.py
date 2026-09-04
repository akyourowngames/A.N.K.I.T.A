from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class Message:
    role: str
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}

    @staticmethod
    def from_dict(data: dict) -> "Message":
        return Message(role=str(data.get("role", "user")), content=str(data.get("content", "")))


@dataclass
class ModelInfo:
    id: str
    name: str = ""
    context_length: int = 0
    is_free: bool = False
    description: str = ""
    owned_by: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "ModelInfo":
        model_id = str(data.get("id", ""))
        name = str(data.get("name", "") or model_id)
        ctx = data.get("context_length", 0) or 0
        try:
            ctx = int(ctx)
        except Exception:
            ctx = 0
        is_free = bool(data.get("isFree", False))
        pricing = data.get("pricing", {}) or {}
        try:
            prompt_price = float(str(pricing.get("prompt", "1")))
            completion_price = float(str(pricing.get("completion", "1")))
            if prompt_price == 0 and completion_price == 0:
                is_free = True
        except Exception:
            pass
        if model_id.endswith(":free") or model_id in ("kilo-auto/free", "openrouter/free"):
            is_free = True
        owned = str(data.get("owned_by", "") or "")
        if not owned and "/" in model_id:
            owned = model_id.split("/")[0]
        return ModelInfo(
            id=model_id,
            name=name,
            context_length=ctx,
            is_free=is_free,
            description=str(data.get("description", "") or ""),
            owned_by=owned,
        )


@dataclass
class ChatUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @staticmethod
    def from_dict(data: Optional[dict]) -> "ChatUsage":
        if not data:
            return ChatUsage()
        return ChatUsage(
            prompt_tokens=int(data.get("prompt_tokens", 0) or 0),
            completion_tokens=int(data.get("completion_tokens", 0) or 0),
            total_tokens=int(data.get("total_tokens", 0) or 0),
        )


@dataclass
class ChatResult:
    content: str
    model: str = ""
    usage: ChatUsage = field(default_factory=ChatUsage)
    raw: Any = None
