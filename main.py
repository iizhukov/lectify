import uvicorn
import sys
import os

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from configparser import ConfigParser
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from prometheus_fastapi_instrumentator import Instrumentator

from src.db.database import init_sqlalchemy_db
from src.llm.manager import LLMManager
from src.api.routes import api_router
from src.web.routes import web_router
from src.workflows.orchestrator import LectureOrchestrator
from src.utils.logging import setup_logging, get_logger
from src.utils.metrics import get_metrics


config = ConfigParser()

if not os.path.exists("config.cfg"):
    print("❌ Ошибка: файл config.cfg не найден!")
    print("📝 Создайте config.cfg на основе config.cfg.example")
    sys.exit(1)

config.read("config.cfg")

if not config.has_section("OpenAI"):
    print("❌ Ошибка: секция [OpenAI] не найдена в config.cfg")
    sys.exit(1)

if not config.has_option("OpenAI", "API_KEY"):
    print("❌ Ошибка: параметр API_KEY не найден в секции [OpenAI]")
    sys.exit(1)

if not config.has_option("OpenAI", "URL"):
    print("❌ Ошибка: параметр URL не найден в секции [OpenAI]")
    sys.exit(1)

app = FastAPI(title="ИИ Конспектирование")

# Настройка логирования
setup_logging(log_level="INFO", log_file="logs/lectify.log")
logger = get_logger(__name__)

logger.info("application_starting", version="1.0.0")

# Инициализируем БД
init_sqlalchemy_db()
logger.info("database_initialized")

# Создаем менеджер моделей и оркестратор
llm_manager = LLMManager(
    api_key=config["OpenAI"]["API_KEY"],
    base_url=config["OpenAI"]["URL"],
)
orchestrator = LectureOrchestrator(llm_manager)
logger.info("orchestrator_initialized", max_concurrent=orchestrator.max_concurrent_workflows)

# Восстанавливаем прерванные фоновые воркфлоу
orchestrator.resume_interrupted_workflows()

# Настройка Prometheus метрик для FastAPI
Instrumentator().instrument(app).expose(app)

# Эндпоинт для Prometheus метрик
@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Эндпоинт для сбора метрик Prometheus"""
    return generate_latest()

app.include_router(web_router)
app.include_router(api_router)

logger.info("application_ready", host="0.0.0.0", port=5001)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=True)
