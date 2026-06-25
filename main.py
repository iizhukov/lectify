import asyncio
import uvicorn
import sys
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from prometheus_fastapi_instrumentator import Instrumentator

from src.config import config
from src.db.database import init_sqlalchemy_db
from src.llm.manager import LLMManager
from src.api import api_router
from src.api.routes import api_router as legacy_router
from src.web.routes import web_router
from src.workflows.orchestrator import LectureOrchestrator
from src.utils.logging import setup_logging, get_logger
from src.utils.metrics import get_metrics

from src.orchestrator import OrchestratorService, OrchestratorConfig


_orchestrator_service: OrchestratorService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan events для startup/shutdown"""
    global _orchestrator_service

    if config.orchestrator_enabled:
        orch_config = OrchestratorConfig(
            enabled=True,
            max_concurrent_workflows=config.orchestrator_max_concurrent_workflows,
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

# Mount static files
import pathlib
STATIC_PATH = pathlib.Path(__file__).parent / "resources" / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_PATH)), name="static")

# Настройка логирования
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
    from src.workflows.migration import run_all_migrations

    # Scan and register plugins from filesystem
    scan_and_register_plugins()
    logger.info("plugins_scanned")
    print("OK: Plugins scanned", file=sys.stderr)

    run_all_migrations()
    logger.info("migrations_completed")
    print("OK: Migrations completed", file=sys.stderr)

except Exception as e:
    logger.error("plugin_system_init_failed", error=str(e), exc_info=True)
    print(f"WARNING:  Plugin system init warning: {str(e)}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    # Don't exit - allow app to start without new features


# =============================================
# LLM MANAGER + ORCHESTRATOR
# =============================================

try:
    llm_manager = LLMManager(
        api_key=config.openai_api_key,
        base_url=config.openai_api_url,
    )
    orchestrator = LectureOrchestrator(llm_manager)
    logger.info("orchestrator_initialized", max_concurrent=orchestrator.max_concurrent_workflows)
    print(f"OK: Orchestrator initialized", file=sys.stderr)

    orchestrator.resume_interrupted_workflows()
    print("OK: Recovered interrupted workflows", file=sys.stderr)
except Exception as e:
    logger.error("orchestrator_initialization_failed", error=str(e), exc_info=True)
    print(f"ERROR:  Orchestrator initialization failed: {str(e)}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)


# =============================================
# FASTAPI SETUP
# =============================================

# Prometheus metrics
Instrumentator().instrument(app).expose(app)


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Эндпоинт для сбора метрик Prometheus"""
    return generate_latest()


# Include routers
app.include_router(web_router)
app.include_router(api_router)  # New workflow API
app.include_router(legacy_router)  # Legacy API


logger.info("application_ready", host="0.0.0.0", port=5001)
print("OK: Application ready at http://0.0.0.0:5001", file=sys.stderr)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=True)