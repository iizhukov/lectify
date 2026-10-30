from generated.logger import get_logger
from generated.scheduler import scheduled

log = get_logger("orchestrator_tasks")


@scheduled(name="cleanup_stale_executions", minutes=10)
async def cleanup_stale_executions() -> None:
    from generated.db.connection import get_session_factory
    from generated.docker_sandbox import DockerSandbox
    from src.engine.launch import cleanup_created_containers
    await cleanup_created_containers(get_session_factory(), DockerSandbox())


_dispatcher = None


@scheduled(name="dispatch_pending_executions", seconds=5)
async def dispatch_pending_executions() -> None:
    global _dispatcher
    if _dispatcher is None:
        from src.service import OrchestratorServiceImpl
        _dispatcher = OrchestratorServiceImpl()
    await _dispatcher.dispatch_pending()
