from __future__ import annotations

from jakata_agent.runtime import create_runtime
from jakata_agent.tasks.daemon import TaskDaemon
from jakata_agent.tasks.orchestrator import TaskOrchestrator


def main() -> None:
    runtime = create_runtime()
    orchestrator = TaskOrchestrator(
        client=runtime.automation_client,
        router=runtime.automation_router,
        tools=runtime.tools,
        validator=runtime.validator,
        memory=runtime.memory,
        task_store=runtime.task_store,
    )
    daemon = TaskDaemon(
        store=runtime.task_store,
        orchestrator=orchestrator,
        pid_file=runtime.daemon.pid_file,
        kill_switch=runtime.daemon.kill_switch,
    )
    daemon.run_forever()


if __name__ == "__main__":
    main()
