from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from core.llm_service import LLMConfig, NvidiaLLMService
from daemon.config import DaemonConfig


class DaemonLLM:
    def __init__(self, config: DaemonConfig) -> None:
        self.config = config
        base = LLMConfig.from_env(config.project_root)
        self.services = {
            "default": NvidiaLLMService(replace(base, model=config.default_model)),
            "review": NvidiaLLMService(replace(base, model=config.review_model)),
            "code_review": NvidiaLLMService(replace(base, model=config.code_review_model)),
            "writing": NvidiaLLMService(replace(base, model=config.writing_model)),
            "summary": NvidiaLLMService(replace(base, model=config.summary_model)),
        }

    @classmethod
    def from_root(cls, project_root: Path) -> "DaemonLLM":
        return cls(DaemonConfig.from_root(project_root))

    def chat(self, role: str, system: str, user: str) -> str:
        service = self.services.get(role, self.services["default"])
        return service.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
