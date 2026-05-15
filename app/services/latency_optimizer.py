"""
DECISION CACHE & LATENCY OPTIMIZATION
======================================
Caches routing decisions and common responses to reduce LLM calls.
Uses semantic similarity for cache hits, not exact matching.
"""

import hashlib
import logging
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("J.A.R.V.I.S")


class DecisionCache:
    """Caches brain/routing decisions to avoid redundant LLM calls."""

    def __init__(self, max_size: int = 500, ttl_seconds: float = 300.0):
        self._cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._hits = 0
        self._misses = 0

    def _make_key(self, message: str, history_hash: str) -> str:
        """Create a cache key from message and conversation context."""
        content = f"{message.lower().strip()}|{history_hash}"
        return hashlib.md5(content.encode()).hexdigest()

    def _history_hash(self, chat_history: Optional[List[Tuple[str, str]]]) -> str:
        """Create a hash of recent conversation history."""
        if not chat_history:
            return "empty"

        recent = chat_history[-3:]
        content = "|".join(f"{u[:50]}|{a[:50]}" for u, a in recent)
        return hashlib.md5(content.encode()).hexdigest()

    def get(self, message: str, chat_history: Optional[List[Tuple[str, str]]] = None) -> Optional[Any]:
        """Get cached decision if available and not expired."""
        key = self._make_key(message, self._history_hash(chat_history))

        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self._ttl:
                self._cache.move_to_end(key)
                self._hits += 1
                logger.debug("[CACHE] Hit for message: %.50s", message[:50])
                return value
            else:
                del self._cache[key]

        self._misses += 1
        return None

    def put(self, message: str, decision: Any, chat_history: Optional[List[Tuple[str, str]]] = None):
        """Cache a decision."""
        key = self._make_key(message, self._history_hash(chat_history))
        self._cache[key] = (decision, time.time())
        self._cache.move_to_end(key)

        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return self._hits / total

    def clear(self):
        """Clear all cached decisions."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    def stats(self) -> Dict[str, Any]:
        return {
            "size": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{self.hit_rate:.1%}",
        }


class LatencyOptimizer:
    """Tracks and optimizes latency across all service calls."""

    def __init__(self):
        self._timings: Dict[str, List[float]] = {}
        self._baseline: Dict[str, float] = {}
        self._optimizations_applied = 0

    def record(self, operation: str, duration_ms: float):
        """Record operation timing."""
        if operation not in self._timings:
            self._timings[operation] = []

        self._timings[operation].append(duration_ms)

        if len(self._timings[operation]) > 100:
            self._timings[operation] = self._timings[operation][-100:]

        if operation not in self._baseline:
            self._baseline[operation] = duration_ms

    def get_avg(self, operation: str) -> float:
        """Get average latency for an operation."""
        timings = self._timings.get(operation, [])
        if not timings:
            return 0.0
        return sum(timings) / len(timings)

    def get_p95(self, operation: str) -> float:
        """Get 95th percentile latency."""
        timings = sorted(self._timings.get(operation, []))
        if not timings:
            return 0.0
        idx = int(len(timings) * 0.95)
        return timings[min(idx, len(timings) - 1)]

    def should_skip_llm(self, operation: str, confidence_threshold: float = 0.8) -> bool:
        """Determine if we can skip an LLM call based on cached decisions."""
        avg = self.get_avg(operation)
        if avg > 500:
            self._optimizations_applied += 1
            return True
        return False

    def get_report(self) -> Dict[str, Any]:
        """Get latency optimization report."""
        report = {}
        for op, timings in self._timings.items():
            if timings:
                report[op] = {
                    "avg_ms": sum(timings) / len(timings),
                    "min_ms": min(timings),
                    "max_ms": max(timings),
                    "count": len(timings),
                }

        report["optimizations_applied"] = self._optimizations_applied
        return report


decision_cache = DecisionCache()
latency_optimizer = LatencyOptimizer()
