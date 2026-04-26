from __future__ import annotations

from dataclasses import dataclass

from jakata_agent.camera import CameraSession
from jakata_agent.config import Settings, load_settings
from jakata_agent.llm import (
    NvidiaChatClient,
    TextCompletionClient,
    build_automation_client,
    build_browser_automation_client,
    build_router_client,
)
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


def create_runtime(settings: Settings | None = None) -> JakataRuntime:
    settings = settings or load_settings()
    client = NvidiaChatClient(settings)
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
    task_store = TaskStore(memory.db_path)
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
    tools.register(TavilySearchTool(settings.tavily_api_key))
    tools.register(OpenWeatherTool(settings.openweather_api_key))
    register_external_service_tools(
        tools,
        data_dir=settings.data_dir,
        google_credentials_path=settings.google_credentials_path,
        google_token_path=settings.google_token_path,
    )
    register_capabilities_tool(tools)
    return JakataRuntime(
        settings=settings,
        client=client,
        automation_client=automation_client,
        tools=tools,
        memory=memory,
        router=IntentRouter(router_client),
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
    )
