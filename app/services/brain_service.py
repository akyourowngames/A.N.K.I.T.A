import logging
import re
import time
from typing import List, Optional, Tuple, Literal

from config import GROQ_API_KEYS, GROQ_BRAIN_MODEL

logger = logging.getLogger("J.A.R.V.I.S")

QueryType = Literal["general", "realtime"]
MAX_CONTEXT_TURNS = 6
MAX_MESSAGE_PREVIEW = 500
REASONING_GENERAL = "Answerable from knowledge and context"
REASONING_REALTIME = "Needs live web search"
REASONING_DEFAULT = "Brain unavailable; defaulting to realtime"
REASONING_UNCLEAR = "Unclear; defaulting to realtime"

_BRAIN_SYSTEM_PROMPT = """You are a query classifier for an AI assistant. Your ONLY job is to decide whether a user's message needs LIVE WEB SEARCH or not.

Output EXACTLY one word: either "general" or "realtime".

- general: ONLY questions that are purely from static knowledge, learning data, or conversation. Examples: "Tell me a joke", "What did I ask you before?", "Thanks", "Hello"

- realtime: ALWAYS use realtime for:
  * ANY question about a person (famous or not): "Who is Elon Musk?", "Tell me about [person]", "What is [name] known for?", "Who is that actor?" — the LLM cannot know current facts; web search can.
  * Anything that could have changed: news, weather, stock prices, sports scores, elections, "latest", "current", "today", "recent", "now".
  * Factual lookups where real-time data would be better: events, companies, products, releases, versions.
  * Follow-up questions about real-time topics: If the previous message was about prices/news/current events and the user asks "what is it", "tell me more", "what about now", etc. -> ALWAYS "realtime"

CRITICAL CONTEXT RULE: Look at the conversation history. If the user previously asked about something that requires real-time data (prices, news, current events), and now asks a follow-up question like "what is it", "what about it", "tell me more" -> ALWAYS route to "realtime" because they're continuing the same topic.

STRONG RULE: If the question is about a person (who, what, tell me about, etc.) -> ALWAYS "realtime". The LLM cannot know current facts; web search can.

When in doubt, prefer "realtime" — it's better to search when not needed than to miss current information.

Output ONLY the word. No explanation, no punctuation, no other text."""

class BrainService:
    def __init__(self):
        self._llms = []
        if GROQ_API_KEYS:
            try:
                from langchain_groq import ChatGroq
                self._llms = [
                    ChatGroq(
                        groq_api_key=key,
                        model_name=GROQ_BRAIN_MODEL,
                        temperature=0.0,
                        max_tokens=20,
                        request_timeout=10,
                    )
                    for key in GROQ_API_KEYS
                ]
                logger.info("[BRAIN] Groq brain initialized (model: %s) with %d key(s)", GROQ_BRAIN_MODEL, len(self._llms))
            except Exception as e:
                logger.warning("[BRAIN] Failed to create Groq brain: %s", e)
        if not self._llms:
            logger.warning("[BRAIN] No API keys. Classification will default to realtime.")

    def classify(
        self,
        user_message: str,
        chat_history: Optional[List[Tuple[str, str]]] = None,
        key_index: int = 0,
    ) -> Tuple[QueryType, str, int]:
        if not self._llms:
            return ("realtime", REASONING_DEFAULT, 0)

        context_lines = []
        if chat_history:
            for u, a in chat_history[-MAX_CONTEXT_TURNS:]:
                u_preview = (u or "")[:MAX_MESSAGE_PREVIEW] + ("…" if len(u or "") > MAX_MESSAGE_PREVIEW else "")
                a_preview = (a or "")[:MAX_MESSAGE_PREVIEW] + ("…" if len(a or "") > MAX_MESSAGE_PREVIEW else "")
                context_lines.append(f"User: {u_preview}")
                context_lines.append(f"Assistant: {a_preview}")
        context_block = "\n".join(context_lines) if context_lines else "(No prior conversation)"
        msg_preview = (user_message or "")[:MAX_MESSAGE_PREVIEW]
        user_content = f"""Conversation so far:
{context_block}

Current user message: {msg_preview}

Classify the current message. Output ONLY: general or realtime"""

        t0 = time.perf_counter()
        try:
            from langchain_core.messages import SystemMessage, HumanMessage
            idx = key_index % len(self._llms)
            llm = self._llms[idx]
            response = llm.invoke([
                SystemMessage(content=_BRAIN_SYSTEM_PROMPT),
                HumanMessage(content=user_content),
            ])
            text = (response.content or "").strip().lower()
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            logger.warning("[BRAIN] Groq error after %d ms: %s. Defaulting to realtime.", elapsed_ms, e)
            return ("realtime", f"API error: {str(e)[:60]}", elapsed_ms)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if re.search(r"\brealtime\b", text):
            logger.info("[BRAIN] Groq (key #%d) returned realtime in %d ms", key_index + 1, elapsed_ms)
            return ("realtime", REASONING_REALTIME, elapsed_ms)
        if re.search(r"\bgeneral\b", text):
            logger.info("[BRAIN] Groq (key #%d) returned general in %d ms", key_index + 1, elapsed_ms)
            return ("general", REASONING_GENERAL, elapsed_ms)
        logger.warning("[BRAIN] Unexpected output: %r in %d ms. Defaulting to realtime.", text[:100], elapsed_ms)
        return ("realtime", REASONING_UNCLEAR, elapsed_ms)