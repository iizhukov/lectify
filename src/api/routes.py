import os
import pathlib
import uuid

from typing import List
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse

from src.db.repository import DBRepository
from src.db.models import FileModel, WorkflowStateModel
from src.workflows.registry import WORKFLOW_REGISTRY
from src.workflows.orchestrator import LectureOrchestrator


api_router = APIRouter()
repository = DBRepository()


@api_router.get("/api/workflows/history", response_model=List[WorkflowStateModel])
async def get_workflows_history():
    """Возвращает историю запусков всех воркфлоу в системе"""
    return repository.get_all_workflows()


@api_router.get("/api/workflows/history/{workflow_id}", response_model=WorkflowStateModel)
async def get_workflow_instance_details(workflow_id: str):
    """Детали конкретного запуска воркфлоу по его ID"""
    wf = repository.get_workflow_details(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Запуск воркфлоу не найден")
    return wf


@api_router.post("/upload")
async def upload(file: UploadFile = File(...), language: str = Form("ru")):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Пустое имя файла")

    allowed_ext = {'.mp3', '.m4a', '.wav', '.ogg', '.flac', '.aac', '.opus', '.wma'}
    file_ext = pathlib.Path(file.filename).suffix.lower()
    if file_ext not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"Формат {file_ext} не поддерживается")

    os.makedirs("data", exist_ok=True)
    
    file_id = str(uuid.uuid4())
    safe_name = f"{file_id}_{pathlib.Path(file.filename).name}"
    file_path = f"data/{safe_name}"
    
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)

    # Получаем инстанс синглтона оркестратора
    orchestrator = LectureOrchestrator()
    orchestrator.init_workflow(file_id, file.filename, language)
    orchestrator.start_orchestration(file_id, file_path, language)

    return {"file_id": file_id}


@api_router.get("/api/files", response_model=List[FileModel])
async def get_files():
    return repository.get_all_files()


@api_router.get("/api/files/{file_id}", response_model=FileModel)
async def get_file_details(file_id: str):
    file_details = repository.get_file_details(file_id)
    if not file_details:
        raise HTTPException(status_code=404, detail="Лекция не найдена")
    return file_details


@api_router.get("/api/workflows")
async def get_workflows():
    workflows_data = []
    for wf_id, wf in WORKFLOW_REGISTRY.items():
        workflows_data.append({
            "id": wf_id,
            "name": wf.name,
            "nodes": [
                {
                    "node_id": node.node_id, 
                    "node_name": node.name, 
                    # Для совместимости с UI генерируем зависимости на лету из графа (или пишем пустой список, если корень)
                    "dependencies": [p.node_id for p in wf.all_nodes if node in p.children]
                } 
                for node in wf.all_nodes
            ]
        })
    return workflows_data


@api_router.get("/download/{file_id}/{ext}")
async def download_artifact(file_id: str, ext: str):
    node_mapping = {
        "txt": "speech_to_text",
        "md": "text_to_md",
        "tex": "text_to_latex",
        "pdf": "latex_to_pdf"
    }
    
    node_id = node_mapping.get(ext)
    if not node_id:
        raise HTTPException(status_code=400, detail="Неверное расширение")
        
    file_details = repository.get_file_details(file_id)
    if not file_details:
        raise HTTPException(status_code=404, detail="Файл не найден")
        
    target_node = next((n for n in file_details.nodes if n.node_id == node_id), None)
    if not target_node or not target_node.artifact_path:
        raise HTTPException(status_code=404, detail="Артефакт еще не готов")
        
    path = target_node.artifact_path
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Файл удален или отсутствует на сервере")
        
    return FileResponse(path, media_type="application/octet-stream", filename=pathlib.Path(path).name)
