import asyncio
import re
import time
import uvicorn
import sys
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_client import generate_latest
from prometheus_fastapi_instrumentator import Instrumentator

from src.config import config
from src.db.database import init_sqlalchemy_db
from src.api import api_router
from src.web.routes import web_router
from src.utils.logging import setup_logging, get_logger
from src.utils.metrics import get_metrics

from src.orchestrator import OrchestratorService, OrchestratorConfig


_UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.IGNORECASE
)
_NUM_ID_RE = re.compile(r'/\d+')


def _normalize_path(path: str) -> str:
    """Нормализует путь для метрик — заменяет UUID и числовые ID на плейсхолдеры."""
    path = _UUID_RE.sub('/{id}', path)
    path = _NUM_ID_RE.sub('/{id}', path)
    return path


class HTTPMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/metrics", "/health", "/ready"):
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        m = get_metrics()
        m.http_requests_total.labels(
            method=request.method,
            path=_normalize_path(request.url.path),
            status=response.status_code,
        ).inc()
        m.http_request_duration.labels(
            method=request.method,
            path=_normalize_path(request.url.path),
        ).observe(duration)

        return response


_orchestrator_service: OrchestratorService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan events для startup/shutdown"""
    global _orchestrator_service

    if config.orchestrator_enabled:
        orch_config = OrchestratorConfig(
            enabled=True,
            max_concurrent_nodes=config.orchestrator_max_concurrent_nodes,
            poll_interval_seconds=config.orchestrator_poll_interval_seconds,
            node_timeout_seconds=config.orchestrator_node_timeout_seconds,
            auto_retry_failed_nodes=config.orchestrator_auto_retry_failed_nodes,
            max_node_retries=config.orchestrator_max_node_retries,
        )
        _orchestrator_service = OrchestratorService(orch_config)
        asyncio.create_task(_orchestrator_service.start())
        logger = get_logger(__name__)
        logger.info("new_orchestrator_service_started")
        print("OK: Orchestrator service started", file=sys.stderr)

    yield

    logger = get_logger(__name__)
    if _orchestrator_service:
        await _orchestrator_service.stop()
        logger.info("orchestrator_service_stopped")

    logger.info("application_shutdown_initiated")


app = FastAPI(title="ИИ Конспектирование", lifespan=lifespan)
app.add_middleware(HTTPMetricsMiddleware)

STATIC_PATH = pathlib.Path(__file__).parent / "resources" / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_PATH)), name="static")

setup_logging()
logger = get_logger(__name__)


def setup_exception_handler():
    """Настройка вывода исключений в консоль"""
    old_excepthook = sys.excepthook

    def new_excepthook(type, value, traceback):
        print(f"ERROR:  UNCAUGHT EXCEPTION: {type.__name__}: {value}", file=sys.stderr)
        old_excepthook(type, value, traceback)

    sys.excepthook = new_excepthook


setup_exception_handler()
logger.info("application_starting", version="2.0.0")
print("🚀 Starting application...", file=sys.stderr)

try:
    init_sqlalchemy_db()
    logger.info("database_initialized")
    print("OK: Database initialized", file=sys.stderr)
except Exception as e:
    logger.error("database_initialization_failed", error=str(e), exc_info=True)
    print(f"ERROR:  Database initialization failed: {str(e)}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    from src.plugins.registry import scan_and_register_plugins
    scan_and_register_plugins()
    logger.info("plugins_scanned")
    print("OK: Plugins scanned", file=sys.stderr)

    if config.plugins_build_on_startup:
        print("Building plugin Docker images...", file=sys.stderr)
        try:
            from src.docker.client import DockerClient
            from src.plugins.registry import PluginRegistry
            registry = PluginRegistry()
            registry.scan_plugins_folder()
            plugin_ids = list(registry.get_all_plugins().keys())
            if plugin_ids:
                client = DockerClient()
                for plugin_id in plugin_ids:
                    success = client.build_plugin_image(plugin_id)
                    if success:
                        print(f"  OK: lectify-plugin-{plugin_id}", file=sys.stderr)
                    else:
                        print(f"  FAIL: lectify-plugin-{plugin_id}", file=sys.stderr)
        except Exception as e:
            print(f"WARNING: Plugin build failed: {str(e)}", file=sys.stderr)
            import traceback
            traceback.print_exc()

except Exception as e:
    logger.error("plugin_system_init_failed", error=str(e), exc_info=True)
    print(f"WARNING:  Plugin system init warning: {str(e)}", file=sys.stderr)
    import traceback
    traceback.print_exc()


# Prometheus metrics
Instrumentator().instrument(app).expose(app)


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Эндпоинт для сбора метрик Prometheus"""
    return generate_latest()


app.include_router(web_router)
app.include_router(api_router)


logger.info("application_ready", host="0.0.0.0", port=5001)
print("OK: Application ready at http://0.0.0.0:5001", file=sys.stderr)


if __name__ == "__main__":
    from src.utils.logging import ACCESS_LOG_CONFIG
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5001,
        reload=True,
        log_config=ACCESS_LOG_CONFIG,
    )
