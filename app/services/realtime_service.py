from typing import List, Optional, Iterator, Tuple, Any
from tavily import TavilyClient
import logging
import os
import time

from app.services.groq_service import GroqService, escape_curly_braces, AllGroqApisFailedError
from app.services.vector_store import VectorStoreService
from app.utils.retry import with_retry
from config import REALTIME_CHAT_ADDENDUM, GROQ_API_KEYS, GROQ_MODEL

logger = logging.getLogger("J.A.R.V.I.S")

GROQ_REQUEST_TIMEOUT_FAST = 15

_QUERY_EXTRACTION_PROMPT = (
    "You are a search query optimizer. Given the user's message and recent conversation, "
    "produce a single short, focused web search query (max 12 words) that will find the "
    "information the user needs. Resolve any references (like 'that website', 'him', 'it') "
    "using the conversation history. Output ONLY the search query, nothing else."
)

_GROUNDING_GUARD_TEMPLATE = (
    "IMPORTANT: You MUST answer using the web search results provided above. "
    "Use the AI-SYNTHESIZED ANSWER as your primary answer when it exists. "
    "Never say you lack current data or mention a knowledge cutoff. "
    "AI-SYNTHESIZED ANSWER:\n{ai_answer}"
)

class RealtimeGroqService(GroqService):
    def __init__(self, vector_store_service: VectorStoreService):
        super().__init__(vector_store_service)

        tavily_api_key = os.getenv("TAVILY_API_KEY", "")
        if tavily_api_key:
            self.tavily_client = TavilyClient(api_key=tavily_api_key)
            logger.info("Tavily search client initialized successfully")
        else:
            self.tavily_client = None
            logger.warning("TAVILY_API_KEY not set. Realtime search will be unavailable.")

        if GROQ_API_KEYS:
            from langchain_groq import ChatGroq
            self._fast_llm = ChatGroq(
                groq_api_key=GROQ_API_KEYS[0],
                model_name=GROQ_MODEL,
                temperature=0.0,
                request_timeout=GROQ_REQUEST_TIMEOUT_FAST,
                max_tokens=50,
            )
        else:
            self._fast_llm = None

    def _extract_search_query(
        self, question: str, chat_history: Optional[List[tuple]] = None
    ) -> str:
        if not self._fast_llm:
            return question

        q = question.strip()
        if len(q) <= 60 and not any(p in q.lower() for p in (" it ", " that ", " him ", " her ", " them ")):
            return q

        try:
            t0 = time.perf_counter()
            history_context = ""
            if chat_history:
                recent = chat_history[-3:]
                parts = []
                for h, a in recent:
                    parts.append(f"User: {h[:200]}")
                    parts.append(f"Assistant: {a[:200]}")
                history_context = "\n".join(parts)

            if history_context:
                full_prompt = (
                    f"{_QUERY_EXTRACTION_PROMPT}\n\n"
                    f"Recent conversation:\n{history_context}\n\n"
                    f"User's latest message: {question}\n\n"
                    f"Search query:"
                )
            else:
                full_prompt = (
                    f"{_QUERY_EXTRACTION_PROMPT}\n\n"
                    f"User's message: {question}\n\n"
                    f"Search query:"
                )

            response = self._fast_llm.invoke(full_prompt)
            extracted = response.content.strip().strip('"').strip("'")

            if extracted and 3 <= len(extracted) <= 200:
                logger.info(
                    "[REALTIME] Query extraction: '%s' -> '%s' (%.3fs)",
                    question[:80], extracted[:80], time.perf_counter() - t0,
                )
                return extracted

            logger.warning("[REALTIME] Query extraction returned unusable result, using raw question")
            return question

        except Exception as e:
            logger.warning("[REALTIME] Query extraction failed (%s), using raw question", e)
            return question

    def search_tavily(self, query: str, num_results: int = 7) -> Tuple[str, Optional[dict]]:
        if not self.tavily_client:
            logger.warning("Tavily client not initialized. TAVILY_API_KEY not set.")
            return ("", None)
        if not query or not str(query).strip():
            return ("", None)

        try:
            t0 = time.perf_counter()

            response = with_retry(
                lambda: self.tavily_client.search(
                    query=query,
                    search_depth="fast",
                    max_results=num_results,
                    include_answer=True,
                    include_raw_content=False,
                ),
                max_retries=3,
                initial_delay=1.0,
            )

            results = response.get("results", [])
            ai_answer = response.get("answer", "")

            if not results and not ai_answer:
                logger.warning("No Tavily search results for query: %s", query)
                return ("", None)

            payload: Optional[dict] = {
                "query": query,
                "answer": ai_answer,
                "results": [
                    {
                        "title": r.get("title", "No title"),
                        "content": (r.get("content") or "")[:500],
                        "url": r.get("url", ""),
                        "score": round(float(r.get("score", 0)), 2),
                    }
                    for r in results[:num_results]
                ],
            }

            parts = [f"--- WEB SEARCH RESULTS FOR: {query} ---\n"]
            if ai_answer:
                parts.append(f"AI-SYNTHESIZED ANSWER (use this as your primary source):\n{ai_answer}\n")
            if results:
                parts.append("INDIVIDUAL SOURCES:")
                for i, result in enumerate(results[:num_results], 1):
                    title = result.get("title", "No title")
                    content = result.get("content", "")
                    url = result.get("url", "")
                    score = result.get("score", 0)
                    parts.append(f"\n[Source {i}] (relevance: {score:.2f})")
                    parts.append(f"Title: {title}")
                    if content:
                        parts.append(f"Content: {content}")
                    if url:
                        parts.append(f"URL: {url}")
            parts.append("\n=== END SEARCH RESULTS ===")
            formatted = "\n".join(parts)

            logger.info(
                "[TAVILY] %d results, AI answer: %s, formatted: %d chars (%.3fs)",
                len(results), "yes" if ai_answer else "no",
                len(formatted), time.perf_counter() - t0,
            )

            return (formatted, payload)

        except Exception as e:
            logger.error("Error performing Tavily search: %s", e)
            return ("", None)

    def _format_results_from_payload(self, payload: dict) -> str:
        if not payload:
            return ""
        query = payload.get("query") or ""
        results = payload.get("results") or []
        ai_answer = (payload.get("answer") or "").strip()

        parts = [f"--- WEB SEARCH RESULTS FOR: {query} ---\n"]
        if ai_answer:
            parts.append(f"AI-SYNTHESIZED ANSWER (use this as your primary source):\n{ai_answer}\n")
        if results:
            parts.append("INDIVIDUAL SOURCES:")
            for i, result in enumerate(results, 1):
                title = result.get("title", "No title")
                content = result.get("content", "")
                url = result.get("url", "")
                score = result.get("score", 0)
                parts.append(f"\n[Source {i}] (relevance: {float(score):.2f})")
                parts.append(f"Title: {title}")
                if content:
                    parts.append(f"Content: {content}")
                if url:
                    parts.append(f"URL: {url}")
        parts.append("\n=== END SEARCH RESULTS ===")
        return "\n".join(parts)

    def _build_grounding_guard(self, payload: Optional[dict]) -> Optional[str]:
        if not payload:
            return None
        ai_answer = (payload.get("answer") or "").strip()
        if not ai_answer:
            return None
        return _GROUNDING_GUARD_TEMPLATE.format(ai_answer=ai_answer)

    def get_response(self, question: str, chat_history: Optional[List[tuple]] = None, key_start_index: int = 0) -> str:
        try:
            search_query = self._extract_search_query(question, chat_history)
            logger.info("[REALTIME] Searching Tavily for: %s", search_query)

            formatted_results, payload = self.search_tavily(search_query, num_results=7)
            if formatted_results:
                logger.info("[REALTIME] Tavily returned results (length: %d chars)", len(formatted_results))
            else:
                logger.warning("[REALTIME] Tavily returned no results for: %s", search_query)

            extra_parts = []
            if formatted_results:
                extra_parts.append(escape_curly_braces(formatted_results))
            guard = self._build_grounding_guard(payload)
            if guard:
                extra_parts.append(guard)
            if not extra_parts:
                extra_parts = None
            prompt, messages = self._build_prompt_and_messages(
                question, chat_history,
                extra_system_parts=extra_parts,
                mode_addendum=REALTIME_CHAT_ADDENDUM,
            )

            t0 = time.perf_counter()
            response_content = self._invoke_llm(prompt, messages, question, key_start_index=key_start_index)
            logger.info("[TIMING] groq_api: %.3fs", time.perf_counter() - t0)
            logger.info(
                "[RESPONSE] Realtime chat | Length: %d chars | Preview: %.120s",
                len(response_content), response_content,
            )
            return response_content

        except AllGroqApisFailedError:
            raise
        except Exception as e:
            logger.error("Error in realtime get_response: %s", e, exc_info=True)
            raise

    def prefetch_web_search(
        self, question: str, chat_history: Optional[List[tuple]] = None
    ) -> Tuple[str, Optional[dict]]:
        try:
            t0 = time.perf_counter()
            search_query = self._extract_search_query(question, chat_history)
            logger.info("[REALTIME] Pre-fetch: extracted query '%s' in %.3fs", search_query[:60], time.perf_counter() - t0)
            formatted_results, payload = self.search_tavily(search_query, num_results=7)
            if formatted_results:
                logger.info("[REALTIME] Pre-fetch: Tavily returned %d chars in %.3fs total",
                            len(formatted_results), time.perf_counter() - t0)
            return (formatted_results or "", payload)
        except Exception as e:
            logger.warning("[REALTIME] Pre-fetch failed: %s", e)
            return ("", None)

    def stream_response(self, question: str, chat_history: Optional[List[tuple]] = None, key_start_index: int = 0) -> Iterator[Any]:
        try:
            yield {"_activity": {"event": "extracting_query", "message": "Extracting search query..."}}
            search_query = self._extract_search_query(question, chat_history)
            logger.info("[REALTIME] Searching Tavily for: %s", search_query)
            yield {"_activity": {"event": "searching_web", "query": search_query, "message": f"Searching web for: {search_query}"}}

            formatted_results, payload = self.search_tavily(search_query, num_results=7)
            num_results = len(payload.get("results", [])) if payload else 0
            if formatted_results:
                logger.info("[REALTIME] Tavily returned results (length: %d chars)", len(formatted_results))
                yield {"_activity": {"event": "search_completed", "message": f"Search completed: {num_results} results, {len(formatted_results)} chars of context"}}
            else:
                logger.warning("[REALTIME] Tavily returned no results for: %s", search_query)
                yield {"_activity": {"event": "search_completed", "message": "No search results found"}}

            if payload:
                yield {"_search_results": payload}

            extra_parts = []
            if formatted_results:
                extra_parts.append(escape_curly_braces(formatted_results))
            guard = self._build_grounding_guard(payload)
            if guard:
                extra_parts.append(guard)
            if not extra_parts:
                extra_parts = None
            prompt, messages = self._build_prompt_and_messages(
                question, chat_history,
                extra_system_parts=extra_parts,
                mode_addendum=REALTIME_CHAT_ADDENDUM,
            )
            yield from self._stream_llm(prompt, messages, question, key_start_index=key_start_index)
            logger.info("[REALTIME] Stream completed for: %s", search_query)

        except AllGroqApisFailedError:
            raise
        except Exception as e:
            logger.error("Error in realtime stream_response: %s", e, exc_info=True)
            raise

    def stream_response_with_prefetched(
        self,
        question: str,
        chat_history: Optional[List[tuple]] = None,
        formatted_results: Optional[str] = None,
        payload: Optional[dict] = None,
        key_start_index: int = 0,
    ) -> Iterator[Any]:
        try:
            if not formatted_results and payload:
                formatted_results = self._format_results_from_payload(payload)
            extra_parts = []
            if formatted_results:
                extra_parts.append(escape_curly_braces(formatted_results))
            guard = self._build_grounding_guard(payload)
            if guard:
                extra_parts.append(guard)
            if not extra_parts:
                extra_parts = None
            prompt, messages = self._build_prompt_and_messages(
                question, chat_history,
                extra_system_parts=extra_parts,
                mode_addendum=REALTIME_CHAT_ADDENDUM,
            )
            yield from self._stream_llm(prompt, messages, question, key_start_index=key_start_index)
            logger.info("[REALTIME] Stream completed (pre-fetched results)")
        except AllGroqApisFailedError:
            raise
        except Exception as e:
            logger.error("Error in realtime stream_response_with_prefetched: %s", e, exc_info=True)
            raise
