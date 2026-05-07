# Jarvis NIM Python Assistant

A tiny Python assistant CLI that talks to NVIDIA NIM through the OpenAI-compatible chat completions API.

This project lives at the root and stays separate from `openclaw/`.

It only tells the model about registered local tools. That keeps Jarvis from claiming broad phone, reminder, file, app, or messaging powers it does not actually have.

## Run

Interactive chat:

```powershell
python main.py
```

One-shot message:

```powershell
python main.py "say hello in one sentence"
```

Check env wiring without sending a message:

```powershell
python main.py --check-env
```

List registered tools:

```powershell
python main.py --list-tools
```

Benchmark configured NIM models:

```powershell
python scripts\benchmark_nim_models.py
```

Run the live Jarvis behavior checks:

```powershell
python scripts\verify_jarvis_live.py
```

Discover and benchmark the live NVIDIA model catalog:

```powershell
python scripts\benchmark_nim_models.py --discover --mode stream
```

Memory files are created automatically:

```powershell
memory\user.txt
memory\extracted.txt
memory\transcripts\YYYY-MM-DD.txt
```

## Environment

Required:

- `NVIDIA_API_KEY`
- `NVIDIA_BASE_URL`
- `NVIDIA_MODEL`

Optional:

- `NVIDIA_STREAM`
- `NIM_STREAM_MODE`
- `NIM_SYNTHETIC_CHUNK_CHARS`
- `NIM_SYNTHETIC_CHUNK_DELAY_SECONDS`
- `NVIDIA_TIMEOUT_SECONDS`
- `NVIDIA_MEMORY_MODEL`
- `NIM_RETRY_ATTEMPTS`
- `NIM_RETRY_DELAY_SECONDS`
- `JARVIS_AUTO_TOOLS`
- `JARVIS_SYSTEM_PROMPT_FILE`
- `JARVIS_PERSONA_FILE`
- `JARVIS_TOOL_PROTOCOL_FILE`
- `JARVIS_TOOL_RESULTS_PROMPT_FILE`
- `TEMPERATURE`
- `MAX_TOKENS`
- `TOOL_MAX_ROUNDS`
- `NIM_TOOL_MODE`
- `USER_NAME`
- `AI_NAME`
- `WEATHER_UNITS`
- `WEATHER_TIMEOUT_SECONDS`
- `WEATHER_GEOCODING_BASE_URL`
- `WEATHER_FORECAST_BASE_URL`
- `TIME_API_BASE_URL`
- `TIME_API_ZONE_PARAM`
- `TIME_API_TIMEOUT_SECONDS`
- `JARVIS_MEMORY_DIR`
- `MEMORY_CONTEXT_CHARS`
- `MEMORY_FILE_CHARS`
- `MEMORY_INCLUDE_TRANSCRIPTS`
- `MEMORY_EXTRACT_FROM_CHAT`
- `MEMORY_EXTRACT_BACKGROUND`
- `MEMORY_EXTRACT_MAX_TOKENS`
- `MEMORY_CONTEXT_PROMPT_FILE`
- `JARVIS_MODEL_CATALOG`
- `JARVIS_TERMINAL_SHELL`
- `JARVIS_TERMINAL_TIMEOUT_SECONDS`
- `JARVIS_TERMINAL_MAX_OUTPUT_CHARS`

The assistant does not invent a model if `NVIDIA_MODEL` is missing. The current `.env` decides which NIM model is used.

Model profiles live in `config/nim_models.json`; the benchmark script reads that file.

The benchmark can also discover model IDs directly from NVIDIA's `/models` endpoint and writes the latest live timing report to `config/nim_benchmark_results.json`.

For low latency, keep `NIM_STREAM_MODE=native`. `NIM_RETRY_ATTEMPTS` can stay low for speed or be raised slightly when the provider is returning temporary rate-limit errors.

`JARVIS_AUTO_TOOLS` controls whether Jarvis plans local tool calls before answering. Keep it `true` when you want tools such as `run_terminal` available in chat. Set it to `false` for pure no-tool conversation.

The normal chat prompt lives in `prompts/chat_system.txt`. Jarvis's voice/persona lives in `prompts/persona.txt`. The optional tool-planner protocol lives in `prompts/tool_protocol.txt`. Tool-result answer shaping lives in `prompts/tool_results.txt`.

`NIM_STREAM_MODE` defaults to `native`: Jarvis reads NVIDIA NIM server-sent events and prints tokens as they arrive. Set `NIM_STREAM_MODE=synthetic` only if a provider endpoint is having temporary SSE trouble and you want local chunk printing after a JSON completion.

`NIM_TOOL_MODE` controls the optional auto-tool path. Use `json` for text JSON tool calls or `native` for models/endpoints that support native OpenAI `tool_calls`.

## Tools

Tool definitions live in `tools/tools.json`. The Python files only provide executor functions. To add or remove a tool from the assistant surface, edit the JSON manifest; the chat loop does not need to change.

Current tools:

- `calculate`
- `fetch_url_text`
- `generate_uuid`
- `get_current_datetime`
- `get_file_info`
- `get_pc_status`
- `get_runtime_info`
- `get_system_info`
- `get_weather`
- `hash_text`
- `list_directory`
- `run_terminal`
- `read_text_file`
- `search_text_files`
- `text_stats`
- `list_registered_tools`

`run_terminal` is a manifest-registered local command tool. Its schema lives in `tools/tools.json`; the chat loop does not need to change when the tool is added or removed.

For GUI launch requests, `run_terminal` supports background execution so Jarvis can start a local app without waiting for the app window to close.

For local system facts such as installed Python, Node, npm, file, environment, and test state, Jarvis must use `run_terminal` before answering. For facts about the running Jarvis process itself, Jarvis must use `get_runtime_info`.

## Memory

Jarvis reads durable memory on every turn. You can write stable details directly in `memory/user.txt`; Jarvis stores extracted chat memory in `memory/extracted.txt`.

By default, active memory context includes hand-written memory and extracted facts, while raw transcripts stay archived as text files in `memory/transcripts/`. Set `MEMORY_INCLUDE_TRANSCRIPTS=true` if you want raw transcripts injected too.

The memory system does not use regex matching or keyword routing. It loads bounded context and lets the model use it as durable background.

Memory extraction uses `NVIDIA_MEMORY_MODEL` when set, then `NVIDIA_TOOL_MODEL`, then the chat model.
