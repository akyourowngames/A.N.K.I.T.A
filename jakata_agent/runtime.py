from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from jakata_agent.camera import CameraSession
from jakata_agent.companion import CompanionStore, ProactiveCompanionEngine
from jakata_agent.config import Settings, load_settings
from jakata_agent.llm import (
    NvidiaChatClient,
    TextCompletionClient,
    build_arg_planner_client,
    build_automation_client,
    build_browser_automation_client,
    build_router_client,
)
from jakata_agent.mandatory_router import build_runtime_mandatory_router
from jakata_agent.memory.manager import MemoryManager
from jakata_agent.plan_validator import PlanValidator
from jakata_agent.router import IntentRouter
from jakata_agent.tasks.engine import TaskCompletionEngine
from jakata_agent.tasks.store import TaskStore
from jakata_agent.tools.browser import register_browser_tools
from jakata_agent.tools.camera import register_camera_tools
from jakata_agent.tools.capabilities import register_capabilities_tool
from jakata_agent.tools.coding_agent import CodingAgentTool, CodingController
from jakata_agent.tools.datetime_tool import DateTimeTool
from jakata_agent.tools.document import register_document_tool
from jakata_agent.tools.external_services import register_external_service_tools
from jakata_agent.tools.image_generation import register_image_generation_tool
from jakata_agent.tools.keyboard import register_input_tools
from jakata_agent.tools.memory_tool import MemoryTool
from jakata_agent.tools.os_agent import OsAgentTool, OsController
from jakata_agent.tools.registry import ToolRegistry
from jakata_agent.tools.screen import register_screen_tools
from jakata_agent.tools.search_web import TavilySearchTool
from jakata_agent.tools.system_control import register_system_tools
from jakata_agent.tools.terminal import register_terminal_tools
from jakata_agent.tools.weather import OpenWeatherTool


@dataclass(slots=True)
class JakataRuntime:
    settings: Settings
    client: NvidiaChatClient
    fast_client: NvidiaChatClient
    automation_client: TextCompletionClient
    tools: ToolRegistry
    memory: MemoryManager
    router: IntentRouter
    automation_router: IntentRouter
    validator: PlanValidator
    task_store: TaskStore
    task_engine: TaskCompletionEngine
    os_controller: OsController
    coding_controller: CodingController
    camera_session: CameraSession
    companion_store: CompanionStore
    companion_engine: ProactiveCompanionEngine
    mandatory_router: Any | None = None


def create_runtime(settings: Settings | None = None) -> JakataRuntime:
    settings = settings or load_settings()
    client = NvidiaChatClient(settings)
    fast_fallbacks = settings.fast_chat_fallback_models or [
        model for model in [settings.primary_model, *settings.fallback_models] if model != settings.fast_chat_model
    ]
    fast_settings = replace(
        settings,
        primary_model=settings.fast_chat_model,
        fallback_models=fast_fallbacks,
        timeout_seconds=settings.fast_chat_timeout_seconds,
        max_retries=1,
    )
    fast_client = NvidiaChatClient(fast_settings)
    router_client = build_router_client(settings, client)
    automation_client = build_automation_client(settings, client)
    browser_automation_client = build_browser_automation_client(settings, automation_client)
    tools = ToolRegistry()
    memory = MemoryManager(
        settings.data_dir,
        settings.session_id,
        settings.api_key,
        settings.base_url,
        settings.embedding_model,
        settings.embedding_timeout_seconds,
    )
    kill_switch_path = settings.data_dir / "control" / "kill.switch"
    register_terminal_tools(tools)
    register_input_tools(tools)
    register_system_tools(tools)
    register_browser_tools(
        tools,
        chrome_path=settings.chrome_path,
        backend=settings.browser_backend,
        user_data_dir=str(settings.data_dir / "playwright_chrome"),
    )
    register_screen_tools(tools, tesseract_cmd=settings.tesseract_cmd)
    camera_session = CameraSession(
        device_index=settings.camera_device_index,
        frame_width=settings.camera_frame_width,
        frame_height=settings.camera_frame_height,
    )
    register_camera_tools(tools, camera_session, client)
    register_image_generation_tool(
        tools,
        api_key=settings.api_key,
        base_url=settings.image_base_url,
        model=settings.image_model,
        output_dir=settings.image_output_dir,
        default_size=settings.image_size,
        infer_url=settings.image_infer_url,
        model_namespace=settings.image_model_namespace,
        timeout_seconds=settings.timeout_seconds,
    )
    search_tool = TavilySearchTool(settings.tavily_api_key)
    register_document_tool(
        tools,
        client=automation_client,
        output_dir=settings.document_output_dir,
        template_dir=settings.document_template_dir,
        workspace_dir=settings.workspace_dir,
        search_tool=search_tool,
    )
    task_store = TaskStore(memory.db_path)
    companion_store = CompanionStore(settings.data_dir / "companion" / "companion.db")
    companion_engine = ProactiveCompanionEngine(
        client=router_client,
        store=companion_store,
        enabled_default=settings.companion_enabled,
        min_interval_seconds=settings.companion_min_interval_seconds,
        max_per_day=settings.companion_max_per_day,
        min_score=settings.companion_min_score,
    )
    os_controller = OsController(
        client=automation_client,
        tools=tools,
        kill_switch_path=str(kill_switch_path),
        browser_client=browser_automation_client,
    )
    tools.register(OsAgentTool(os_controller))
    coding_controller = CodingController(client=automation_client, tools=tools)
    tools.register(CodingAgentTool(coding_controller))
    tools.register(DateTimeTool())
    tools.register(MemoryTool())
    tools.register(search_tool)
    tools.register(OpenWeatherTool(settings.openweather_api_key))
    register_external_service_tools(
        tools,
        data_dir=settings.data_dir,
        google_credentials_path=settings.google_credentials_path,
        google_token_path=settings.google_token_path,
    )
    register_capabilities_tool(tools)
    mandatory_router = build_runtime_mandatory_router(settings, tools, local_embedder=getattr(memory, "embedder", None))
    agent_router_client = build_arg_planner_client(settings, client) if mandatory_router is not None else router_client
    return JakataRuntime(
        settings=settings,
        client=client,
        fast_client=fast_client,
        automation_client=automation_client,
        tools=tools,
        memory=memory,
        router=IntentRouter(agent_router_client),
        automation_router=IntentRouter(automation_client),
        validator=PlanValidator(),
        task_store=task_store,
        task_engine=TaskCompletionEngine(
            client=automation_client,
            router=IntentRouter(automation_client),
            tools=tools,
            validator=PlanValidator(),
            memory=memory,
            task_store=task_store,
            approval_policy=settings.approval_policy,
            workspace_dir=settings.workspace_dir,
            data_dir=settings.data_dir,
        ),
        os_controller=os_controller,
        coding_controller=coding_controller,
        camera_session=camera_session,
        companion_store=companion_store,
        companion_engine=companion_engine,
        mandatory_router=mandatory_router,
    )
