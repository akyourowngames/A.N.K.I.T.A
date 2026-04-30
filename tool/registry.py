from __future__ import annotations

from tool.date_time import DateTimeTool
from tool.tavily_search import TavilySearchTool


TIME_TRIGGERS = ("time", "date", "today", "day is it", "current day")
SEARCH_TRIGGERS = ("search", "web", "online", "internet", "latest", "current news", "look up")


class ToolRegistry:
    def __init__(self) -> None:
        self.date_time = DateTimeTool()
        self.tavily_search = TavilySearchTool()

    def context_for(self, user_text: str) -> str:
        lowered = user_text.lower()
        contexts: list[str] = []

        if any(trigger in lowered for trigger in TIME_TRIGGERS):
            try:
                contexts.append(f"[date_time]\n{self.date_time.run()}")
            except Exception as error:
                contexts.append(f"[date_time error]\n{error}")

        if any(trigger in lowered for trigger in SEARCH_TRIGGERS):
            try:
                contexts.append(f"[tavily_search]\n{self.tavily_search.run(user_text)}")
            except Exception as error:
                contexts.append(f"[tavily_search error]\n{error}")

        return "\n\n".join(contexts)
