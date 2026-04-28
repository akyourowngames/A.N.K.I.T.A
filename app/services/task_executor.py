import json
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import quote, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from config import NVIDIA_FAST_MODEL, PC_STATE_ANSWER_TIMEOUT, TASK_EXECUTION_TIMEOUT
from app.services.decision_types import (
    INTENT_OPEN, INTENT_PLAY, INTENT_CAMERA,
    INTENT_OPEN_WEBCAM, INTENT_CLOSE_WEBCAM,
    INTENT_GENERATE_IMAGE, INTENT_CONTENT,
    INTENT_GOOGLE_SEARCH, INTENT_YOUTUBE_SEARCH, INTENT_CHAT,
    INTENT_OPEN_APP, INTENT_CLOSE_APP,
    INTENT_SET_VOLUME, INTENT_VOLUME_UP, INTENT_VOLUME_DOWN, INTENT_MUTE_VOLUME,
    INTENT_SET_BRIGHTNESS, INTENT_BRIGHTNESS_UP, INTENT_BRIGHTNESS_DOWN,
    INTENT_LOCK_SCREEN, INTENT_RUN_TERMINAL, INTENT_INSPECT_PC,
    HEAVY_INTENTS,
)
from app.utils.pc_state import PCStateInspector
from app.utils.system_control import SystemControl, parse_percent
from app.utils.terminal_control import TerminalControl

logger = logging.getLogger("J.A.R.V.I.S")


@dataclass
class TaskResponse:
    text: str = ""
    wopens: List[str] = field(default_factory=list)
    plays: List[str] = field(default_factory=list)
    images: List[str] = field(default_factory=list)
    contents: List[str] = field(default_factory=list)
    googlesearches: List[str] = field(default_factory=list)
    youtubesearches: List[str] = field(default_factory=list)
    cam: Optional[dict] = None
    local_results: List[str] = field(default_factory=list)


class TaskExecutor:

    def __init__(self, groq_service=None):
        self.groq_service = groq_service
        self.system_control = SystemControl()
        self.terminal_control = TerminalControl()
        self.pc_state = PCStateInspector()
        logger.info("[TASK] TaskExecutor initialized (Pollinations.ai for images)")

    def describe_chain(self, intents: List[tuple]) -> Optional[dict]:
        if not intents:
            return None

        steps = []
        heavy_count = 0

        for intent_type, payload in intents:
            if intent_type in HEAVY_INTENTS:
                heavy_count += 1
            target = self._describe_payload_target(payload)
            steps.append(f"{intent_type}" + (f": {target}" if target else ""))

        instant_count = len(intents) - heavy_count
        mode = "parallel where possible"
        if heavy_count and instant_count:
            mode = "instant tools first, heavy tools in background"
        elif heavy_count:
            mode = "background execution"

        return {
            "steps": steps,
            "instant_count": instant_count,
            "heavy_count": heavy_count,
            "parallel": len(intents) > 1,
            "message": f"{len(intents)} step(s): {', '.join(steps[:4])}. {mode}.",
        }

    def _describe_payload_target(self, payload: dict) -> str:
        for key in ("app", "url", "query", "prompt", "command", "level"):
            value = payload.get(key)
            if value:
                return str(value)[:80]
        return ""

    def execute(
        self,
        intents: List[tuple],
        chat_history: Optional[List[tuple]] = None,
    ) -> TaskResponse:

        response = TaskResponse()

        tasks = []

        for intent_type, payload in intents:

            if intent_type == INTENT_OPEN:
                tasks.append(("wopen", self._do_open, payload))

            elif intent_type == INTENT_PLAY:
                tasks.append(("play", self._do_play, payload))

            elif intent_type == INTENT_GENERATE_IMAGE:
                tasks.append(("image", self._do_generate_image, payload))

            elif intent_type == INTENT_CONTENT:
                tasks.append(("content", lambda p: self._do_content(p, chat_history), payload))

            elif intent_type == INTENT_GOOGLE_SEARCH:
                tasks.append(("google", self._do_google_search, payload))

            elif intent_type == INTENT_YOUTUBE_SEARCH:
                tasks.append(("youtube", self._do_youtube_search, payload))

            elif intent_type == INTENT_OPEN_APP:
                tasks.append(("local", self._do_open_app, payload))

            elif intent_type == INTENT_CLOSE_APP:
                tasks.append(("local", self._do_close_app, payload))

            elif intent_type == INTENT_SET_VOLUME:
                tasks.append(("local", self._do_set_volume, payload))

            elif intent_type == INTENT_VOLUME_UP:
                tasks.append(("local", self._do_volume_up, payload))

            elif intent_type == INTENT_VOLUME_DOWN:
                tasks.append(("local", self._do_volume_down, payload))

            elif intent_type == INTENT_MUTE_VOLUME:
                tasks.append(("local", self._do_mute_volume, payload))

            elif intent_type == INTENT_SET_BRIGHTNESS:
                tasks.append(("local", self._do_set_brightness, payload))

            elif intent_type == INTENT_BRIGHTNESS_UP:
                tasks.append(("local", self._do_brightness_up, payload))

            elif intent_type == INTENT_BRIGHTNESS_DOWN:
                tasks.append(("local", self._do_brightness_down, payload))

            elif intent_type == INTENT_LOCK_SCREEN:
                tasks.append(("local", self._do_lock_screen, payload))

            elif intent_type == INTENT_RUN_TERMINAL:
                tasks.append(("local", self._do_run_terminal, payload))

            elif intent_type == INTENT_INSPECT_PC:
                tasks.append(("local", self._do_inspect_pc, payload))

            elif intent_type == INTENT_OPEN_WEBCAM:
                response.cam = {"action": "open"}
                response.text = "Opening the webcam for you."

            elif intent_type == INTENT_CLOSE_WEBCAM:
                response.cam = {"action": "close"}
                response.text = "Webcam closed."

            elif intent_type == INTENT_CAMERA:
                response.cam = {"action": "open"}
                response.text = "Opening your webcam. Once it's on, send your message again and I'll describe what I see."

            elif intent_type == INTENT_CHAT:
                pass

        if not tasks:

            if not response.text and not response.cam:
                response.text = "I'm not sure what you'd like me to do. Could you clarify?"

            return response

        t0 = time.perf_counter()
        failed_tags = []

        try:

            with ThreadPoolExecutor(max_workers=min(6, len(tasks))) as executor:
                futures = {
                    executor.submit(fn, p): (tag, fn, p)
                    for tag, fn, p in tasks
                }

                for future in as_completed(futures, timeout=TASK_EXECUTION_TIMEOUT):
                    tag, fn, payload = futures[future]

                    try:
                        result = future.result()
                        if tag == "wopen" and result:
                            response.wopens.append(result)

                        elif tag == "play" and result:
                            response.plays.append(result)

                        elif tag == "image" and result:
                            response.images.append(result)

                        elif tag == "content" and result:
                            response.contents.append(result)

                        elif tag == "google" and result:
                            response.googlesearches.append(result)

                        elif tag == "youtube" and result:
                            response.youtubesearches.append(result)

                        elif tag == "local" and result:
                            response.local_results.append(result)

                    except Exception as e:
                        failed_tags.append(tag)
                        err_msg = str(e)[:100]
                        logger.warning("[TASK] Task %s failed: %s", tag, e)

                        if "content_policy" in err_msg.lower() or "safety" in err_msg.lower():
                            if tag == "image":
                                response.text = "I couldn't generate that image — it may violate content guidelines."

                        elif not response.text:
                            response.text = f"Something went wrong with that task: {err_msg}"

        except FuturesTimeoutError:
            logger.warning("[TASK] Task execution timed out after %ds", TASK_EXECUTION_TIMEOUT)

            if not response.text:
                response.text = "Some tasks took too long. Please try again."

        elapsed = time.perf_counter() - t0
        logger.info("[TASK] Executed %d tasks in %.2fs (failed: %s)", len(tasks), elapsed, failed_tags or "none")

        if not response.text:
            parts = self._build_conversational_response(
                response.wopens, response.plays, response.images,
                response.contents, response.googlesearches, response.youtubesearches,
                response.local_results,
            )
            response.text = parts if parts else "All done."

        return response

    def _url_to_display_name(self, url: str) -> str:
        u = (url or "").lower()
        mapping = {
            "facebook.com": "Facebook", "instagram.com": "Instagram", "youtube.com": "YouTube",
            "google.com": "Google", "netflix.com": "Netflix", "twitter.com": "Twitter",
            "x.com": "X", "gmail.com": "Gmail", "whatsapp.com": "WhatsApp",
            "linkedin.com": "LinkedIn", "reddit.com": "Reddit", "discord.com": "Discord",
            "spotify.com": "Spotify", "tiktok.com": "TikTok", "amazon.com": "Amazon",
            "github.com": "GitHub", "wikipedia.org": "Wikipedia", "stackoverflow.com": "Stack Overflow",
            "medium.com": "Medium", "notion.so": "Notion", "figma.com": "Figma",
            "canva.com": "Canva", "zoom.us": "Zoom", "drive.google.com": "Google Drive",
            "jarvisforeveryone.com": "Jarvis for Everyone", "graphy.com": "Graphy",
        }

        for key, name in mapping.items():
            if key in u:
                return name

        try:
            parsed = urlparse(url)
            domain = (parsed.netloc or parsed.path or "").replace("www.", "").split(".")[0]
            return domain.title() if domain else "the link"

        except Exception:
            return "the link"

    def _build_conversational_response(
        self,
        wopens: List[str],
        plays: List[str],
        images: List[str],
        contents: List[str],
        googlesearches: List[str],
        youtubesearches: List[str],
        local_results: Optional[List[str]] = None,
    ) -> str:

        parts = []

        if wopens:
            names = [self._url_to_display_name(u) for u in wopens]

            if len(names) == 1:
                parts.append(f"I've opened {names[0]} for you.")

            else:
                last = names[-1]
                rest = ", ".join(names[:-1])
                parts.append(f"I've opened {rest} and {last} for you.")

        if plays:
            parts.append("I've started playing that for you.")

        if images:
            count = len(images)
            parts.append(f"I've generated the image{'s' if count > 1 else ''} for you.")

        if contents:
            parts.append("I've written that for you.")

        if googlesearches or youtubesearches:
            parts.append("I've run the search for you.")

        if local_results:
            parts.extend(local_results)

        return " ".join(parts) if parts else "Done."

    def _validate_url(self, url: str) -> Optional[str]:

        if not url or len(url) > 2048:
            return None

        u = url.strip()

        if not u.startswith("http"):
            u = "https://" + u

        try:
            parsed = urlparse(u)

            if parsed.scheme not in ("http", "https"):
                logger.warning("[TASK] Rejected non-http URL: %s", u[:50])
                return None
            return u

        except Exception:
            return None

    def _do_open(self, payload: dict) -> Optional[str]:
        url = payload.get("url", "").strip()

        if not url:
            return None

        return self._validate_url(url)

    def _do_play(self, payload: dict) -> Optional[str]:
        query = (payload.get("query", payload.get("message", "")) or "").strip()[:500]
        if not query:
            return "https://www.youtube.com"
        return f"https://www.youtube.com/results?search_query={quote(query, safe='')}"

    def _do_generate_image(self, payload: dict) -> Optional[tuple]:
        """Returns (pollinations_url, image_bytes) or None on failure."""
        prompt = (payload.get("prompt", payload.get("message", "")) or "").strip()

        if len(prompt) < 3:
            logger.warning("[TASK] Image prompt too short (< 3 chars)")
            return None

        prompt = prompt[:4000]
        t0 = time.perf_counter()

        result = self._generate_pollinations(prompt)

        if result:
            logger.info("[TASK] Pollinations image downloaded in %.2fs", time.perf_counter() - t0)
            return result

        logger.warning("[TASK] Image generation failed")
        return None

    def _generate_pollinations(self, prompt: str) -> Optional[tuple]:
        """Download the generated image and return (url, bytes), or None on failure."""
        import httpx
        encoded_prompt = quote(prompt, safe="")
        api_url = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?model=flux&width=1024&height=1024&nologo=true&private=true&enhance=true&safe=false"
        )

        logger.info("[TASK] Fetching Pollinations image: %s", api_url[:120])
        for attempt in range(3):
            try:
                with httpx.Client(timeout=60, follow_redirects=True) as client:
                    resp = client.get(api_url)
                    if resp.status_code == 200 and resp.content:
                        content_type = resp.headers.get("content-type", "")
                        if "image" in content_type or len(resp.content) > 1000:
                            logger.info("[TASK] Pollinations image fetched (%d bytes)", len(resp.content))
                            return (api_url, resp.content)
                    logger.warning("[TASK] Pollinations attempt %d: status=%d", attempt + 1, resp.status_code)
            except Exception as e:
                logger.warning("[TASK] Pollinations attempt %d failed: %s", attempt + 1, e)
            time.sleep(2)
        return None

    def _do_content(self, payload: dict, chat_history: Optional[List[tuple]] = None) -> Optional[str]:
        prompt = (payload.get("prompt", payload.get("message", "")) or "").strip()

        if not prompt or not self.groq_service:
            return None

        content_question = f"Write the following. Be thorough and well-structured. Return only the requested content, no preamble.\n\n{prompt}"

        try:
            out = self.groq_service.get_response(
                question=content_question,
                chat_history=chat_history or [],
                key_start_index=0,
            )

            if not out or len(out.strip()) < 10:
                logger.warning("[TASK] Content generation returned empty or very short result")
                return None
            return out

        except Exception as e:
            logger.warning("[TASK] Content generation error: %s", e)
            return None

    def _do_google_search(self, payload: dict) -> Optional[str]:
        query = (payload.get("query", payload.get("message", "")) or "").strip()[:500]
        if not query:
            return None
        return f"https://www.google.com/search?q={quote(query, safe='')}"

    def _do_youtube_search(self, payload: dict) -> Optional[str]:
        query = (payload.get("query", payload.get("message", "")) or "").strip()[:500]
        if not query:
            return "https://www.youtube.com"
        return f"https://www.youtube.com/results?search_query={quote(query, safe='')}"

    def _do_open_app(self, payload: dict) -> Optional[str]:
        app = payload.get("app", payload.get("query", payload.get("message", "")))
        result = self.system_control.open_app(app)
        return result.message

    def _do_close_app(self, payload: dict) -> Optional[str]:
        app = payload.get("app", payload.get("query", payload.get("message", "")))
        result = self.system_control.close_app(app)
        return result.message

    def _do_set_volume(self, payload: dict) -> Optional[str]:
        result = self.system_control.set_volume(parse_percent(payload.get("level", payload.get("query", "")), 50))
        return result.message

    def _do_volume_up(self, payload: dict) -> Optional[str]:
        result = self.system_control.volume_up()
        return result.message

    def _do_volume_down(self, payload: dict) -> Optional[str]:
        result = self.system_control.volume_down()
        return result.message

    def _do_mute_volume(self, payload: dict) -> Optional[str]:
        result = self.system_control.mute_volume()
        return result.message

    def _do_set_brightness(self, payload: dict) -> Optional[str]:
        result = self.system_control.set_brightness(parse_percent(payload.get("level", payload.get("query", "")), 50))
        return result.message

    def _do_brightness_up(self, payload: dict) -> Optional[str]:
        result = self.system_control.brightness_up()
        return result.message

    def _do_brightness_down(self, payload: dict) -> Optional[str]:
        result = self.system_control.brightness_down()
        return result.message

    def _do_lock_screen(self, payload: dict) -> Optional[str]:
        result = self.system_control.lock_screen()
        return result.message

    def _do_run_terminal(self, payload: dict) -> Optional[str]:
        command = payload.get("command", payload.get("query", payload.get("message", "")))
        result = self.terminal_control.run(command)
        return result.message

    def _do_inspect_pc(self, payload: dict) -> Optional[str]:
        query = payload.get("message") or payload.get("query", "")
        result = self.pc_state.inspect(query)
        if result.ok and result.snapshot:
            direct_answer = self.pc_state.format_focused(query, result.snapshot)
            if self._use_direct_pc_answer(query):
                return direct_answer
            return self._answer_pc_state(query, result.snapshot) or direct_answer
        return result.message

    def _use_direct_pc_answer(self, query: str) -> bool:
        q = (query or "").lower()
        exact_terms = (
            "cpu", "processor", "download", "file", "window", "apps are open",
            "open apps", "port", "server", "battery", "disk", "storage",
            "space", "ram", "memory",
        )
        broad_terms = ("slow", "performance", "status", "overview", "summary", "health")
        return any(term in q for term in exact_terms) and not any(term in q for term in broad_terms)

    def _answer_pc_state(self, query: str, snapshot: dict) -> Optional[str]:
        if not self.groq_service or not getattr(self.groq_service, "clients", None):
            return None

        focused_snapshot = self.pc_state.focused_snapshot(query, snapshot)
        fallback = self.pc_state.format_focused(query, snapshot)

        prompt = (
            "You answer questions about the user's Windows PC using only this JSON snapshot.\n"
            "Answer the exact question, not the whole snapshot.\n"
            "Use clean chat formatting: a short title, a blank line, then only '- ' bullet points.\n"
            "Keep it compact: 2-6 bullets unless the user asks for full status.\n"
            "Do not use markdown bold, tables, tabs, or nested bullets.\n"
            "Include concrete process names, file names, ports, timestamps, percentages, and sizes when relevant.\n"
            "If the user asks what file was just downloaded, answer the latest_download first.\n"
            "If total CPU is not present, do not invent total or overall CPU; report the listed per-process CPU only.\n"
            "If the snapshot does not contain enough evidence, say that briefly.\n"
            "Do not recommend generic web advice unless the snapshot supports it.\n\n"
            f"User question: {query}\n\n"
            f"Relevant PC snapshot JSON:\n{json.dumps(focused_snapshot, ensure_ascii=False)[:6000]}"
        )

        messages = [
            {"role": "system", "content": "You are Jarvis' grounded PC-state answer layer."},
            {"role": "user", "content": prompt},
        ]

        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(
                self.groq_service._invoke_llm,
                messages,
                0,
                NVIDIA_FAST_MODEL,
                420,
                0.1,
            )
            answer = future.result(timeout=PC_STATE_ANSWER_TIMEOUT).strip()
            return self._clean_pc_answer(answer) or fallback
        except FuturesTimeoutError:
            logger.info("[PC-STATE] Answer LLM timed out after %.1fs; using focused formatter", PC_STATE_ANSWER_TIMEOUT)
            return fallback
        except Exception as exc:
            logger.warning("[PC-STATE] Answer LLM failed: %s", exc)
            return None
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _clean_pc_answer(self, answer: str) -> str:
        answer = (answer or "").strip()
        if not answer:
            return ""

        cleaned_lines = []
        for line in answer.replace("\t", "  ").splitlines():
            stripped = line.strip()
            stripped = stripped.replace("**", "").replace("__", "")

            if stripped.startswith(("* ", "+ ", "• ")):
                stripped = "- " + stripped[2:].strip()
            elif stripped.startswith(("-   ", "-  ")):
                stripped = "- " + stripped.lstrip("- ").strip()

            cleaned_lines.append(stripped if stripped else "")

        return "\n".join(cleaned_lines).strip()
