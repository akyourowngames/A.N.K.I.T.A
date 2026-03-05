"""
PersonalityEngine — Dynamic emotion detection + adaptive personality for A.N.K.I.T.A.

Philosophy:
  - FRIDAY-style: warm, sharp, trusted ally — adapts tone/length/humor to how the user feels.
  - Emotion is detected two ways:
      1. Instant rule-based pre-check (synchronous, same-turn): catches explicit cues and
         strong signals (ALL_CAPS, "I'm stressed", etc.) with zero latency.
      2. LLM classification (Groq llama-3.1-8b-instant, in background thread): richer
         nuance that rules can't catch. Updates mood state for the *next* turn.
  - Session-level accumulation via EMA (exponential moving average) — mood deepens over
    several turns, then decays naturally back to neutral.
  - `get_personality_directive()` returns a short, clean system message block injected
    into every LLM call so ANKITA's tone shifts automatically.

Usage:
    from tools.personality_engine import get_mood_tracker

    tracker = get_mood_tracker()
    tracker.update(user_text, runtime=llm_runtime)   # call each turn
    directive = tracker.get_personality_directive()   # inject into messages
"""
from __future__ import annotations

import json
import re
import threading
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Emotion enum — 8 moods + neutral
# ─────────────────────────────────────────────────────────────────────────────
EMOTIONS = frozenset({
    "stressed", "frustrated", "excited", "sad", "tired",
    "curious", "urgent", "casual", "neutral",
})

# ─────────────────────────────────────────────────────────────────────────────
# Rule-based keyword maps for instant pre-check
# ─────────────────────────────────────────────────────────────────────────────
_KEYWORD_MAP: dict[str, list[str]] = {
    "stressed":   ["stressed", "stress", "overwhelmed", "anxious", "anxiety", "panic", "too much",
                   "burning out", "burned out", "cant cope", "can't cope", "drowning"],
    "frustrated": ["frustrated", "frustrating", "annoying", "annoyed", "ridiculous", "stupid",
                   "broken", "not working", "doesn't work", "won't work", "useless", "hate this",
                   "what the hell", "wtf", "ugh", "argh"],
    "excited":    ["excited", "amazing", "awesome", "incredible", "can't wait", "hyped",
                   "let's go", "lets go", "yess", "woohoo", "finally", "just finished",
                   "it works", "working now", "nailed it"],
    "sad":        ["sad", "upset", "heartbroken", "depressed", "lonely", "miss", "crying",
                   "feel bad", "feeling bad", "not okay", "not ok", "down today"],
    "tired":      ["tired", "exhausted", "sleepy", "drained", "worn out", "fatigue",
                   "no energy", "low energy", "need sleep", "haven't slept"],
    "curious":    ["curious", "wondering", "how does", "how do", "why does", "why do",
                   "can you explain", "what is", "what's", "tell me about", "understand",
                   "interested in", "want to know", "how would"],
    "urgent":     ["urgent", "asap", "right now", "immediately", "emergency", "quick",
                   "quickly", "fast", "hurry", "time sensitive", "need this now"],
    "casual":     ["hey", "yo", "lol", "haha", "btw", "ngl", "tbh", "just wondering",
                   "just curious", "no rush", "whenever", "chillin", "chill"],
}

# Explicit first-person cue patterns — "I'm stressed", "I feel tired", etc.
_EXPLICIT_PATTERNS = [
    re.compile(
        r"\bi\s*(?:am|'m|feel|felt|was)\s+(" + "|".join(sum(_KEYWORD_MAP.values(), [])) + r")\b",
        re.I,
    ),
    re.compile(
        r"\bi\s*(?:am|'m)\s+(?:so|really|very|extremely)\s+(" + "|".join(sum(_KEYWORD_MAP.values(), [])) + r")\b",
        re.I,
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class EmotionResult:
    emotion: str        # one of EMOTIONS
    intensity: float    # 0.0–1.0
    explicit: bool      # True if user directly stated emotion ("I'm stressed")
    source: str         # "rules" | "llm" | "fallback"


@dataclass
class MoodState:
    primary: str = "neutral"
    intensity: float = 0.0
    consecutive_count: int = 0
    explicit: bool = False
    history: List[str] = field(default_factory=list)  # last 5 emotions


# ─────────────────────────────────────────────────────────────────────────────
# Personality directives per mood
# ─────────────────────────────────────────────────────────────────────────────
_DIRECTIVES: dict[str, str] = {
    "stressed": (
        "[ANKITA-MOOD: stressed]\n"
        "The user is stressed. Adapt your response:\n"
        "• Calm, decisive tone — no sass, no jokes right now\n"
        "• Keep it brief and clear — reduce cognitive load\n"
        "• Lead with action: do the thing first, then explain\n"
        "• Acknowledge the pressure briefly before diving in (1 short sentence max)\n"
        "• If there's a quick win available, prioritise it"
    ),
    "frustrated": (
        "[ANKITA-MOOD: frustrated]\n"
        "The user is frustrated. Adapt your response:\n"
        "• Acknowledge the frustration first — don't skip past it\n"
        "• Zero sarcasm or snark; be genuinely helpful\n"
        "• Get to the fix fast — long explanations will irritate further\n"
        "• If ANKITA caused the issue, own it directly: 'That was my fault, here's the fix'\n"
        "• Be concrete: exact steps, not vague reassurance"
    ),
    "excited": (
        "[ANKITA-MOOD: excited]\n"
        "The user is excited/hyped. Match their energy:\n"
        "• Be enthusiastic and punchy — short sentences, forward momentum\n"
        "• Light humor and expressiveness are welcome here\n"
        "• Build on their excitement: amplify wins, celebrate progress\n"
        "• Keep it energetic but still sharp and useful"
    ),
    "sad": (
        "[ANKITA-MOOD: sad]\n"
        "The user seems sad or down. Be warmer and gentler:\n"
        "• Lead with warmth — acknowledge before tasking\n"
        "• Softer, more human tone than usual — less 'efficiency mode'\n"
        "• Don't project or overdramatise; just be present and helpful\n"
        "• If they need distraction (task to do), dive in supportively"
    ),
    "tired": (
        "[ANKITA-MOOD: tired]\n"
        "The user is tired or low energy. Adapt:\n"
        "• Keep it brief and clear — no dense paragraphs\n"
        "• Warm but efficient; don't make them work to parse your reply\n"
        "• If the task can wait, gently note that; if it can't, handle it smoothly\n"
        "• Skip unnecessary commentary — just get it done quietly"
    ),
    "curious": (
        "[ANKITA-MOOD: curious]\n"
        "The user is in learning/exploration mode. Engage thoughtfully:\n"
        "• Be more explanatory than usual — context is welcome here\n"
        "• Suggest related next steps or interesting angles they might not have considered\n"
        "• Slightly more conversational; match their inquisitive energy\n"
        "• Still stay focused — don't ramble, but depth is appreciated"
    ),
    "urgent": (
        "[ANKITA-MOOD: urgent]\n"
        "The user has an urgent request. Prioritise speed:\n"
        "• Action first, zero preamble — skip greetings and context\n"
        "• One-line acknowledgement max, then execute\n"
        "• Omit explanations unless they are critical to the action\n"
        "• If something can't be done instantly, say so in one sentence and offer the fastest alternative"
    ),
    "casual": (
        "[ANKITA-MOOD: casual]\n"
        "The user is in a relaxed, casual mood:\n"
        "• Drop the efficiency-mode intensity — be more conversational\n"
        "• Light humor and easy banter are welcome\n"
        "• No need to be terse; a slightly warmer and more relaxed tone works well\n"
        "• Still sharp and capable — just less formal about it"
    ),
    "neutral": "",  # No directive for neutral — base SYSTEM_PROMPT applies
}

_MOOD_MARKER = "[ANKITA-MOOD:"

# ─────────────────────────────────────────────────────────────────────────────
# EmotionAnalyzer
# ─────────────────────────────────────────────────────────────────────────────

class EmotionAnalyzer:
    """
    Stateless emotion detector.

    Two paths:
    1. Synchronous rule-based pre-check (instant) — explicit cues + strong signals
    2. LLM background classify (non-blocking) — richer nuance, updates next turn
    """

    def detect_rules(self, text: str) -> EmotionResult:
        """Instant synchronous rule check. Always returns something."""
        stripped = text.strip()

        # Multiple !! → excited (check BEFORE all_caps so "YES!!!" wins over frustrated)
        if stripped.count("!") >= 3:
            return EmotionResult("excited", 0.7, False, "rules")

        # Strong signals: ALL_CAPS message (>= 5 chars) → frustrated/urgent
        is_allcaps = (
            len(stripped) >= 5
            and stripped == stripped.upper()
            and any(c.isalpha() for c in stripped)
        )
        if is_allcaps:
            return EmotionResult("frustrated", 0.65, False, "rules")

        # Explicit first-person cue check
        for pat in _EXPLICIT_PATTERNS:
            m = pat.search(stripped)
            if m:
                word = m.group(1).lower()
                # Map keyword to emotion
                for emotion, keywords in _KEYWORD_MAP.items():
                    if word in keywords:
                        return EmotionResult(emotion, 0.8, True, "rules")

        # Keyword scan
        text_lower = stripped.lower()
        best_emotion = "neutral"
        best_count = 0
        for emotion, keywords in _KEYWORD_MAP.items():
            count = sum(1 for kw in keywords if kw in text_lower)
            if count > best_count:
                best_count = count
                best_emotion = emotion

        if best_count == 0:
            return EmotionResult("neutral", 0.0, False, "rules")

        intensity = min(0.3 + best_count * 0.15, 0.75)
        return EmotionResult(best_emotion, intensity, False, "rules")

    def detect_llm_async(
        self,
        text: str,
        runtime: Any,
        callback,  # callable(EmotionResult)
    ) -> None:
        """
        Non-blocking LLM emotion classification. Runs in a daemon thread.
        On completion calls callback(EmotionResult). On any error, silent no-op.
        """
        def _run():
            try:
                result = self._call_llm(text, runtime)
                if result:
                    callback(result)
            except Exception as e:
                logger.debug("[PersonalityEngine] LLM emotion classify failed: %s", e)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _call_llm(self, text: str, runtime: Any) -> Optional[EmotionResult]:
        """Make a tight LLM call to classify emotion. Returns None on failure."""
        try:
            # Import here to avoid circular dep at module load
            from llm.client import call_chat_once, LLMRuntime
            import os

            # Only use Groq for emotion classification — it's fast and cheap.
            # NEVER fall back to the main runtime (Copilot/Gemini) to avoid
            # competing with the main response pipeline.
            groq_key = os.getenv("GROQ_API_KEY", "").strip()
            # Reject obvious placeholder values
            if not groq_key or groq_key.lower() in {"your_groq_api_key", "placeholder", "none", ""}:
                return None  # No Groq key → use rules only, skip LLM

            from llm.client import GROQ_BASE_URL, DEFAULT_GROQ_MODEL
            classify_runtime = LLMRuntime(
                provider="groq",
                model=DEFAULT_GROQ_MODEL,
                api_key=groq_key,
                base_url=GROQ_BASE_URL,
                max_tokens=80,
            )

            system_msg = (
                "Classify the emotion in the user message.\n"
                'Return ONLY valid JSON: {"emotion": "<emotion>", "intensity": <0.0-1.0>, "explicit": <true|false>}\n'
                f"emotion must be one of: {', '.join(sorted(EMOTIONS))}\n"
                "intensity: 0.0 = barely detectable, 1.0 = very strong\n"
                "explicit: true only if the user directly states their emotion (e.g. 'I am stressed')\n"
                "Return neutral with intensity 0.0 for task-only messages."
            )

            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": text[:400]},  # cap input to keep cost low
            ]

            response = call_chat_once(classify_runtime, messages, tools=None, max_tokens=80)
            raw = (response.get("content") or "").strip()

            # Parse JSON — handle markdown fences
            raw = re.sub(r"```(?:json)?|```", "", raw).strip()
            data = json.loads(raw)

            emotion = str(data.get("emotion", "neutral")).lower()
            if emotion not in EMOTIONS:
                emotion = "neutral"
            intensity = float(data.get("intensity", 0.0))
            intensity = max(0.0, min(1.0, intensity))
            explicit = bool(data.get("explicit", False))

            return EmotionResult(emotion, intensity, explicit, "llm")

        except Exception as e:
            logger.debug("[PersonalityEngine] _call_llm parse failed: %s", e)
            return None


# ─────────────────────────────────────────────────────────────────────────────
# SessionMoodTracker
# ─────────────────────────────────────────────────────────────────────────────

class SessionMoodTracker:
    """
    Session-scoped mood accumulation via EMA.

    • α = 0.35 for inferred emotions (rule-based weak signal)
    • α = 0.60 for explicit emotions ("I'm tired") or LLM-confirmed
    • Auto-decays toward neutral after 10 consecutive neutral detections
    • `get_personality_directive()` returns system message block or "" for neutral
    """

    _ALPHA_INFERRED = 0.35
    _ALPHA_EXPLICIT  = 0.60
    _NEUTRAL_DECAY_THRESHOLD = 10  # consecutive neutrals before decay

    def __init__(self):
        self._state = MoodState()
        self._consecutive_neutral = 0
        self._lock = threading.RLock()
        self._analyzer = EmotionAnalyzer()

    def update(self, text: str, runtime: Any = None) -> MoodState:
        """
        Process a new user message.
        1. Instant rule pre-check → applies to current turn immediately.
        2. LLM async classify → updates state for *next* turn (non-blocking).
        Returns current MoodState after rule-based update.
        """
        # --- Instant rule check ---
        result = self._analyzer.detect_rules(text)
        self._apply_result(result)

        # --- LLM async check (updates next turn) ---
        if runtime is not None:
            self._analyzer.detect_llm_async(text, runtime, self._on_llm_result)

        return self.current_state()

    def _on_llm_result(self, result: EmotionResult) -> None:
        """Callback from background LLM thread."""
        with self._lock:
            # LLM result has higher trust — apply at full alpha
            # but only if LLM detected something non-neutral
            if result.emotion != "neutral" or result.intensity > 0.1:
                self._apply_result(result)
                logger.debug(
                    "[PersonalityEngine] LLM updated mood: %s (%.2f) [%s]",
                    result.emotion, result.intensity, result.source,
                )

    def _apply_result(self, result: EmotionResult) -> None:
        with self._lock:
            alpha = self._ALPHA_EXPLICIT if (result.explicit or result.source == "llm") else self._ALPHA_INFERRED
            cur = self._state

            if result.emotion == "neutral":
                # Decay current intensity
                new_intensity = cur.intensity * (1.0 - alpha)
                self._consecutive_neutral += 1

                # After threshold, snap back fully to neutral
                if self._consecutive_neutral >= self._NEUTRAL_DECAY_THRESHOLD:
                    self._state = MoodState()
                    self._consecutive_neutral = 0
                else:
                    if new_intensity < 0.08:
                        self._state = MoodState()
                    else:
                        self._state = MoodState(
                            primary=cur.primary,
                            intensity=new_intensity,
                            consecutive_count=cur.consecutive_count,
                            explicit=cur.explicit,
                            history=cur.history,
                        )
                return

            self._consecutive_neutral = 0

            if result.emotion == cur.primary:
                # Same mood — EMA intensity up
                new_intensity = cur.intensity + alpha * (result.intensity - cur.intensity)
                new_count = cur.consecutive_count + 1
                explicit = cur.explicit or result.explicit
            else:
                # Mood shift — blend: new mood wins if (new_intensity × alpha) > current
                blended = result.intensity * alpha
                if blended > cur.intensity * 0.5:
                    # Switch to new mood
                    new_intensity = blended
                    new_count = 1
                    explicit = result.explicit
                else:
                    # Not strong enough to override — keep current, slight intensity dip
                    new_intensity = cur.intensity * (1.0 - alpha * 0.3)
                    new_count = cur.consecutive_count
                    explicit = cur.explicit
                    # Still record the new emotion in history
                    history = (cur.history[-4:] + [result.emotion])
                    self._state = MoodState(
                        primary=cur.primary,
                        intensity=new_intensity,
                        consecutive_count=new_count,
                        explicit=explicit,
                        history=history,
                    )
                    return

            history = (cur.history[-4:] + [result.emotion])
            self._state = MoodState(
                primary=result.emotion,
                intensity=min(new_intensity, 1.0),
                consecutive_count=new_count,
                explicit=explicit,
                history=history,
            )

    def current_state(self) -> MoodState:
        with self._lock:
            # Return a shallow copy to avoid race conditions
            s = self._state
            return MoodState(
                primary=s.primary,
                intensity=s.intensity,
                consecutive_count=s.consecutive_count,
                explicit=s.explicit,
                history=list(s.history),
            )

    def get_personality_directive(self) -> str:
        """
        Return the mood-adaptive system message block to inject into LLM calls.
        Returns "" for neutral or very low intensity (< 0.15).
        The returned string starts with '[ANKITA-MOOD:' for easy find-and-replace.
        """
        state = self.current_state()
        if state.primary == "neutral" or state.intensity < 0.15:
            return ""
        return _DIRECTIVES.get(state.primary, "")

    def reset(self) -> None:
        """Clear session mood state (e.g. on /reset command)."""
        with self._lock:
            self._state = MoodState()
            self._consecutive_neutral = 0


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton
# ─────────────────────────────────────────────────────────────────────────────

_TRACKER_INSTANCE: Optional[SessionMoodTracker] = None
_TRACKER_LOCK = threading.Lock()


def get_mood_tracker() -> SessionMoodTracker:
    """Return the module-level SessionMoodTracker singleton."""
    global _TRACKER_INSTANCE
    if _TRACKER_INSTANCE is None:
        with _TRACKER_LOCK:
            if _TRACKER_INSTANCE is None:
                _TRACKER_INSTANCE = SessionMoodTracker()
    return _TRACKER_INSTANCE


# ─────────────────────────────────────────────────────────────────────────────
# Helper: inject / replace mood message in a messages list
# ─────────────────────────────────────────────────────────────────────────────

def apply_mood_to_messages(messages: list, directive: str) -> None:
    """
    Inject or replace the mood directive system message in-place.

    • If a [ANKITA-MOOD: ...] marker message exists → replace it
    • If directive is non-empty and no marker exists → insert at index 1
      (right after the base SYSTEM_PROMPT) or append if messages is empty
    • If directive is empty → remove any existing marker message (clean up)
    """
    marker = _MOOD_MARKER

    # Find existing mood message
    existing_idx = None
    for i, msg in enumerate(messages):
        if msg.get("role") == "system" and isinstance(msg.get("content"), str):
            if marker in msg["content"]:
                existing_idx = i
                break

    if not directive:
        # Remove existing mood message if present
        if existing_idx is not None:
            messages.pop(existing_idx)
        return

    mood_msg = {"role": "system", "content": directive}

    if existing_idx is not None:
        # Replace in-place
        messages[existing_idx] = mood_msg
    else:
        # Insert after the first system message (base prompt), else at start
        insert_at = 1
        if messages and messages[0].get("role") == "system":
            insert_at = 1
        else:
            insert_at = 0
        messages.insert(insert_at, mood_msg)
