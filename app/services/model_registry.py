"""
NVIDIA MODEL REGISTRY
=====================
Supports all NVIDIA NIM models with automatic selection based on task type.
Models are categorized by capability: fast, chat, vision, code, embedding.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("J.A.R.V.I.S")


class ModelTier(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    POWERFUL = "powerful"
    SPECIALIZED = "specialized"


class ModelCapability(str, Enum):
    CHAT = "chat"
    CODE = "code"
    VISION = "vision"
    EMBEDDING = "embedding"
    RERANK = "rerank"


@dataclass
class ModelInfo:
    model_id: str
    tier: ModelTier
    capabilities: List[ModelCapability]
    max_tokens: int = 4096
    default_temperature: float = 0.4
    avg_latency_ms: float = 0.0
    success_count: int = 0
    failure_count: int = 0
    last_used: float = 0.0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0
        return self.success_count / total

    @property
    def reliability_score(self) -> float:
        return self.success_rate * 0.6 + (1.0 / (1.0 + self.avg_latency_ms / 1000.0)) * 0.4


NVIDIA_MODEL_REGISTRY: Dict[str, ModelInfo] = {
    "FAST MODELS": ModelInfo(
        model_id="meta/llama-3.1-8b-instruct",
        tier=ModelTier.FAST,
        capabilities=[ModelCapability.CHAT],
        max_tokens=2048,
        default_temperature=0.3,
    ),
    "BALANCED MODELS": ModelInfo(
        model_id="meta/llama-3.1-70b-instruct",
        tier=ModelTier.BALANCED,
        capabilities=[ModelCapability.CHAT],
        max_tokens=4096,
        default_temperature=0.4,
    ),
    "POWERFUL MODELS": ModelInfo(
        model_id="meta/llama-3.1-405b-instruct",
        tier=ModelTier.POWERFUL,
        capabilities=[ModelCapability.CHAT],
        max_tokens=8192,
        default_temperature=0.5,
    ),
    "CODE MODELS": ModelInfo(
        model_id="meta/codellama-70b-instruct",
        tier=ModelTier.BALANCED,
        capabilities=[ModelCapability.CHAT, ModelCapability.CODE],
        max_tokens=4096,
        default_temperature=0.2,
    ),
    "VISION MODELS": ModelInfo(
        model_id="nvidia/llama-3.1-nemotron-nano-vl-8b-v1",
        tier=ModelTier.SPECIALIZED,
        capabilities=[ModelCapability.VISION, ModelCapability.CHAT],
        max_tokens=2048,
        default_temperature=0.3,
    ),
}


ALL_NVIDIA_CHAT_MODELS = {
    "meta/llama-3.1-8b-instruct": {"tier": "fast", "latency_ms": 200},
    "meta/llama-3.1-70b-instruct": {"tier": "balanced", "latency_ms": 500},
    "meta/llama-3.1-405b-instruct": {"tier": "powerful", "latency_ms": 1500},
    "meta/llama-3.3-70b-versatile": {"tier": "balanced", "latency_ms": 600},
    "mistralai/mistral-large-2": {"tier": "powerful", "latency_ms": 800},
    "mistralai/mixtral-8x22b-instruct-v0.1": {"tier": "balanced", "latency_ms": 400},
    "google/gemma-2-27b-it": {"tier": "balanced", "latency_ms": 350},
    "google/gemma-2-9b-it": {"tier": "fast", "latency_ms": 200},
    "microsoft/phi-3-medium-128k-instruct": {"tier": "fast", "latency_ms": 250},
    "microsoft/phi-3-mini-128k-instruct": {"tier": "fast", "latency_ms": 150},
    "nvidia/nemotron-4-340b-instruct": {"tier": "powerful", "latency_ms": 1200},
    "nvidia/nemotron-3-nano-30b-a3b": {"tier": "balanced", "latency_ms": 400},
    "deepseek-ai/deepseek-r1": {"tier": "powerful", "latency_ms": 2000},
    "qwen/qwen2.5-coder-32b-instruct": {"tier": "balanced", "latency_ms": 500},
    "qwen/qwq-32b": {"tier": "powerful", "latency_ms": 1000},
    "baichuan-inc/baichuan2-13b-chat": {"tier": "fast", "latency_ms": 300},
    "thudm/chatglm3-6b": {"tier": "fast", "latency_ms": 250},
    "writer/palmyra-med-70b-32k": {"tier": "balanced", "latency_ms": 600},
    "writer/palmyra-fin-70b-32k": {"tier": "balanced", "latency_ms": 600},
    "snowflake/arctic": {"tier": "balanced", "latency_ms": 500},
}


class ModelSelector:
    """Automatically selects the best model based on task type and performance history."""

    def __init__(self):
        self._model_stats: Dict[str, Dict] = {}
        self._fallback_order = [
            "meta/llama-3.1-8b-instruct",
            "google/gemma-2-9b-it",
            "microsoft/phi-3-mini-128k-instruct",
        ]

    def select_for_task(self, task_type: str, prefer_fast: bool = False) -> str:
        """Select the best model for a given task type."""
        task_lower = task_type.lower()

        if prefer_fast:
            return self._select_fast_model()

        if any(x in task_lower for x in ["code", "program", "script", "function"]):
            return "qwen/qwen2.5-coder-32b-instruct"

        if any(x in task_lower for x in ["vision", "image", "describe", "see"]):
            return "nvidia/llama-3.1-nemotron-nano-vl-8b-v1"

        if any(x in task_lower for x in ["write", "essay", "content", "creative"]):
            return "meta/llama-3.1-70b-instruct"

        if any(x in task_lower for x in ["route", "classify", "brain", "decision"]):
            return self._select_fast_model()

        return "meta/llama-3.1-70b-instruct"

    def _select_fast_model(self) -> str:
        """Select the fastest available model based on recent performance."""
        best_model = self._fallback_order[0]
        best_score = float('inf')

        for model_id in self._fallback_order:
            stats = self._model_stats.get(model_id, {})
            latency = stats.get("avg_latency_ms", 300)
            success_rate = stats.get("success_rate", 1.0)

            score = latency / (success_rate + 0.1)
            if score < best_score:
                best_score = score
                best_model = model_id

        return best_model

    def record_latency(self, model_id: str, latency_ms: float, success: bool = True):
        """Record model performance for future selection."""
        if model_id not in self._model_stats:
            self._model_stats[model_id] = {
                "total_latency_ms": 0.0,
                "count": 0,
                "successes": 0,
                "failures": 0,
            }

        stats = self._model_stats[model_id]
        stats["total_latency_ms"] += latency_ms
        stats["count"] += 1

        if success:
            stats["successes"] += 1
        else:
            stats["failures"] += 1

    def get_model_info(self, model_id: str) -> dict:
        """Get model configuration and performance stats."""
        base_info = ALL_NVIDIA_CHAT_MODELS.get(model_id, {"tier": "balanced", "latency_ms": 500})
        stats = self._model_stats.get(model_id, {})

        return {
            **base_info,
            "avg_latency_ms": stats.get("total_latency_ms", 0) / max(stats.get("count", 1), 1),
            "success_rate": stats.get("successes", 0) / max(stats.get("count", 1), 1),
            "total_calls": stats.get("count", 0),
        }

    def list_available_models(self) -> List[str]:
        """List all available NVIDIA models."""
        return list(ALL_NVIDIA_CHAT_MODELS.keys())


model_selector = ModelSelector()
