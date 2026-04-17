"""Multi-agent orchestration package for A.N.K.I.T.A."""

from .orchestrator import Orchestrator as LegacyOrchestrator

try:
    from .orchestration import Orchestrator
except Exception:
    Orchestrator = LegacyOrchestrator
from .supervisor import SupervisorAgent
from .specialists import (
    FileAgent,
    WebAgent,
    SystemAgent,
    MusicAgent,
    CodeAgent,
    CodeWriterAgent,
    GeneralAgent,
)

__all__ = [
    "Orchestrator",
    "LegacyOrchestrator",
    "SupervisorAgent",
    "FileAgent",
    "WebAgent",
    "SystemAgent",
    "MusicAgent",
    "CodeAgent",
    "CodeWriterAgent",
    "GeneralAgent",
]
