from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def case(case_id: str, prompt: str, tools: list[str], difficulty: str, category: str, notes: str) -> dict[str, object]:
    return {
        "id": case_id,
        "prompt": prompt,
        "expected_tools": tools,
        "difficulty": difficulty,
        "category": category,
        "notes": notes,
    }


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> int:
    seen: set[str] = set()
    unique: list[dict[str, object]] = []
    for row in rows:
        key = str(row["prompt"]).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in unique) + "\n", encoding="utf-8")
    return len(unique)


SINGLE_TOOL_PROMPTS: dict[str, list[str]] = {
    "shell": [
        "run git status --short in the terminal",
        "execute python --version and show the output",
        "install the project requirements from the command line",
        "run pytest for the router tests",
        "use powershell to list running python processes",
        "run npm install in the frontend folder",
        "execute a curl request to check the local API health",
    ],
    "read_file": [
        "read README.md and summarize the setup section",
        "open the contents of pyproject.toml in chat",
        "quote the first 20 lines of jakata_agent/router.py",
        "inspect the config file and tell me the router settings",
        "read prompts/router/planner.md",
        "show me what is inside requirements.txt",
        "read the latest eval report file",
    ],
    "list_dir": [
        "list the files in the frontend folder",
        "show me what is inside jakata_agent/tools",
        "list directories under data",
        "show the project root files",
        "list generated reports",
        "show everything in prompts",
        "list my Downloads folder",
    ],
    "search_files": [
        "search project files for create_runtime",
        "find the file named router.py",
        "search my computer for invoice PDFs",
        "look through local files for the API key note",
        "find the screenshot I took yesterday",
        "search workspace for TODO comments",
        "find my resume file",
    ],
    "write_file": [
        "write a short note to data/generated/router-note.txt",
        "save this idea as a local text file",
        "append this reminder to my scratchpad",
        "create a simple markdown checklist file",
        "overwrite the temporary test note with hello router",
        "make a local todo file",
        "save these bullet points to notes/router.txt",
    ],
    "open_path": [
        "open README.md in the default app",
        "open the generated reports folder",
        "open https://example.com in the default browser",
        "open the latest PDF report",
        "launch the image file I just generated",
        "open my Downloads directory",
        "open the frontend index.html file",
    ],
    "keyboard": [
        "type hello world into the focused window",
        "press ctrl c",
        "hit alt tab once",
        "send enter in the active app",
        "type this text into notepad",
        "press escape",
        "use ctrl s in the current window",
    ],
    "clipboard": [
        "copy this text to the clipboard",
        "read what is currently copied",
        "put the meeting link on my clipboard",
        "paste the clipboard text into the active app",
        "stage this paragraph for pasting",
        "clear and replace my clipboard with hello",
        "what did I copy last",
    ],
    "window": [
        "focus the Chrome window",
        "minimize the active window",
        "maximize notepad",
        "list all open windows",
        "center the current window",
        "close the Calculator window",
        "restore the VS Code window",
    ],
    "mouse": [
        "click the center of the screen",
        "move the mouse to 500 400",
        "scroll down a little",
        "double click the current item",
        "drag from the left side to the right side",
        "show me the cursor position",
        "right click here",
    ],
    "system": [
        "open me notepad",
        "launch spotify",
        "turn the volume down",
        "open bluetooth settings",
        "show my PC status",
        "lower the screen brightness",
        "lock this computer",
    ],
    "browser": [
        "open google.com in Chrome",
        "inspect the current browser page title",
        "refresh the active Chrome tab",
        "search YouTube for lofi beats",
        "close the current browser tab",
        "go back in the browser",
        "pause the video in Chrome",
    ],
    "screen": [
        "take a screenshot",
        "capture the current screen",
        "grab a screenshot of this window",
        "show me what is on screen",
        "capture the top left region",
        "save a screen snapshot",
        "observe the desktop visually",
    ],
    "ocr": [
        "read the text on my screen",
        "extract text from the current screenshot",
        "OCR the active window",
        "what does the error dialog say",
        "read the visible page text",
        "pull text from this image on screen",
        "scan the screen for UI labels",
    ],
    "camera": [
        "check the webcam view",
        "describe what the camera sees",
        "take a quick webcam snapshot",
        "is my camera working",
        "look through the laptop camera",
        "capture from the local webcam",
        "what is in front of the camera",
    ],
    "image_generation": [
        "generate an image of a futuristic coffee cup",
        "make a pixel art robot image",
        "create a banner image for my project",
        "generate a clean wallpaper",
        "make an illustration of a calm workspace",
        "create a transparent icon of a lightning bolt",
        "generate a product mockup image",
    ],
    "document": [
        "create a meeting agenda document",
        "make a one page project update doc",
        "generate a PDF packing checklist",
        "write a clean monthly goals document",
        "draft a resume summary document",
        "make a comparison table document",
        "create a client call notes template",
    ],
    "os_agent": [
        "open Chrome, search YouTube for lofi music, play the first result, and verify playback starts",
        "use the desktop to log into the dashboard and confirm the reports page loads",
        "complete this browser workflow with retries and proof",
        "navigate the site, fill the form, submit it, and verify the success message",
        "open the app, change the setting, and confirm it stayed changed",
        "use a browser workflow to find the first video result and play it",
        "recover from any popups while opening the requested website",
    ],
    "coding_agent": [
        "fix the failing router tests in this repo",
        "implement the new settings page and run tests",
        "refactor the document tool and verify it",
        "debug why the frontend build fails",
        "add unit tests for the parser",
        "build a small demo app and open it",
        "inspect the codebase and patch the routing bug",
    ],
    "datetime": [
        "what time is it right now",
        "what is today's date",
        "tell me the UTC time",
        "is it Monday today",
        "show local and UTC date time",
        "what day is tomorrow",
        "give me the current timestamp",
    ],
    "memory": [
        "what do you remember about my study preferences",
        "search your memory for my profile facts",
        "recall what I said about router latency",
        "find archived chat context about NVIDIA",
        "look up my saved preferences",
        "what personal facts do you know about me",
        "search my knowledge files for assistant OS notes",
    ],
    "search_web": [
        "look up python async best practices",
        "search the web for latest AI news",
        "find cafes near me",
        "check current GPU prices online",
        "latest NVIDIA news today",
        "browse the official FastAPI docs",
        "find current Bitcoin price",
    ],
    "weather": [
        "what is the weather in Bangalore tomorrow",
        "weather",
        "wether in mumbai tmrw",
        "will it rain in Delhi today",
        "go check the weather outside",
        "forecast for Pune this weekend",
        "temperature in Chennai right now",
    ],
    "external_services_status": [
        "check Google Workspace connection status",
        "are Calendar and Gmail connected",
        "show external services health",
        "check OAuth status for Google integrations",
        "is Gmail sync working",
        "verify calendar integration health",
        "show Google Workspace service status",
    ],
    "google_workspace_connect": [
        "start Google Workspace OAuth setup",
        "connect my Gmail account",
        "authorize Google Calendar access",
        "begin Calendar and Gmail setup",
        "launch Google OAuth for workspace tools",
        "reconnect Google Workspace",
        "set up calendar integration",
    ],
    "calendar_today": [
        "what meetings do I have today",
        "check my real calendar events for today",
        "show today's appointments",
        "summarize my calendar for today",
        "do I have any events today",
        "list today's meetings",
        "what is on my schedule today",
    ],
    "calendar_upcoming": [
        "what meetings do I have this week",
        "show upcoming calendar events",
        "check appointments for the next three days",
        "what is on my calendar tomorrow",
        "summarize my upcoming schedule",
        "list calendar events for next week",
        "show my future meetings",
    ],
    "gmail_unread": [
        "show my unread Gmail messages",
        "check unread email metadata",
        "do I have new Gmail messages",
        "summarize unread Gmail",
        "list unread messages",
        "check my inbox for unread mail",
        "what unread emails came in",
    ],
    "gmail_search": [
        "search Gmail for invoices",
        "find email from Rahul about the meeting",
        "look through Gmail for flight tickets",
        "search my mail for password reset",
        "find messages about router bug",
        "search Gmail for receipts",
        "look up emails from OpenAI",
    ],
    "gmail_create_draft": [
        "draft an email to test@example.com about the router update",
        "create a Gmail draft for my manager",
        "write an email draft to the team",
        "make a draft reply saying I will join late",
        "draft a follow up email for the client",
        "create a Gmail draft with subject project status",
        "prepare an email draft but do not send it",
    ],
    "capabilities": [
        "what can you do",
        "which tools are connected",
        "show the tool catalog",
        "list your capabilities",
        "what integrations are available",
        "tell me the live tool inventory",
        "what JAKATA tools can you use",
    ],
}


MULTI_REAL: list[tuple[str, list[str], str]] = [
    ("search latest AI news and make a brief", ["search_web", "document"], "web_document"),
    ("find me cafes near me and put them in a doc", ["search_web", "document"], "web_document"),
    ("what's the weather in Delhi and make a packing list", ["weather", "document"], "weather_document"),
    ("write a summary of today's NVIDIA news", ["search_web", "document"], "web_document"),
    ("search my notes about the router and turn them into a summary doc", ["memory", "document"], "memory_document"),
    ("find the PDF I edited yesterday and open it", ["search_files", "open_path"], "file_open"),
    ("read README.md and create a setup checklist document", ["read_file", "document"], "file_document"),
    ("list the eval reports and open the latest one", ["list_dir", "open_path"], "file_open"),
    ("search project files for router and make a coverage report", ["search_files", "document"], "file_document"),
    ("look up GPU prices online and save a compact table", ["search_web", "document"], "web_document"),
    ("check Mumbai weather and create a commute checklist", ["weather", "document"], "weather_document"),
    ("generate an image and open it when done", ["image_generation", "open_path"], "image_open"),
    ("check today's calendar and draft a follow-up email", ["calendar_today", "gmail_create_draft"], "calendar_gmail"),
    ("search Gmail for invoices and create a summary doc", ["gmail_search", "document"], "gmail_document"),
    ("check unread Gmail and today's calendar", ["gmail_unread", "calendar_today"], "workspace"),
    ("open Chrome and inspect the page title", ["browser"], "browser"),
    ("take a screenshot and read the visible text", ["screen", "ocr"], "screen_ocr"),
    ("open notepad and type my meeting notes", ["system", "keyboard"], "desktop"),
    ("copy this paragraph to clipboard and paste it into the active app", ["clipboard", "keyboard"], "clipboard_keyboard"),
    ("focus Chrome and click the first visible button", ["window", "mouse"], "desktop"),
    ("run tests and fix the code if they fail", ["coding_agent"], "coding"),
    ("use the browser to search, open the first result, and verify it loaded", ["os_agent"], "os_workflow"),
]


HARD_MULTI: list[tuple[str, list[str], str]] = [
    ("yo opne notpad and type the rough idea", ["system", "keyboard"], "typo_desktop"),
    ("serch web fr gpu prices n make comprsn doc", ["search_web", "document"], "typo_web_document"),
    ("wthr delhi tomrw packng list", ["weather", "document"], "typo_weather_document"),
    ("dig up my router notes and make them readable", ["memory", "document"], "memory_document"),
    ("find local invoices, then build a tax checklist", ["search_files", "document"], "file_document"),
    ("weather in Goa, nearby cafes, and a travel prep doc", ["weather", "search_web", "document"], "compound"),
    ("open downloads and search for invoice PDFs", ["system", "search_files"], "desktop_search"),
    ("browse latest AI papers, find my related notes, make synthesis doc", ["search_web", "memory", "document"], "compound"),
    ("check Mumbai weather, find indoor activities nearby, make weekend plan", ["weather", "search_web", "document"], "compound"),
    ("open VS Code and look up FastAPI websocket docs", ["system", "search_web"], "compound"),
    ("find latest OpenAI pricing and build a cost comparison sheet", ["search_web", "document"], "web_document"),
    ("check Chennai humidity and write a packing note", ["weather", "document"], "weather_document"),
    ("search web for nearby laptop repair and open maps app", ["search_web", "system"], "compound"),
    ("find my old benchmark cases and make a coverage report", ["search_files", "document"], "file_document"),
    ("open notepad and check the weather for tomorrow", ["system", "weather"], "compound"),
    ("look up passport rules and create a documents checklist", ["search_web", "document"], "web_document"),
    ("search my transcripts for deadlines and create a clean summary", ["memory", "document"], "memory_document"),
    ("check weather in Manali and latest road closure news", ["weather", "search_web"], "compound"),
    ("screen text looks tiny, capture it and OCR it", ["screen", "ocr"], "screen_ocr"),
    ("what tools do you have and are Google services connected", ["capabilities", "external_services_status"], "capabilities_status"),
]


def realistic_cases() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for tool, prompts in SINGLE_TOOL_PROMPTS.items():
        for index, prompt in enumerate(prompts[:5], start=1):
            rows.append(case(f"real_{tool}_{index:03d}", prompt, [tool], "simple", tool, "Single-tool realistic assistant OS prompt."))
    for index, (prompt, tools, category) in enumerate(MULTI_REAL, start=1):
        rows.append(case(f"real_multi_{index:03d}", prompt, tools, "medium", category, "Multi-tool realistic assistant OS prompt."))

    topics = ["noise cancelling headphones", "AI coding agents", "budget laptops", "cloud GPU providers", "nearby cafes", "electric scooters", "Python async practices", "latest NVIDIA news", "home office chairs", "React performance tips", "wireless earbuds", "best monitors for coding", "AI image tools", "current laptop deals", "standing desks"]
    for index, topic in enumerate(topics, start=1):
        rows.append(case(f"real_web_doc_extra_{index:03d}", f"research {topic} online and create a short comparison doc", ["search_web", "document"], "medium", "web_document", "Extra web plus document coverage."))
    places = ["Delhi", "Mumbai", "Bangalore", "Pune", "Chennai", "Goa", "Jaipur", "Kolkata", "Hyderabad", "Shimla"]
    for index, place in enumerate(places, start=1):
        rows.append(case(f"real_weather_doc_extra_{index:03d}", f"check the weather in {place} and make a packing checklist", ["weather", "document"], "medium", "weather_document", "Extra weather plus document coverage."))
    return rows


def hard_cases() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for tool, prompts in SINGLE_TOOL_PROMPTS.items():
        for index, prompt in enumerate(prompts[2:7], start=1):
            hard_prompt = prompt
            if index % 2 == 0:
                hard_prompt = f"quickly, {prompt}, keep it tight"
            if index % 3 == 0:
                hard_prompt = f"when you get a sec can you {prompt}"
            rows.append(case(f"hard_{tool}_{index:03d}", hard_prompt, [tool], "hard", tool, "Hard single-tool prompt with casual wrapping."))
    for index, (prompt, tools, category) in enumerate(HARD_MULTI, start=1):
        rows.append(case(f"hard_multi_seed_{index:03d}", prompt, tools, "hard", category, "Seeded complex multi-tool prompt."))

    web_topics = ["wireless earbuds", "AI note apps", "current GPU prices", "passport appointment rules", "Windows ARM laptops", "tax deadline updates", "creator laptop reviews", "vector databases", "startup CRM tools", "travel insurance India", "mechanical keyboards", "latest Android phones", "cloud hosting prices", "cybersecurity news", "stable diffusion tools"]
    for index, topic in enumerate(web_topics, start=1):
        rows.append(case(f"hard_web_doc_{index:03d}", f"can you check current web info on {topic}, then save a crisp table doc", ["search_web", "document"], "hard", "web_document", "Intentionally hard web plus document prompt."))

    memory_topics = ["archived meeting notes", "remembered router decisions", "saved prompt ideas in memory", "knowledge notes about studying", "archived client context", "personal book highlights", "stored API preferences", "assistant OS knowledge notes"]
    for index, topic in enumerate(memory_topics, start=1):
        rows.append(case(f"hard_memory_doc_{index:03d}", f"search your memory for my {topic} and turn useful parts into a clean brief", ["memory", "document"], "hard", "memory_document", "Memory retrieval plus document generation."))

    file_topics = ["router logs", "downloaded invoices", "college note files", "fitness journal files", "bug report files", "deployment notes in the workspace", "budget spreadsheets", "travel draft files"]
    for index, topic in enumerate(file_topics, start=1):
        rows.append(case(f"hard_file_doc_{index:03d}", f"search local files for my {topic} and turn useful parts into a clean brief", ["search_files", "document"], "hard", "file_document", "Local file search plus document generation."))

    places = ["Delhi", "Mumbai", "Bangalore", "Goa", "Pune", "Chennai", "Jaipur", "Kolkata", "Hyderabad", "Manali", "Shimla", "Kochi", "Lucknow", "Ahmedabad", "Surat"]
    for index, place in enumerate(places, start=1):
        rows.append(case(f"hard_weather_doc_{index:03d}", f"{place} tomorrow morning, clothes and commute checklist please", ["weather", "document"], "hard", "weather_document", "Weather plus generated list."))

    vague = [
        ("find it", ["search_files"]),
        ("look that up online", ["search_web"]),
        ("outside?", ["weather"]),
        ("pull it up", ["system"]),
        ("make it a doc", ["document"]),
        ("latest on that", ["search_web"]),
        ("where did I save it", ["search_files"]),
        ("open that thing", ["open_path"]),
        ("is it raining", ["weather"]),
        ("my notes pls", ["memory"]),
        ("tools?", ["capabilities"]),
        ("calendar today?", ["calendar_today"]),
        ("mail unread?", ["gmail_unread"]),
        ("camera check", ["camera"]),
        ("screen text?", ["ocr"]),
    ]
    for index, (prompt, tools) in enumerate(vague, start=1):
        rows.append(case(f"hard_vague_{index:03d}", prompt, tools, "hard", "vague", "Short vague prompt."))
    return rows


def main() -> int:
    real_count = write_jsonl(ROOT / "real_cases.jsonl", realistic_cases())
    hard_count = write_jsonl(ROOT / "hard_cases.jsonl", hard_cases())
    print(json.dumps({"real_cases": real_count, "hard_cases": hard_count}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
