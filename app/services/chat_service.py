import base64
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional, Dict, Iterator, Any, Union
import uuid
import threading
from config import CHATS_DATA_DIR, CAMERA_CAPTURES_DIR, MAX_CHAT_HISTORY_TURNS, GROQ_API_KEYS, SPECULATIVE_EXECUTION_ENABLED
from app.model import ChatMessage
from app.services.groq_service import GroqService
from app.services.realtime_service import RealtimeGroqService
from app.services.brain_service import BrainService
from app.services.decision_types import (
    CATEGORY_GENERAL, CATEGORY_REALTIME, CATEGORY_CAMERA, CATEGORY_TASK,
    CATEGORY_MIXED, HEAVY_INTENTS, INSTANT_INTENTS
)
from app.services.task_executor import TaskExecutor, TaskResponse
from app.services.task_manager import TaskManager
from app.services.vision_service import VisionService
from app.utils.key_rotation import get_next_key_pair

CAMERA_BYPASS_TOKEN = "ITCAMTOKENIT"


def _save_camera_image(img_base64: str, session_id: str) -> Optional[Path]:
    if not img_base64 or not CAMERA_CAPTURES_DIR:
        return None

    raw = img_base64.split(",", 1)[-1] if "," in img_base64 else img_base64

    try:
        data = base64.b64decode(raw)
        if len(data) < 1000:
            logger.warning("[VISION] Captured image very small (%d bytes), may be invalid", len(data))
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        safe_id = (session_id or "").replace("/", "_")[:16] or "unknown"
        filename = f"cam_{safe_id}_{ts}.jpg"
        path = CAMERA_CAPTURES_DIR / filename
        path.write_bytes(data)
        logger.info("[VISION] Saved camera capture: %s (%d bytes) -> %s", path.name, len(data), path)
        return path

    except Exception as e:
        logger.warning("[VISION] Failed to save camera image: %s", e)
        return None


logger = logging.getLogger("J.A.R.V.I.S")
SAVE_EVERY_N_CHUNKS = 20


class ChatService:
    def __init__(
        self,
        groq_service,
        realtime_service=None,
        brain_service=None,
        task_executor=None,
        vision_service=None,
        task_manager=None,
        prompt_router=None,
    ):
        self.groq_service = groq_service
        self.realtime_service = realtime_service
        self.brain_service = brain_service
        self.task_executor = task_executor
        self.vision_service = vision_service
        self.task_manager = task_manager
        self.prompt_router = prompt_router
        self.sessions: Dict[str, List[ChatMessage]] = {}
        self._save_lock = threading.Lock()
        self._speculative_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="jarvis-fastpath")

    def _collect_general_stream(
        self,
        user_message: str,
        chat_history: List[tuple],
        key_start_index: Optional[int],
    ) -> List[Union[str, Dict[str, Any]]]:
        return list(
            self.groq_service.stream_response(
                question=user_message,
                chat_history=chat_history,
                key_start_index=key_start_index,
            )
        )

    def _collect_realtime_stream(
        self,
        user_message: str,
        chat_history: List[tuple],
        key_start_index: Optional[int],
    ) -> List[Union[str, Dict[str, Any]]]:
        if not self.realtime_service:
            return []
        return list(
            self.realtime_service.stream_response(
                question=user_message,
                chat_history=chat_history,
                key_start_index=key_start_index,
            )
        )

    def load_session_from_disk(self, session_id: str) -> bool:
        try:
            safe_session_id = session_id.replace("/", "_").replace(" ", "_")
            filepath = CHATS_DATA_DIR / f"chat_{safe_session_id}.json"
            CHATS_DATA_DIR.mkdir(parents=True, exist_ok=True)

            if not filepath.exists():
                return False

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
        self, session_id: str, user_message: str, imgbase64: Optional[str] = None
    ) -> Iterator[Union[str, Dict[str, Any]]]:

        t0_jarvis = time.perf_counter()
        logger.info("[JARVIS-STREAM] Session: %s | User: %.200s | img: %s",
                    session_id[:12], user_message[:80], "yes" if imgbase64 else "no")

        self.add_message(session_id, "user", user_message)
        self.add_message(session_id, "assistant", "")
        chat_history = self.format_history_for_llm(session_id, exclude_last=True)

        yield {"_activity": {"event": "query_detected", "message": user_message}}

        if imgbase64 and CAMERA_BYPASS_TOKEN in (user_message or ""):
            yield {"_activity": {"event": "decision", "query_type": "vision", "reasoning": "Image attached", "elapsed_ms": 0}}
            yield {"_activity": {"event": "routing", "route": "vision"}}
            yield {"_activity": {"event": "vision_analyzing", "message": "Analyzing image..."}}
            yield {"_activity": {"event": "streaming_started", "route": "vision"}}
            prompt = (user_message or "").replace(CAMERA_BYPASS_TOKEN, "").strip() or "What do you see in this image?"
            clean_msg = prompt or "What do you see in this image?"

            if self.sessions[session_id]:
                self.sessions[session_id][-2].content = clean_msg
            _save_camera_image(imgbase64, session_id)

            if self.vision_service:
                text = self.vision_service.describe_image(imgbase64, prompt)

            else:
                text = "Vision is not available. Please set NVIDIA_API_KEY."

            self.sessions[session_id][-1].content = text
            yield text
            self.save_chat_session(session_id)
            return

        brain_idx, chat_idx = get_next_key_pair(len(GROQ_API_KEYS), need_brain=bool(self.brain_service))
        speculative_general_future = None
        speculative_general_started = 0.0
        speculative_realtime_future = None

        if SPECULATIVE_EXECUTION_ENABLED and not imgbase64:
            speculative_general_started = time.perf_counter()
            speculative_general_future = self._speculative_executor.submit(
                self._collect_general_stream,
                user_message,
                chat_history,
                chat_idx,
            )

            if self.realtime_service:
                speculative_realtime_future = self._speculative_executor.submit(
                    self._collect_realtime_stream,
                    user_message,
                    chat_history,
                    chat_idx,
                )
        category = CATEGORY_GENERAL
        primary_elapsed_ms = 0
        primary_method = "default"
        prompt_decision = None

        if self.brain_service:
            category, primary_method, primary_elapsed_ms = self.brain_service.classify_primary(
                user_message, chat_history, key_index=brain_idx if brain_idx is not None else 0
            )

        if self.prompt_router and category == CATEGORY_REALTIME:
            try:
                prompt_decision = self.prompt_router.classify_route(
                    user_message, chat_history, key_index=brain_idx if brain_idx is not None else 0
                )
                if prompt_decision.primary in (CATEGORY_TASK, CATEGORY_MIXED):
                    category = prompt_decision.primary
                    primary_method = f"{prompt_decision.method}:{prompt_decision.reason or 'classified'}"
                    primary_elapsed_ms = prompt_decision.elapsed_ms
            except Exception as e:
                logger.warning("[PROMPT-ROUTER] Realtime validation failed, keeping brain route: %s", e)

        yield {"_activity": {"event": "decision", "query_type": category, "reasoning": primary_method.capitalize(), "elapsed_ms": primary_elapsed_ms}}

        if category == CATEGORY_CAMERA:
            yield {"_activity": {"event": "routing", "route": "camera"}}

            if imgbase64:
                yield {"_activity": {"event": "vision_analyzing", "message": "Analyzing image..."}}
                yield {"_activity": {"event": "streaming_started", "route": "vision"}}
                _save_camera_image(imgbase64, session_id)

                if self.vision_service:
                    text = self.vision_service.describe_image(imgbase64, user_message)

                else:
                    text = "Vision is not available. Please set NVIDIA_API_KEY."

            else:
                text = "Let me take a look..."
                yield {"_actions": {"wopens": [], "plays": [], "images": [], "contents": [],
                                    "googlesearches": [], "youtubesearches": [],
                                    "cam": {"action": "open_and_capture", "resend_message": user_message}}}
                yield {"_activity": {"event": "actions_emitted", "message": "camera (auto-capture)"}}

            self.sessions[session_id][-1].content = text
            yield text
            self.save_chat_session(session_id)
            elapsed_jarvis = time.perf_counter() - t0_jarvis
            logger.info("[JARVIS-STREAM] Camera flow complete in %.2fs", elapsed_jarvis)
            return

        if category in (CATEGORY_TASK, CATEGORY_MIXED):
            yield {"_activity": {"event": "routing", "route": "task" if category == CATEGORY_TASK else "mixed"}}

            task_types = []
            task_elapsed_ms = 0
            task_method = "default"
            if self.brain_service:
                task_types, task_method, task_elapsed_ms = self.brain_service.classify_task(
                    user_message, chat_history, key_index=brain_idx if brain_idx is not None else 0
                )

            if self.prompt_router and self._should_validate_with_prompt_router(category, task_types):
                try:
                    prompt_decision = self.prompt_router.classify_route(
                        user_message, chat_history, key_index=brain_idx if brain_idx is not None else 0
                    )
                    yield {"_activity": {
                        "event": "route_validated",
                        "route": f"{prompt_decision.primary}/{prompt_decision.tool or '-'}",
                        "elapsed_ms": prompt_decision.elapsed_ms,
                    }}
                except Exception as e:
                    logger.warning("[PROMPT-ROUTER] Validation failed, keeping brain route: %s", e)

            if prompt_decision and prompt_decision.tool == "unsupported_needs_tool":
                text = (
                    "I don't have a tool for that yet, so I won't fake it by opening a random website."
                )
                self.sessions[session_id][-1].content = text
                yield {"_activity": {"event": "intent_classified", "intent": "unsupported_needs_tool"}}
                yield text
                self.save_chat_session(session_id)
                elapsed_jarvis = time.perf_counter() - t0_jarvis
                logger.info("[JARVIS-STREAM] Unsupported tool stopped in %.2fs | reason: %s",
                            elapsed_jarvis, prompt_decision.reason)
                return

            if prompt_decision and self._should_use_prompt_override(category, task_types, prompt_decision):
                task_types = [tool for tool, _ in prompt_decision.tasks]
                task_method = prompt_decision.method
                task_elapsed_ms = prompt_decision.elapsed_ms
                if self.brain_service:
                    self.brain_service._last_task_decisions = prompt_decision.tasks

            task_name = ", ".join(task_types[:3]) if task_types else "task"
            yield {"_activity": {"event": "intent_classified", "intent": task_name}}

            intents = self.brain_service.extract_task_payloads(user_message, task_types, chat_history) if self.brain_service else []

            chain_plan = self.task_executor.describe_chain(intents) if self.task_executor else None
            if chain_plan:
                yield {"_activity": {"event": "tool_chain_planned", "message": chain_plan["message"]}}

            instant_intents = [(t, p) for t, p in intents if t not in HEAVY_INTENTS]
            heavy_intents = [(t, p) for t, p in intents if t in HEAVY_INTENTS]

            instant_response = TaskResponse()

            if self.task_executor and instant_intents:
                yield {"_activity": {"event": "tasks_executing", "message": f"Running instant tasks..."}}
                instant_response = self.task_executor.execute(instant_intents, chat_history)
                yield {"_activity": {"event": "tasks_completed", "message": "Instant tasks done"}}

            has_instant_actions = (
                instant_response.wopens or instant_response.plays or
                instant_response.googlesearches or instant_response.youtubesearches or
                instant_response.cam
            )

            if has_instant_actions:
                actions = {
                    "wopens": instant_response.wopens,
                    "plays": instant_response.plays,
                    "images": [],
                    "contents": [],
                    "googlesearches": instant_response.googlesearches,
                    "youtubesearches": instant_response.youtubesearches,
                    "cam": instant_response.cam,
                }

                action_summary = []
                if instant_response.wopens: action_summary.append("open")
                if instant_response.plays: action_summary.append("play")
                if instant_response.googlesearches or instant_response.youtubesearches: action_summary.append("search")
                if instant_response.cam: action_summary.append("camera")
                yield {"_activity": {"event": "actions_emitted", "message": ", ".join(action_summary) or "actions"}}
                yield {"_actions": actions}

            bg_task_ids = []

            if self.task_manager and heavy_intents:
                yield {"_activity": {"event": "tasks_executing", "message": "Dispatching background tasks..."}}

                for intent_type, payload in heavy_intents:
                    task_id = self.task_manager.submit(intent_type, payload, chat_history)
                    bg_task_ids.append({"task_id": task_id, "type": intent_type, "label": payload.get("prompt", payload.get("message", ""))[:100]})

                yield {"_activity": {"event": "background_dispatched", "message": f"{len(bg_task_ids)} task(s) in background"}}

            elif not self.task_manager and heavy_intents:
                yield {"_activity": {"event": "tasks_executing", "message": f"Running {task_name}..."}}
                sync_response = self.task_executor.execute(heavy_intents, chat_history) if self.task_executor else TaskResponse()
                yield {"_activity": {"event": "tasks_completed", "message": "Tasks completed"}}

                if sync_response.images or sync_response.contents:
                    actions = {
                        "wopens": [], "plays": [],
                        "images": sync_response.images,
                        "contents": sync_response.contents,
                        "googlesearches": [], "youtubesearches": [],
                        "cam": None,
                    }
                    yield {"_actions": actions}
                instant_response.text = instant_response.text or sync_response.text

            if category == CATEGORY_MIXED:
                yield {"_activity": {"event": "streaming_started", "route": "mixed"}}
                stream_svc = self.realtime_service if self.realtime_service else self.groq_service
                chunk_count = 0
                t0 = time.perf_counter()

                try:

                    for chunk in stream_svc.stream_response(
                        question=user_message, chat_history=chat_history, key_start_index=chat_idx
                    ):

                        if isinstance(chunk, dict):
                            yield chunk
                            continue

                        if chunk_count == 0:
                            elapsed_ms = int((time.perf_counter() - t0) * 1000)
                            yield {"_activity": {"event": "first_chunk", "route": "mixed", "elapsed_ms": elapsed_ms}}

                        self.sessions[session_id][-1].content += chunk
                        chunk_count += 1

                        if chunk_count % SAVE_EVERY_N_CHUNKS == 0:
                            self.save_chat_session(session_id, log_timing=False)
                        yield chunk

                finally:
                    self.save_chat_session(session_id)

                if bg_task_ids:
                    yield {"_background_tasks": bg_task_ids}
                elapsed_jarvis = time.perf_counter() - t0_jarvis
                logger.info("[JARVIS-STREAM] Mixed flow complete in %.2fs | tasks: %s", elapsed_jarvis, task_types)
                return

            text_parts = []

            if instant_response.text:
                text_parts.append(instant_response.text)

            if bg_task_ids:
                bg_labels = []

                for bt in bg_task_ids:
                    if bt["type"] == "generate image":
                        bg_labels.append("image generation")
                    elif bt["type"] == "content":
                        bg_labels.append("content writing")
                    else:
                        bg_labels.append(bt["type"])

                text_parts.append(f"I'm working on the {', '.join(bg_labels)} in the background. I'll open it for you when it's ready.")

            text = " ".join(text_parts) if text_parts else "Done."
            self.sessions[session_id][-1].content = text
            yield text

            if bg_task_ids:
                yield {"_background_tasks": bg_task_ids}

            self.save_chat_session(session_id)
            elapsed_jarvis = time.perf_counter() - t0_jarvis
            logger.info("[JARVIS-STREAM] Task flow complete in %.2fs | tasks: %s | bg: %d", elapsed_jarvis, task_types, len(bg_task_ids))
            return

        use_realtime = category == CATEGORY_REALTIME and self.realtime_service
        route_name = "realtime" if use_realtime else "general"
        yield {"_activity": {"event": "routing", "route": route_name}}
        yield {"_activity": {"event": "streaming_started", "route": route_name}}

        stream_svc = self.realtime_service if use_realtime else self.groq_service
        stream_chunks = None
        chunk_count = 0
        t0 = time.perf_counter()

        if use_realtime and speculative_realtime_future:
            try:
                stream_chunks = speculative_realtime_future.result()
                if stream_chunks:
                    logger.info("[JARVIS-STREAM] Using speculative realtime response")
            except Exception as e:
                logger.warning("[JARVIS-STREAM] Speculative realtime response failed, retrying normally: %s", e)

        elif not use_realtime and speculative_general_future:
            try:
                stream_chunks = speculative_general_future.result()
                if speculative_general_started:
                    t0 = speculative_general_started
                logger.info("[JARVIS-STREAM] Using speculative general response")
            except Exception as e:
                logger.warning("[JARVIS-STREAM] Speculative general response failed, retrying normally: %s", e)

        try:

            stream_iter = stream_chunks if stream_chunks is not None else stream_svc.stream_response(
                question=user_message, chat_history=chat_history, key_start_index=chat_idx
            )

            for chunk in stream_iter:

                if isinstance(chunk, dict):
                    yield chunk
                    continue

                if chunk_count == 0:
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    yield {"_activity": {"event": "first_chunk", "route": route_name, "elapsed_ms": elapsed_ms}}

                self.sessions[session_id][-1].content += chunk
                chunk_count += 1
                if chunk_count % SAVE_EVERY_N_CHUNKS == 0:
                    self.save_chat_session(session_id, log_timing=False)
                yield chunk

        finally:
            self.save_chat_session(session_id)

        elapsed_jarvis = time.perf_counter() - t0_jarvis
        logger.info("[JARVIS-STREAM] %s flow complete in %.2fs | chunks: %d", route_name, elapsed_jarvis, chunk_count)

    def _should_validate_with_prompt_router(self, category: str, task_types: List[str]) -> bool:
        if not task_types:
            return False
        return category == CATEGORY_MIXED or "open" in task_types or len(task_types) > 1

    def _should_use_prompt_override(self, category: str, task_types: List[str], prompt_decision) -> bool:
        if not prompt_decision or not prompt_decision.tasks:
            return False
        if prompt_decision.confidence < 0.75:
            return False
        if category == CATEGORY_MIXED and prompt_decision.primary == CATEGORY_MIXED:
            return True
        if "open" in task_types and prompt_decision.primary in (CATEGORY_TASK, CATEGORY_MIXED):
            return True
        if len(task_types) > 1 and prompt_decision.primary in (CATEGORY_TASK, CATEGORY_MIXED):
            return True
        return False

    def save_chat_session(self, session_id: str, log_timing: bool = True):
        if session_id not in self.sessions or not self.sessions[session_id]:
            return

        messages = self.sessions[session_id]

        safe_session_id = session_id.replace("/", "_").replace(" ", "_")
        filename = f"chat_{safe_session_id}.json"
        filepath = CHATS_DATA_DIR / filename
        CHATS_DATA_DIR.mkdir(parents=True, exist_ok=True)

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
