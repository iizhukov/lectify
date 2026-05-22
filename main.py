import os
import sys
import uvicorn

from fastapi import FastAPI

from src.db.database import init_sqlalchemy_db
from src.llm.manager import LLMManager
from src.api.routes import api_router
from src.web.routes import web_router
from src.workflows.orchestrator import LectureOrchestrator


app = FastAPI(title="ИИ Конспектирование")

# Инициализируем БД
init_sqlalchemy_db()

# Создаем менеджер моделей и оркестратор
llm_manager = LLMManager()
orchestrator = LectureOrchestrator(llm_manager)

# Восстанавливаем прерванные фоновые воркфлоу
orchestrator.resume_interrupted_workflows()

app.include_router(web_router)
app.include_router(api_router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=True)
