import os
import uuid

from typing import List, Dict

from fastapi import APIRouter, HTTPException, UploadFile, File as FastAPIFile
from fastapi.responses import FileResponse, Response

from src.utils.telegram import TelegramClient
from src.db.models import FileModel, WorkflowStateModel, ArtifactModel
from src.db.repository import DBRepository
from src.utils.storage import MinIOStorage
from src.utils.logging import get_logger
from src.utils.metrics import metrics


logger = get_logger(__name__)


api_router = APIRouter()

repository = DBRepository()
minio_storage = MinIOStorage()


@api_router.post(
    "/api/files",
    response_model=FileModel
)
async def upload_file(
    file: UploadFile = FastAPIFile(...),
    language: str = "ru"
):
    file_id = str(uuid.uuid4())
    content = await file.read()
    size_bytes = len(content)

    minio_path = minio_storage.upload_user_file(content, file.filename or "", file_id)

    file_record = repository.create_file(
        file_id=file_id,
        filename=file.filename or "",
        original_path=minio_path or "",
        language=language,
        size_bytes=size_bytes,
        mime_type=file.content_type or "application/octet-stream",
        minio_path=minio_path,
    )

    if minio_path:
        metrics.files_uploaded.inc()
        metrics.file_size_bytes.observe(size_bytes)

    return file_record


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


@api_router.get("/download/files/{file_id}")
async def download_file(file_id: str):
    file = repository.get_file_details(file_id)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    minio_path = file.minio_path or file.original_path
    if not minio_path:
        raise HTTPException(status_code=404, detail="File not found in storage")

    data = minio_storage.get_file_bytes(minio_path)
    if data is None:
        raise HTTPException(status_code=404, detail="File not found in MinIO")

    return Response(
        content=data,
        media_type=file.mime_type,
        headers={"Content-Disposition": f"attachment; filename=\"{file.filename}\""}
    )


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
async def receive_alert(alert_data: Dict):
    from src.config import config

    alerts: List[Dict] = alert_data.get("alerts", [])

    for alert in alerts:
        status = alert.get("status")
        labels: Dict[str, str] = alert.get("labels", {})
        annotations: Dict[str, str] = alert.get("annotations", {})

        logger.warning(
            "alert_received",
            status=status,
            alertname=labels.get("alertname"),
            severity=labels.get("severity"),
            component=labels.get("component"),
            summary=annotations.get("summary"),
            description=annotations.get("description")
        )

    if config.telegram_enabled and config.telegram_bot_token and config.telegram_chat_id:
        try:
            client = TelegramClient(
                bot_token=config.telegram_bot_token,
                chat_id=config.telegram_chat_id,
            )

            await client.send_alerts(alerts)
        except Exception as e:
            import httpx
            err_detail = str(e)
            if isinstance(e, httpx.HTTPStatusError):
                err_detail = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.error("telegram_notification_failed",
                error=err_detail,
                error_type=type(e).__name__,
                bot_configured=bool(config.telegram_bot_token),
                chat_configured=bool(config.telegram_chat_id),
            )

    return {"status": "ok", "received": len(alerts)}
