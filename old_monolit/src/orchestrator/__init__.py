"""
Оркестратор — отдельный сервис для выполнения воркфлоу в Docker-контейнерах.
Читает БД на наличие новых задач, запускает ноды, сохраняет артефакты в MinIO.
"""
from src.orchestrator.service import OrchestratorService
from src.orchestrator.models import OrchestratorConfig

__all__ = ["OrchestratorService", "OrchestratorConfig"]
