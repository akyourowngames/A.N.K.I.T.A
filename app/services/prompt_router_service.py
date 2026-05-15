import json
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from app.services.nvidia_client import NvidiaClient
from config import GROQ_API_KEYS, NVIDIA_BASE_URL, NVIDIA_FAST_MODEL

logger = logging.getLogger("J.A.R.V.I.S")


PRIMARY_LABELS = ("general", "realtime", "camera", "task", "mixed")

TOOL_LABELS = (
    "open",
    "play",
    "open_app",
    "close_app",
    "open_webcam",
    "close_webcam",
    "generate_image",
    "content",
    "google_search",
    "youtube_search",
    "inspect_pc",
    "run_terminal",
    "set_volume",
    "volume_up",
    "volume_down",
    "mute_volume",
    "set_brightness",
    "brightness_up",
    "brightness_down",
    "lock_screen",
    "unsupported_needs_tool",
)


@dataclass
class PromptRouteDecision:
    primary: str
    tool: Optional[str]
    query: str
    confidence: float
    reason: str
    elapsed_ms: int
    method: str = "prompt-router"
    tasks: List[Tuple[str, str]] = field(default_factory=list)


class PromptRouterService:
    def __init__(self, api_keys: Optional[List[str]] = None, model: str = NVIDIA_FAST_MODEL):
        keys = api_keys if api_keys is not None else GROQ_API_KEYS
        self.clients = [NvidiaClient(key, NVIDIA_BASE_URL, timeout=12) for key in keys if key]
        self.model = model
        if self.clients:
            logger.info("[PROMPT-ROUTER] Initialized with %d key(s), model=%s", len(self.clients), model)
        else:
            logger.warning("[PROMPT-ROUTER] No API keys configured")

    def classify_route(
        self,
        user_message: str,
        chat_history: Optional[List[Tuple[str, str]]] = None,
        key_index: int = 0,
    ) -> PromptRouteDecision:
        if not self.clients:
            raise ValueError("PromptRouterService has no configured API keys")

        started = time.perf_counter()
        client = self.clients[key_index % len(self.clients)]
        raw = client.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": self._user_prompt(user_message, chat_history)},
            ],
            temperature=0.0,
            max_tokens=320,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        data = self._parse_json(raw)

        primary = self._clean_label(data.get("primary"), PRIMARY_LABELS, "general")
        tasks = self._clean_tasks(data.get("tasks"))
        tool = self._clean_label(data.get("tool"), TOOL_LABELS, "")
        query = str(data.get("query") or "").strip()
        confidence = self._clean_confidence(data.get("confidence"))
        reason = str(data.get("reason") or "").strip()

        if not tasks and tool:
            tasks = [(tool, query)]
        if tasks:
            tool, query = tasks[0]

        if tool and primary not in ("task", "mixed"):
            primary = "task"
        if primary not in ("task", "mixed"):
            tool = None
            tasks = []
        elif not tool:
            tool = "unsupported_needs_tool"
            tasks = [(tool, query)]

        logger.info(
            "[PROMPT-ROUTER] %s -> %s/%s conf=%.2f (%d ms) %s",
            (user_message or "")[:60],
            primary,
            tool or "-",
            confidence,
            elapsed_ms,
            reason[:80],
        )
        return PromptRouteDecision(primary, tool, query, confidence, reason, elapsed_ms, tasks=tasks)

    def _system_prompt(self) -> str:
        return """You are Jarvis' routing classifier. Decide where the user's message should go. Do not answer and do not execute anything.

Return exactly one JSON object:
{"primary":"...","tool":"first tool or null","query":"first clean target/query if any","tasks":[{"tool":"...","query":"..."}],"confidence":0.0-1.0,"reason":"short reason"}

Golden examples to copy exactly in spirit:
- "can yu take ss" -> {"primary":"task","tool":"unsupported_needs_tool","query":"screenshot","tasks":[{"tool":"unsupported_needs_tool","query":"screenshot"}],"confidence":0.95,"reason":"screenshot request has no executor"}
- "open youtube" -> {"primary":"task","tool":"open","query":"youtube","tasks":[{"tool":"open","query":"youtube"}],"confidence":0.95,"reason":"open website command"}
- "what apps are open" -> {"primary":"task","tool":"inspect_pc","query":"open apps/windows","tasks":[{"tool":"inspect_pc","query":"open apps/windows"}],"confidence":0.95,"reason":"asks what is already open on this PC"}
- "generate image of a blue sports car" -> {"primary":"task","tool":"generate_image","query":"blue sports car","tasks":[{"tool":"generate_image","query":"blue sports car"}],"confidence":0.95,"reason":"image generation command"}
- "tell me about python and open youtube" -> {"primary":"mixed","tool":"open","query":"youtube","tasks":[{"tool":"open","query":"youtube"}],"confidence":0.9,"reason":"information request plus open action"}
- "search youtube for python decorators" -> {"primary":"task","tool":"youtube_search","query":"python decorators","tasks":[{"tool":"youtube_search","query":"python decorators"}],"confidence":0.95,"reason":"explicit YouTube search"}
- "play nanna re na re" -> {"primary":"task","tool":"play","query":"nanna re na re","tasks":[{"tool":"play","query":"nanna re na re"}],"confidence":0.95,"reason":"play media command"}
- "increase brightness" -> {"primary":"task","tool":"brightness_up","query":"brightness","tasks":[{"tool":"brightness_up","query":"brightness"}],"confidence":0.95,"reason":"directional brightness increase"}
- "latest cricket score today" -> {"primary":"realtime","tool":null,"query":"","tasks":[],"confidence":0.95,"reason":"current score question"}
- "open facebook and play despacito" -> {"primary":"task","tool":"open","query":"facebook","tasks":[{"tool":"open","query":"facebook"},{"tool":"play","query":"despacito"}],"confidence":0.95,"reason":"multi-tool: open website + play media"}
- "open google and search youtube for cats" -> {"primary":"task","tool":"open","query":"google","tasks":[{"tool":"open","query":"google"},{"tool":"youtube_search","query":"cats"}],"confidence":0.95,"reason":"multi-tool: open website + youtube search"}
- "generate image of a cat and write a poem about stars" -> {"primary":"task","tool":"generate_image","query":"a cat","tasks":[{"tool":"generate_image","query":"a cat"},{"tool":"content","query":"poem about stars"}],"confidence":0.95,"reason":"multi-tool: image gen + content writing"}
- "open youtube, set volume to 60, and play relaxing jazz" -> {"primary":"task","tool":"open","query":"youtube","tasks":[{"tool":"open","query":"youtube"},{"tool":"set_volume","query":"60"},{"tool":"play","query":"relaxing jazz"}],"confidence":0.9,"reason":"multi-tool: open + set volume + play"}
- "search google for python tutorials and open stackoverflow" -> {"primary":"task","tool":"google_search","query":"python tutorials","tasks":[{"tool":"google_search","query":"python tutorials"},{"tool":"open","query":"stackoverflow"}],"confidence":0.95,"reason":"multi-tool: search + open"}

Primary labels:
- general: casual chat, static knowledge, advice, coding help, math, definitions, or anything answerable without live web data and without taking an action.
- realtime: current/live/recent/changing information questions such as weather, scores, prices, news, reviews, current status, or up-to-date web facts.
- camera: visual analysis through camera or an attached image, such as identifying what the user is holding or showing.
- task: the user wants Jarvis to perform an action with a tool.
- mixed: the same message contains both an information/question request and an action request.

Tool labels for task/mixed:
- open: open a website, URL, domain, web app, or online service.
- play: play a song, video, music, artist, playlist, or media item.
- open_app: launch a desktop app on this Windows computer.
- close_app: close, quit, kill, stop, or terminate a desktop app/process.
- open_webcam: turn on/start/show the webcam feed.
- close_webcam: turn off/stop/close the webcam feed.
- generate_image: generate, draw, create, or make an image, picture, logo, artwork, or visual.
- content: write/draft/compose an essay, application, email, poem, code, letter, or other text.
- google_search: explicitly search Google or the web.
- youtube_search: explicitly search YouTube or find videos on YouTube without directly playing a specific item.
- inspect_pc: inspect this PC's current state, including already open apps/windows, CPU, RAM, memory, disk, battery, ports, downloads, or slow laptop diagnostics.
- run_terminal: run an explicit terminal, shell, command prompt, or PowerShell command.
- set_volume: set volume to a specific level.
- volume_up: increase volume.
- volume_down: decrease volume.
- mute_volume: mute/unmute/toggle mute.
- set_brightness: set brightness to a specific level.
- brightness_up: increase brightness.
- brightness_down: decrease/dim/lower brightness.
- lock_screen: lock the Windows session.
- unsupported_needs_tool: requested action has no executor, such as taking a screenshot/screen capture, sending messages, making calls, booking, buying, or controlling unsupported apps.

Decision constraints:
- If the user wants Jarvis to do something, primary is task unless there is also a separate information question, then primary is mixed.
- Realtime is for answering current information, not for explicit Google/YouTube search commands.
- "Open YouTube/Google/Gmail/etc." means open. It does not mean youtube_search or google_search unless the user says search/find/look up.
- Camera is for analyzing what the user shows, not for opening/closing the webcam.
- Asking what apps/windows are already open is inspect_pc, not open_app.
- Launching an app is open_app.
- "Tell me about X" is not content. Content requires write/draft/compose/create text for the user.
- Directional brightness/volume changes use *_up or *_down; only choose set_* when the user gives a level.
- Never use set_volume or set_brightness unless the user provides a specific number, percentage, or level.
- "increase brightness", "brightness up", and "make screen brighter" must be brightness_up.
- "decrease brightness", "dim the screen", and "lower brightness" must be brightness_down.
- If an action tool does not exist, use unsupported_needs_tool. Never map unknown actions to open.
- Understand typo-heavy short messages by meaning. Short forms like "ss" can mean screenshot when the user asks to take/capture it.
- The query should be the clean target: website name, song title, prompt, app name, search query, command, or PC-inspection topic. For unsupported actions, set query to the requested action.
- If the user asks for multiple actions, include EVERY action in tasks in order with the correct tool and query per task. NEVER drop or merge tasks. The top-level tool/query should match the first task.
- Example: "open youtube and play despacito" needs tasks: [{"tool":"open","query":"youtube"},{"tool":"play","query":"despacito"}]. Do NOT collapse into a single task.
- The JSON labels must agree with the reason. If the reason says inspect_pc, the tool must be inspect_pc.

Mapping examples:
- User asks to open an online service -> primary task, tool open, query the service name.
- User asks to search YouTube for a topic -> primary task, tool youtube_search, query the topic.
- User asks to play a song or video -> primary task, tool play, query the title/topic.
- User asks which apps/windows are already open -> primary task, tool inspect_pc, query open apps/windows.
- User asks to open a desktop application -> primary task, tool open_app, query the app name.
- User asks for an explanation and also asks to open something -> primary mixed, tasks contains the open action.
- User asks to generate or draw a picture -> primary task, tool generate_image, query the image prompt.
- User asks for a screenshot or screen capture -> primary task, tool unsupported_needs_tool, query screenshot."""

    def _user_prompt(self, user_message: str, chat_history: Optional[List[Tuple[str, str]]]) -> str:
        lines = []
        if chat_history:
            lines.append("Recent conversation:")
            for user, assistant in chat_history[-4:]:
                lines.append(f"User: {(user or '')[:300]}")
                lines.append(f"Assistant: {(assistant or '')[:300]}")
            lines.append("")
        lines.append(f"Current user message: {(user_message or '')[:1000]}")
        return "\n".join(lines)

    @staticmethod
    def _parse_json(raw: str) -> dict:
        text = (raw or "").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    pass
        logger.warning("[PROMPT-ROUTER] Could not parse JSON response: %s", text[:200])
        return {}

    @staticmethod
    def _clean_label(value, allowed, default: str) -> str:
        label = str(value or "").strip().lower()
        return label if label in allowed else default

    @classmethod
    def _clean_tasks(cls, value) -> List[Tuple[str, str]]:
        if not isinstance(value, list):
            return []

        tasks = []
        for item in value:
            if not isinstance(item, dict):
                continue
            tool = cls._clean_label(item.get("tool"), TOOL_LABELS, "")
            if not tool:
                continue
            query = str(item.get("query") or "").strip()
            tasks.append((tool, query))
        return tasks

    @staticmethod
    def _clean_confidence(value) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, confidence))
