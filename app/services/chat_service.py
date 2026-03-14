import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import List, Optional, Dict, Iterator, Any, Union
import uuid
import threading

from config import CHATS_DATA_DIR, MAX_CHAT_HISTORY_TURNS, GROQ_API_KEYS
from app.model import ChatMessage, ChatHistory
from app.services.groq_service import GroqService
from app.services.realtime_service import RealtimeGroqService
from app.services.brain_service import BrainService
from app.utils.key_rotation import get_next_key_pair

logger = logging.getLogger("J.A.R.V.I.S")

JARVIS_BRAIN_SEARCH_TIMEOUT = 15
SAVE_EVERY_N_CHUNKS = 5

class ChatService:
    def __init__(
        self,
        groq_service: GroqService,
        realtime_service: RealtimeGroqService = None,
        brain_service: BrainService = None,
    ):
        self.groq_service = groq_service
        self.realtime_service = realtime_service
        self.brain_service = brain_service
        self.sessions: Dict[str, List[ChatMessage]] = {}
        self._save_lock = threading.Lock()

    def load_session_from_disk(self, session_id: str) -> bool:
        safe_session_id = session_id.replace("-", "").replace(" ", "_")
        filename = f"chat_{safe_session_id}.json"
        filepath = CHATS_DATA_DIR / filename

        if not filepath.exists():
            return False

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                chat_dict = json.load(f)
            messages = []
            for msg in chat_dict.get("messages", []):
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                role = role if role in ("user", "assistant") else "user"
                content = msg.get("content")
                content = content if isinstance(content, str) else str(content or "")
                messages.append(ChatMessage(role=role, content=content))
            self.sessions[session_id] = messages
            return True
        except Exception as e:
            logger.warning("Failed to load session %s from disk: %s", session_id, e)
            return False

    def validate_session_id(self, session_id: str) -> bool:
        if not session_id or not session_id.strip():
            return False
        if "\0" in session_id:
            return False
        if ".." in session_id or "/" in session_id or "\\" in session_id:
            return False
        if len(session_id) > 255:
            return False
        return True

    def get_or_create_session(self, session_id: Optional[str] = None) -> str:
        t0 = time.perf_counter()
        if not session_id:
            new_session_id = str(uuid.uuid4())
            self.sessions[new_session_id] = []
            logger.info("[TIMING] session_get_or_create: %.3fs (new)", time.perf_counter() - t0)
            return new_session_id

        if not self.validate_session_id(session_id):
            raise ValueError(
                f"Invalid session_id format: {session_id}. Session ID must be non-empty, "
                "not contain path traversal characters, and be under 255 characters."
            )

        if session_id in self.sessions:
            logger.info("[TIMING] session_get_or_create: %.3fs (memory)", time.perf_counter() - t0)
            return session_id

        if self.load_session_from_disk(session_id):
            logger.info("[TIMING] session_get_or_create: %.3fs (disk)", time.perf_counter() - t0)
            return session_id

        self.sessions[session_id] = []
        logger.info("[TIMING] session_get_or_create: %.3fs (new_id)", time.perf_counter() - t0)
        return session_id

    def add_message(self, session_id: str, role: str, content: str):
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        self.sessions[session_id].append(ChatMessage(role=role, content=content))

    def get_chat_history(self, session_id: str) -> List[ChatMessage]:
        return self.sessions.get(session_id, [])

    def format_history_for_llm(self, session_id: str, exclude_last: bool = False) -> List[tuple]:
        messages = self.get_chat_history(session_id)
        history = []
        messages_to_process = messages[:-1] if exclude_last and messages else messages

        i = 0
        while i < len(messages_to_process) - 1:
            user_msg = messages_to_process[i]
            ai_msg = messages_to_process[i + 1]
            if user_msg.role == "user" and ai_msg.role == "assistant":
                u_content = user_msg.content if isinstance(user_msg.content, str) else str(user_msg.content or "")
                a_content = ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content or "")
                history.append((u_content, a_content))
                i += 2
            else:
                i += 1

        if len(history) > MAX_CHAT_HISTORY_TURNS:
            history = history[-MAX_CHAT_HISTORY_TURNS:]
        return history

    def process_message(self, session_id: str, user_message: str) -> str:
        logger.info("[GENERAL] Session: %s | User: %.200s", session_id[:12], user_message)
        self.add_message(session_id, "user", user_message)
        chat_history = self.format_history_for_llm(session_id, exclude_last=True)
        logger.info("[GENERAL] History pairs sent to LLM: %d", len(chat_history))
        _, chat_idx = get_next_key_pair(len(GROQ_API_KEYS), need_brain=False)
        response = self.groq_service.get_response(question=user_message, chat_history=chat_history, key_start_index=chat_idx)
        self.add_message(session_id, "assistant", response)
        logger.info("[GENERAL] Response length: %d chars | Preview: %.120s", len(response), response)
        return response

    def process_realtime_message(self, session_id: str, user_message: str) -> str:
        if not self.realtime_service:
            raise ValueError("Realtime service is not initialized. Cannot process realtime queries.")
        logger.info("[REALTIME] Session: %s | User: %.200s", session_id[:12], user_message)
        self.add_message(session_id, "user", user_message)
        chat_history = self.format_history_for_llm(session_id, exclude_last=True)
        logger.info("[REALTIME] History pairs sent to LLM: %d", len(chat_history))
        _, chat_idx = get_next_key_pair(len(GROQ_API_KEYS), need_brain=False)
        response = self.realtime_service.get_response(question=user_message, chat_history=chat_history, key_start_index=chat_idx)
        self.add_message(session_id, "assistant", response)
        logger.info("[REALTIME] Response length: %d chars | Preview: %.120s", len(response), response)
        return response

    def process_message_stream(
        self, session_id: str, user_message: str
    ) -> Iterator[Union[str, Dict[str, Any]]]:
        logger.info("[GENERAL-STREAM] Session: %s | User: %.200s", session_id[:12], user_message)
        self.add_message(session_id, "user", user_message)
        self.add_message(session_id, "assistant", "")
        chat_history = self.format_history_for_llm(session_id, exclude_last=True)
        logger.info("[GENERAL-STREAM] History pairs sent to LLM: %d", len(chat_history))

        yield {"_activity": {"event": "query_detected", "message": user_message}}
        yield {"_activity": {"event": "routing", "route": "general"}}
        yield {"_activity": {"event": "streaming_started", "route": "general"}}

        _, chat_idx = get_next_key_pair(len(GROQ_API_KEYS), need_brain=False)
        chunk_count = 0
        t0 = time.perf_counter()
        try:
            for chunk in self.groq_service.stream_response(
                question=user_message, chat_history=chat_history, key_start_index=chat_idx
            ):
                if isinstance(chunk, dict):
                    yield chunk
                    continue
                if chunk_count == 0:
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    yield {"_activity": {"event": "first_chunk", "route": "general", "elapsed_ms": elapsed_ms}}
                self.sessions[session_id][-1].content += chunk
                chunk_count += 1
                if chunk_count % SAVE_EVERY_N_CHUNKS == 0:
                    self.save_chat_session(session_id, log_timing=False)
                yield chunk
        finally:
            final_response = self.sessions[session_id][-1].content
            logger.info("[GENERAL-STREAM] Completed | Chunks: %d | Response length: %d chars", chunk_count, len(final_response))
            self.save_chat_session(session_id)

    def process_realtime_message_stream(
        self, session_id: str, user_message: str
    ) -> Iterator[Union[str, Dict[str, Any]]]:
        if not self.realtime_service:
            raise ValueError("Realtime service is not initialized.")
        logger.info("[REALTIME-STREAM] Session: %s | User: %.200s", session_id[:12], user_message)
        self.add_message(session_id, "user", user_message)
        self.add_message(session_id, "assistant", "")
        chat_history = self.format_history_for_llm(session_id, exclude_last=True)
        logger.info("[REALTIME-STREAM] History pairs sent to LLM: %d", len(chat_history))

        yield {"_activity": {"event": "query_detected", "message": user_message}}
        yield {"_activity": {"event": "routing", "route": "realtime"}}
        yield {"_activity": {"event": "streaming_started", "route": "realtime"}}

        _, chat_idx = get_next_key_pair(len(GROQ_API_KEYS), need_brain=False)
        chunk_count = 0
        t0 = time.perf_counter()
        try:
            for chunk in self.realtime_service.stream_response(
                question=user_message, chat_history=chat_history, key_start_index=chat_idx
            ):
                if isinstance(chunk, dict):
                    yield chunk
                    continue
                if chunk_count == 0:
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    yield {"_activity": {"event": "first_chunk", "route": "realtime", "elapsed_ms": elapsed_ms}}
                self.sessions[session_id][-1].content += chunk
                chunk_count += 1
                if chunk_count % SAVE_EVERY_N_CHUNKS == 0:
                    self.save_chat_session(session_id, log_timing=False)
                yield chunk
        finally:
            final_response = self.sessions[session_id][-1].content
            logger.info("[REALTIME-STREAM] Completed | Chunks: %d | Response length: %d chars", chunk_count, len(final_response))
            self.save_chat_session(session_id)

    def process_jarvis_message_stream(
        self, session_id: str, user_message: str
    ) -> Iterator[Union[str, Dict[str, Any]]]:
        logger.info("[JARVIS-STREAM] Session: %s | User: %.200s", session_id[:12], user_message)
        self.add_message(session_id, "user", user_message)
        self.add_message(session_id, "assistant", "")
        chat_history = self.format_history_for_llm(session_id, exclude_last=True)

        yield {"_activity": {"event": "query_detected", "message": user_message}}

        brain_idx, chat_idx = get_next_key_pair(len(GROQ_API_KEYS), need_brain=True)

        query_type = "realtime"
        reasoning = "Defaulting to realtime"
        brain_elapsed_ms = 0
        formatted_results = ""
        search_payload = None

        def _run_brain():
            if self.brain_service and brain_idx is not None:
                qt, r, ms = self.brain_service.classify(user_message, chat_history, key_index=brain_idx)
                return (qt, r, ms)
            return ("realtime", "No brain service", 0)

        def _run_search():
            if self.realtime_service:
                return self.realtime_service.prefetch_web_search(user_message, chat_history)
            return ("", None)

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_brain = executor.submit(_run_brain)
            future_search = executor.submit(_run_search)
            try:
                query_type, reasoning, brain_elapsed_ms = future_brain.result(timeout=JARVIS_BRAIN_SEARCH_TIMEOUT)
            except FuturesTimeoutError:
                logger.warning("[JARVIS] Brain classification timed out after %ds, defaulting to realtime", JARVIS_BRAIN_SEARCH_TIMEOUT)
                query_type, reasoning, brain_elapsed_ms = "realtime", "Brain timeout, defaulting to realtime", 0

            if query_type == "general":
                formatted_results, search_payload = "", None
            else:
                try:
                    formatted_results, search_payload = future_search.result(timeout=JARVIS_BRAIN_SEARCH_TIMEOUT)
                except FuturesTimeoutError:
                    logger.warning("[JARVIS] Web search prefetch timed out after %ds", JARVIS_BRAIN_SEARCH_TIMEOUT)
                    formatted_results, search_payload = "", None

        logger.info("[JARVIS] Brain: %s in %d ms — %s", query_type, brain_elapsed_ms, reasoning)

        yield {"_activity": {"event": "decision", "query_type": query_type, "reasoning": reasoning, "elapsed_ms": brain_elapsed_ms}}
        yield {"_activity": {"event": "routing", "route": query_type}}
        if query_type == "realtime" and search_payload:
            yield {"_search_results": search_payload}
        yield {"_activity": {"event": "streaming_started", "route": query_type}}

        chunk_count = 0
        t0 = time.perf_counter()
        try:
            if query_type == "general":
                stream = self.groq_service.stream_response(
                    question=user_message, chat_history=chat_history, key_start_index=chat_idx
                )
            else:
                if not self.realtime_service:
                    raise ValueError("Realtime service not initialized.")
                stream = self.realtime_service.stream_response_with_prefetched(
                    question=user_message,
                    chat_history=chat_history,
                    formatted_results=formatted_results,
                    payload=search_payload,
                    key_start_index=chat_idx,
                )

            for chunk in stream:
                if isinstance(chunk, dict):
                    yield chunk
                    continue
                if chunk_count == 0:
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    yield {"_activity": {"event": "first_chunk", "route": query_type, "elapsed_ms": elapsed_ms}}
                self.sessions[session_id][-1].content += chunk
                chunk_count += 1
                if chunk_count % SAVE_EVERY_N_CHUNKS == 0:
                    self.save_chat_session(session_id, log_timing=False)
                yield chunk
        finally:
            final_response = self.sessions[session_id][-1].content
            logger.info("[JARVIS-STREAM] Completed | Route: %s | Chunks: %d | Response length: %d chars",
                        query_type, chunk_count, len(final_response))
            self.save_chat_session(session_id)

    def save_chat_session(self, session_id: str, log_timing: bool = True):
        if session_id not in self.sessions or not self.sessions[session_id]:
            return

        messages = self.sessions[session_id]
        safe_session_id = session_id.replace("-", "").replace(" ", "_")
        filename = f"chat_{safe_session_id}.json"
        filepath = CHATS_DATA_DIR / filename

        chat_dict = {
            "session_id": session_id,
            "messages": [{"role": msg.role, "content": msg.content} for msg in messages]
        }

        max_retries = 3
        last_exc = None
        for attempt in range(max_retries):
            try:
                with self._save_lock:
                    t0 = time.perf_counter() if log_timing else 0
                    with open(filepath, "w", encoding="utf-8") as f:
                        json.dump(chat_dict, f, indent=2, ensure_ascii=False)
                    if log_timing:
                        logger.info("[TIMING] save_session_json: %.3fs", time.perf_counter() - t0)
                    return
            except OSError as e:
                last_exc = e
                if attempt < max_retries - 1:
                    time.sleep(0.1 * (attempt + 1))
            except Exception as e:
                logger.error("Failed to save chat session %s to disk: %s", session_id, e)
                return
        logger.error("Failed to save chat session %s after %d retries: %s", session_id, max_retries, last_exc)