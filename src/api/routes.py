import os

from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src.db.models import FileModel, WorkflowStateModel, ArtifactModel
from src.db.repository import DBRepository
from src.utils.storage import MinIOStorage
from src.utils.logging import get_logger


logger = get_logger(__name__)


api_router = APIRouter()

repository = DBRepository()
minio_storage = MinIOStorage()


@api_router.get(
    "/api/files",
    response_model=List[FileModel]
)
async def get_files():
    return repository.get_all_files()


@api_router.get(
    "/api/files/{file_id}",
    response_model=FileModel
)
async def get_file_details(
    file_id: str
):

    file = repository.get_file_details(file_id)

    if not file:
        raise HTTPException(
            status_code=404,
            detail="File not found"
        )

    return file


@api_router.get(
    "/api/workflows/history",
    response_model=List[WorkflowStateModel]
)
async def get_workflows_history():
    return repository.get_all_workflows()


@api_router.get(
    "/api/workflows/history/{workflow_id}",
    response_model=WorkflowStateModel
)
async def get_workflow_details(
    workflow_id: str
):

    workflow = repository.get_workflow_details(
        workflow_id
    )

    if not workflow:
        raise HTTPException(
            status_code=404,
            detail="Workflow not found"
        )

    return workflow


@api_router.get(
    "/api/artifacts/{artifact_id}",
    response_model=ArtifactModel
)
async def get_artifact(
    artifact_id: str
):

    artifact = repository.get_artifact(
        artifact_id
    )

    if not artifact:
        raise HTTPException(
            status_code=404,
            detail="Artifact not found"
        )

    return artifact


@api_router.get(
    "/download/artifacts/{artifact_id}"
)
async def download_artifact(
    artifact_id: str
):

    artifact = repository.get_artifact(
        artifact_id
    )

    if not artifact:
        raise HTTPException(
            status_code=404,
            detail="Artifact not found"
        )

    if not os.path.exists(artifact.path):
        raise HTTPException(
            status_code=404,
            detail="File deleted"
        )

    return FileResponse(
        artifact.path,
        media_type=artifact.mime_type,
        filename=artifact.name
    )


@api_router.post("/api/alerts/webhook")
async def receive_alert(alert_data: dict):
    """
    Webhook для получения алертов от Alertmanager.
    Отправляет уведомления в Telegram при настроенном боте.
    """
    from src.config import config
    import httpx

    logger = get_logger(__name__)

    alerts = alert_data.get("alerts", [])

    # Логируем полученные алерты
    for alert in alerts:
        status = alert.get("status")
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})

        logger.warning(
            "alert_received",
            status=status,
            alertname=labels.get("alertname"),
            severity=labels.get("severity"),
            component=labels.get("component"),
            summary=annotations.get("summary"),
            description=annotations.get("description")
        )

    # Отправка в Telegram если настроено
    if config.telegram_enabled and config.telegram_bot_token and config.telegram_chat_id:
        try:
            for alert in alerts:
                labels = alert.get("labels", {})
                annotations = alert.get("annotations", {})
                status = alert.get("status", "firing")
                severity = labels.get("severity", "warning")

                emoji = "🚨" if severity == "critical" else "⚠️"
                status_emoji = "🔴" if status == "firing" else "🟢"

                message = f"""{emoji} *Alert: {labels.get('alertname', 'Unknown')}*
{status_emoji} Status: {status.upper()}
📋 Severity: {severity}
📝 {annotations.get('summary', 'No description')}

```
{annotations.get('description', 'No details')}
```"""

                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
                        json={
                            "chat_id": config.telegram_chat_id,
                            "text": message,
                            "parse_mode": "Markdown"
                        },
                        timeout=10
                    )
        except Exception as e:
            logger.error("telegram_notification_failed", error=str(e))

    return {"status": "ok", "received": len(alerts)}
