from generated.logger import get_logger
from generated.scheduler import scheduled

log = get_logger("orchestrator_tasks")


@scheduled(name="cleanup_stale_executions", seconds=15)
async def cleanup_stale_executions() -> None:
    from generated.db.connection import get_session_factory
    from generated.docker_sandbox import DockerSandbox
    from src.engine.launch import cleanup_created_containers
    service = _get_dispatcher()
    workers = getattr(service.container_manager, 'workers', None)
    sandboxes = [sandbox for _, sandbox in workers.items()] if workers else [DockerSandbox()]
    for sandbox in sandboxes:
        try:
            await cleanup_created_containers(get_session_factory(), sandbox)
        except (RuntimeError, OSError, TimeoutError):
            log.warning('host_cleanup_unavailable')


_dispatcher = None


def _get_dispatcher():
    global _dispatcher
    if _dispatcher is None:
        from src.service import OrchestratorServiceImpl
        _dispatcher = OrchestratorServiceImpl()
    return _dispatcher


@scheduled(name="dispatch_pending_executions", seconds=5)
async def dispatch_pending_executions() -> None:
    await _get_dispatcher().dispatch_pending()
