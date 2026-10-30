from generated.logger import get_logger
from generated.scheduler import scheduled

log = get_logger("orchestrator_tasks")


@scheduled(name="cleanup_stale_executions", minutes=10)
async def cleanup_stale_executions() -> None:
    log.info("cleanup_stale_executions_task_running")
