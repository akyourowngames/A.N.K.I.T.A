import logging
import time
from typing import Iterator, List, Optional

from app.services.nvidia_client import NvidiaClient
from app.services.vector_store import VectorStoreService
from app.utils.retry import with_retry
from app.utils.time_info import get_time_information
from config import (
    GENERAL_CHAT_ADDENDUM,
    GROQ_API_KEYS,
    JARVIS_SYSTEM_PROMPT,
    NVIDIA_BASE_URL,
    NVIDIA_MODEL,
)

logger = logging.getLogger("J.A.R.V.I.S")
NVIDIA_REQUEST_TIMEOUT = 60

ALL_APIS_FAILED_MESSAGE = (
    "I'm unable to process your request at the moment. The NVIDIA AI service is "
    "temporarily unavailable. Please try again in a few minutes."
)


class AllGroqApisFailedError(Exception):
    pass


def escape_curly_braces(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}") if text else text


_REPEAT_WINDOW = 100
_REPEAT_THRESHOLD = 3
_REPEAT_CHECK_INTERVAL = 200


def _detect_repetition_loop(text: str) -> bool:
    if len(text) < _REPEAT_WINDOW * _REPEAT_THRESHOLD:
        return False
    phrase = text[-_REPEAT_WINDOW:]
    return text.count(phrase) >= _REPEAT_THRESHOLD


def _truncate_at_repetition(text: str) -> str:
    if len(text) < _REPEAT_WINDOW * _REPEAT_THRESHOLD:
        return text
    phrase = text[-_REPEAT_WINDOW:]
    if text.count(phrase) < _REPEAT_THRESHOLD:
        return text
    first = text.find(phrase)
    second = text.find(phrase, first + 1)
    return text[:second].rstrip() if second > first else text


def _is_rate_limit_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "429" in str(exc) or "rate limit" in msg or "tokens per day" in msg


def _log_timing(label: str, elapsed: float, extra: str = ""):
    msg = f"[TIMING] {label}: {elapsed:.3f}s"
    if extra:
        msg += f" ({extra})"
    logger.info(msg)


def _mask_api_key(key: str) -> str:
    if not key or len(key) <= 12:
        return "***masked***"
    return f"{key[:8]}...{key[-4:]}"


class GroqService:
    """Compatibility wrapper: existing app calls this GroqService, but it uses NVIDIA."""

    def __init__(self, vector_store_service: VectorStoreService):
        if not GROQ_API_KEYS:
            raise ValueError("No NVIDIA_API_KEY configured. Set NVIDIA_API_KEY in .env")

        self.clients = [
            NvidiaClient(key, NVIDIA_BASE_URL, timeout=NVIDIA_REQUEST_TIMEOUT)
            for key in GROQ_API_KEYS
        ]
        self.vector_store_service = vector_store_service
        logger.info(
            "Initialized NVIDIA-backed chat service with %d API key(s), model=%s",
            len(GROQ_API_KEYS),
            NVIDIA_MODEL,
        )

    def _invoke_llm(
        self,
        messages: List[dict],
        key_start_index: int = 0,
        model: str = NVIDIA_MODEL,
        max_tokens: int = 1024,
        temperature: float = 0.4,
    ) -> str:
        n = len(self.clients)
        last_exc = None
        keys_tried = []

        for j in range(n):
            i = (key_start_index + j) % n
            keys_tried.append(i)
            masked_key = _mask_api_key(GROQ_API_KEYS[i])
            logger.info("[NVIDIA] Trying API key #%d/%d: %s", i + 1, n, masked_key)

            try:
                text = with_retry(
                    lambda: self.clients[i].chat(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    ),
                    max_retries=2,
                    initial_delay=0.5,
                )
                if _detect_repetition_loop(text):
                    logger.warning("[NVIDIA] Repetition loop detected - truncating response (%d chars)", len(text))
                    text = _truncate_at_repetition(text)
                return text

            except Exception as e:
                last_exc = e
                if _is_rate_limit_error(e):
                    logger.warning("[NVIDIA] API key #%d/%d rate limited: %s", i + 1, n, masked_key)
                else:
                    logger.warning("[NVIDIA] API key #%d/%d failed: %s - %s", i + 1, n, masked_key, str(e)[:120])

        masked_all = ", ".join(_mask_api_key(GROQ_API_KEYS[j]) for j in keys_tried)
        logger.error("[NVIDIA] All %d API key(s) failed. Tried: %s", n, masked_all)
        raise AllGroqApisFailedError(ALL_APIS_FAILED_MESSAGE) from last_exc

    def _stream_llm(
        self,
        messages: List[dict],
        key_start_index: int = 0,
        model: str = NVIDIA_MODEL,
        max_tokens: int = 1024,
        temperature: float = 0.4,
    ) -> Iterator[str]:
        n = len(self.clients)
        last_exc = None

        for j in range(n):
            i = (key_start_index + j) % n
            masked_key = _mask_api_key(GROQ_API_KEYS[i])
            logger.info("[NVIDIA] Streaming with API key #%d/%d: %s", i + 1, n, masked_key)

            try:
                chunk_count = 0
                first_chunk_time = None
                stream_start = time.perf_counter()
                accumulated = ""
                last_check_len = 0

                for content in self.clients[i].stream_chat(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    if first_chunk_time is None:
                        first_chunk_time = time.perf_counter() - stream_start
                        _log_timing("first_chunk", first_chunk_time)

                    chunk_count += 1
                    accumulated += content

                    if len(accumulated) - last_check_len >= _REPEAT_CHECK_INTERVAL:
                        last_check_len = len(accumulated)
                        if _detect_repetition_loop(accumulated):
                            logger.warning("[NVIDIA] Repetition loop detected after %d chars - stopping", len(accumulated))
                            break

                    yield content

                _log_timing("nvidia_stream_total", time.perf_counter() - stream_start, f"chunks: {chunk_count}")
                return

            except Exception as e:
                last_exc = e
                if _is_rate_limit_error(e):
                    logger.warning("[NVIDIA] API key #%d/%d rate limited: %s", i + 1, n, masked_key)
                else:
                    logger.warning("[NVIDIA] API key #%d/%d failed: %s - %s", i + 1, n, masked_key, str(e)[:120])

        logger.error("[NVIDIA] All %d API key(s) failed during stream.", n)
        raise AllGroqApisFailedError(ALL_APIS_FAILED_MESSAGE) from last_exc

    def _build_messages(
        self,
        question: str,
        chat_history: Optional[List[tuple]] = None,
        extra_system_parts: Optional[List[str]] = None,
        mode_addendum: str = "",
    ) -> List[dict]:
        context = ""
        context_sources = []
        t0 = time.perf_counter()

        try:
            retriever = self.vector_store_service.get_retriever(k=5)
            context_docs = retriever.invoke(question)
            if context_docs:
                context = "\n".join(doc.page_content for doc in context_docs)
                context_sources = [doc.metadata.get("source", "unknown") for doc in context_docs]
                logger.info("[CONTEXT] Retrieved %d chunks from sources: %s", len(context_docs), context_sources)
            else:
                logger.info("[CONTEXT] No relevant chunks found for query")
        except Exception as retrieval_err:
            logger.warning("Vector store retrieval failed, using empty context: %s", retrieval_err)
        finally:
            _log_timing("vector_db", time.perf_counter() - t0)

        system_message = JARVIS_SYSTEM_PROMPT
        system_message += f"\n\nCurrent time and date: {get_time_information()}"

        if context:
            system_message += f"\n\nRelevant context from your learning data and past conversations:\n{context}"
        if extra_system_parts:
            system_message += "\n\n" + "\n\n".join(extra_system_parts)
        if mode_addendum:
            system_message += f"\n\n{mode_addendum}"

        messages = [{"role": "system", "content": system_message}]
        if chat_history:
            for human_msg, ai_msg in chat_history:
                messages.append({"role": "user", "content": human_msg})
                messages.append({"role": "assistant", "content": ai_msg})
        messages.append({"role": "user", "content": question})

        logger.info(
            "[PROMPT] System message length: %d chars | History pairs: %d | Question: %.100s",
            len(system_message),
            len(chat_history) if chat_history else 0,
            question,
        )
        return messages

    def get_response(
        self,
        question: str,
        chat_history: Optional[List[tuple]] = None,
        key_start_index: int = 0,
    ) -> str:
        try:
            messages = self._build_messages(question, chat_history, mode_addendum=GENERAL_CHAT_ADDENDUM)
            t0 = time.perf_counter()
            result = self._invoke_llm(messages, key_start_index=key_start_index)
            _log_timing("nvidia_api", time.perf_counter() - t0)
            logger.info("[RESPONSE] General chat | Length: %d chars | Preview: %.120s", len(result), result)
            return result
        except AllGroqApisFailedError:
            raise
        except Exception as e:
            raise Exception(f"Error getting response from NVIDIA: {str(e)}") from e

    def stream_response(
        self,
        question: str,
        chat_history: Optional[List[tuple]] = None,
        key_start_index: int = 0,
    ) -> Iterator[str]:
        try:
            messages = self._build_messages(question, chat_history, mode_addendum=GENERAL_CHAT_ADDENDUM)
            yield {"_activity": {"event": "context_retrieved", "message": "Retrieved relevant context from knowledge base"}}
            yield from self._stream_llm(messages, key_start_index=key_start_index)
        except AllGroqApisFailedError:
            raise
        except Exception as e:
            raise Exception(f"Error streaming response from NVIDIA: {str(e)}") from e
