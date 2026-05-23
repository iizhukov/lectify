import os
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


api_router = APIRouter()

repository = DBRepository()


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

    os.makedirs("data/uploads", exist_ok=True)

    file_id = str(uuid.uuid4())

    safe_name = f"{file_id}_{pathlib.Path(file.filename).name}"

    path = f"data/uploads/{safe_name}"

    content = await file.read()

    with open(path, "wb") as f:
        f.write(content)

    repository.create_file(
        file_id=file_id,
        filename=file.filename,
        original_path=path,
        language=language,
        size_bytes=len(content),
        mime_type=file.content_type or "application/octet-stream"
    )

    orchestrator = LectureOrchestrator()

    workflow_id = orchestrator.init_workflow(
        file_id=file_id
    )

    orchestrator.start_orchestration(
        workflow_id=workflow_id,
        file_id=file_id,
        file_path=path,
        language=language
    )

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
    Webhook для получения алертов от Alertmanager
    """
    from src.utils.logging import get_logger
    
    logger = get_logger(__name__)
    
    # Логируем полученные алерты
    for alert in alert_data.get("alerts", []):
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
    
    return {"status": "ok", "received": len(alert_data.get("alerts", []))}
