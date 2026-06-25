import pathlib
import uuid

from typing import List

from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    HTTPException
)

from fastapi.responses import FileResponse

from src.db.models import (
    FileModel,
    WorkflowStateModel,
    ArtifactModel
)

from src.db.repository import DBRepository

from src.workflows.orchestrator import LectureOrchestrator
from src.utils.storage import MinIOStorage
from src.utils.logging import get_logger


logger = get_logger(__name__)


api_router = APIRouter()

repository = DBRepository()
minio_storage = MinIOStorage()


@api_router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    language: str = Form("ru")
):

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="Empty filename"
        )

    allowed_ext = {
        ".mp4",
        ".mkv",
        ".avi",
        ".mov",
        ".webm",
        ".mp3",
        ".wav",
        ".m4a"
    }

    ext = pathlib.Path(file.filename).suffix.lower()

    if ext not in allowed_ext:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format: {ext}"
        )

    file_id = str(uuid.uuid4())
    
    content = await file.read()
    safe_name = f"{file_id}_{pathlib.Path(file.filename).name}"

    try:
        minio_storage.ensure_buckets()
        minio_object_name = minio_storage.upload_artifact_from_bytes(
            data=content,
            filename=safe_name,
            workflow_id="uploads",
            node_id="initial",
            artifact_type="media"
        )
        
        if minio_object_name:
            logger.info(
                "file_uploaded_to_minio",
                file_id=file_id,
                filename=file.filename,
                minio_object=minio_object_name,
                size_bytes=len(content)
            )

            storage_path = f"minio://{minio_object_name}"
        else:
            logger.error(
                "minio_upload_failed",
                file_id=file_id,
                filename=file.filename
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to upload file to storage"
            )
    except Exception as e:
        logger.error(
            "minio_upload_exception",
            file_id=file_id,
            filename=file.filename,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True
        )

        import traceback
        print(f"ERROR:  Upload error for {file_id}: {str(e)}", file=__import__('sys').stderr)
        traceback.print_exc()
        
        raise HTTPException(
            status_code=500,
            detail=f"Upload failed: {str(e)}"
        )

    try:
        logger.info("database_save_starting", file_id=file_id)
        repository.create_file(
            file_id=file_id,
            filename=file.filename,
            original_path=storage_path,
            language=language,
            size_bytes=len(content),
            mime_type=file.content_type or "application/octet-stream"
        )
        logger.info("database_save_completed", file_id=file_id)
    except Exception as e:
        logger.error(
            "database_save_failed",
            file_id=file_id,
            error=str(e),
            exc_info=True
        )
        print(f"ERROR:  Database save error for {file_id}: {str(e)}", file=__import__('sys').stderr)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    try:
        logger.info("workflow_initialization_starting", file_id=file_id)
        orchestrator = LectureOrchestrator()

        workflow_id = orchestrator.init_workflow(
            file_id=file_id
        )
        logger.info("workflow_initialized", file_id=file_id, workflow_id=workflow_id)

        logger.info("workflow_orchestration_starting", workflow_id=workflow_id)
        orchestrator.start_orchestration(
            workflow_id=workflow_id,
            file_id=file_id,
            file_path=storage_path,
            language=language
        )
        logger.info("workflow_orchestration_started", workflow_id=workflow_id)
    except Exception as e:
        logger.error(
            "workflow_initialization_failed",
            file_id=file_id,
            error=str(e),
            exc_info=True
        )
        print(f"ERROR:  Workflow error for {file_id}: {str(e)}", file=__import__('sys').stderr)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Workflow error: {str(e)}")


    return {
        "file_id": file_id,
        "workflow_id": workflow_id
    }



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


@api_router.get("/api/queue/status")
async def get_queue_status():
    """Возвращает статус очереди воркфлоу"""
    orchestrator = LectureOrchestrator()
    
    return {
        "active_workflows": len(orchestrator.active_workflows),
        "max_concurrent": orchestrator.max_concurrent_workflows,
        "queue_size": orchestrator._workflow_queue.qsize(),
        "active_workflow_ids": list(orchestrator.active_workflows)
    }


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
