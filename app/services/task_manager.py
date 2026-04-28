import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor
from app.services.decision_types import INTENT_GENERATE_IMAGE, INTENT_CONTENT

logger = logging.getLogger("J.A.R.V.I.S")
TASK_TTL = 3600


@dataclass
class TaskEntry:
    task_id: str
    status: str = "running"
    task_type: str = ""
    label: str = ""
    prompt: str = ""
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = 0.0
    image_bytes: Optional[bytes] = None


class TaskManager:

    def __init__(self, task_executor):
        self.task_executor = task_executor
        self._tasks: Dict[str, TaskEntry] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bg-task")
        logger.info("[TASK-MGR] Background task manager initialized (4 workers)")

    def submit(
        self,
        intent_type: str,
        payload: dict,
        chat_history: Optional[List[tuple]] = None,
    ) -> str:

        task_id = uuid.uuid4().hex[:8]
        prompt = payload.get("prompt", payload.get("message", ""))[:200]

        if intent_type == INTENT_GENERATE_IMAGE:
            label = "Generating image"

        elif intent_type == INTENT_CONTENT:
            label = "Writing content"

        else:
            label = "Processing task"

        entry = TaskEntry(
            task_id=task_id,
            status="running",
            task_type=intent_type,
            label=label,
            prompt=prompt,
            created_at=time.time(),
        )

        with self._lock:
            self._tasks[task_id] = entry

        self._pool.submit(self._run, task_id, intent_type, payload, chat_history)
        logger.info("[TASK-MGR] Submitted %s task %s: %.80s", intent_type, task_id, prompt)
        return task_id

    def get(self, task_id: str) -> Optional[TaskEntry]:
        with self._lock:
            return self._tasks.get(task_id)

    def get_serializable(self, task_id: str) -> Optional[dict]:
        entry = self.get(task_id)
        if not entry:
            return None
        return {
            "task_id": entry.task_id,
            "status": entry.status,
            "task_type": entry.task_type,
            "label": entry.label,
            "prompt": entry.prompt,
            "result": entry.result,
            "error": entry.error,
        }

    def _run(self, task_id: str, intent_type: str, payload: dict, chat_history):
        t0 = time.perf_counter()

        try:
            if intent_type == INTENT_GENERATE_IMAGE:
                img_result = self.task_executor._do_generate_image(payload)

                if img_result:
                    pollinations_url, image_bytes = img_result
                    result = {
                        "type": "image",
                        "url": f"/tasks/{task_id}/image",
                        "prompt": payload.get("prompt", payload.get("message", "")),
                    }
                    with self._lock:
                        self._tasks[task_id].image_bytes = image_bytes

                else:
                    raise RuntimeError("Image generation returned no result. Check API key or content policy.")

            elif intent_type == INTENT_CONTENT:
                text = self.task_executor._do_content(payload, chat_history)

                if text:
                    result = {
                        "type": "content",
                        "text": text,
                        "prompt": payload.get("prompt", payload.get("message", "")),
                    }

                else:
                    raise RuntimeError("Content generation returned no result.")

            else:
                raise ValueError(f"Unsupported background task type: {intent_type}")

            with self._lock:
                self._tasks[task_id].status = "completed"
                self._tasks[task_id].result = result

            elapsed = time.perf_counter() - t0
            logger.info("[TASK-MGR] Task %s completed in %.2fs", task_id, elapsed)

        except Exception as e:
            with self._lock:
                self._tasks[task_id].status = "failed"
                self._tasks[task_id].error = str(e)[:500]
            logger.warning("[TASK-MGR] Task %s failed: %s", task_id, e)

    def cleanup_old(self):
        cutoff = time.time() - TASK_TTL

        with self._lock:
            to_remove = [tid for tid, e in self._tasks.items() if e.created_at < cutoff]
            for tid in to_remove:
                del self._tasks[tid]

        if to_remove:
            logger.info("[TASK-MGR] Cleaned up %d expired tasks", len(to_remove))

    def shutdown(self):
        self._pool.shutdown(wait=False)
        logger.info("[TASK-MGR] Shutdown complete")