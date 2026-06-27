import uuid
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Header, Query
from pydantic import BaseModel

from src.db.models import WorkflowTemplateModel, ExecutionModel, ExecutionNodeModel
from src.db.repository import WorkflowTemplateRepository, ExecutionRepository, ExecutionNodeRepository
from src.orchestrator.logs import NodeLogManager

router = APIRouter(prefix="/api/workflows", tags=["workflows"])
repo = WorkflowTemplateRepository()
exec_repo = ExecutionRepository()
node_repo = ExecutionNodeRepository()


class ExecuteWorkflowRequest(BaseModel):
    file_id: str
    file_path: str
    language: str = "ru"


class WorkflowCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    graph: dict = {}
    is_public: bool = False


@router.get("", response_model=List[WorkflowTemplateModel])
async def list_workflows(
    user_id: Optional[str] = Query(None),
    authorization: str = Header(None),
):
    if user_id:
        return repo.get_by_user(user_id)
    return repo.get_public()


@router.post("", response_model=WorkflowTemplateModel)
async def create_workflow(req: WorkflowCreateRequest, authorization: str = Header(None)):
    return repo.create({
        "id": str(uuid.uuid4()),
        "user_id": None,
        "name": req.name,
        "description": req.description,
        "graph": req.graph,
        "is_public": req.is_public,
    })


@router.get("/executions", response_model=List[ExecutionModel])
async def list_executions(
    status: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    authorization: str = Header(None),
):
    if user_id:
        executions = exec_repo.get_by_user(user_id)
        if status:
            executions = [e for e in executions if e.status == status]
        return executions

    from src.db.entity import DBExecution
    from src.db.repository.execution import _execution_to_model
    with exec_repo.session() as s:
        q = s.query(DBExecution)
        if status:
            q = q.filter(DBExecution.status == status)
        rows = q.order_by(DBExecution.created_at.desc()).all()
        return [_execution_to_model(e) for e in rows]


@router.get("/executions/{execution_id}", response_model=ExecutionModel)
async def get_execution(execution_id: str):
    execution = exec_repo.get(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


@router.get("/executions/{execution_id}/nodes", response_model=List[ExecutionNodeModel])
async def get_execution_nodes(execution_id: str):
    return node_repo.get_by_execution(execution_id)


@router.get("/executions/{execution_id}/artifacts")
async def get_execution_artifacts(execution_id: str):
    from src.utils.storage import get_storage
    from src.db.repository.workflow import WorkflowRepository
    storage = get_storage()
    file_repo = WorkflowRepository()

    execution = exec_repo.get(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    workflow_id = execution_id
    result = []

    # Original user file first
    if execution.file_id:
        db_file = file_repo.get_file(execution.file_id)
        if db_file and db_file.minio_path:
            url = storage.get_artifact_url(db_file.minio_path, expires_hours=24)
            result.append({
                "node_id": None,
                "filename": db_file.filename,
                "artifact_type": "original",
                "url": url,
                "size": db_file.size_bytes,
                "minio_path": db_file.minio_path,
            })

    # Terminal nodes: those with no outgoing edges in the workflow graph.
    # Their artifacts are promoted to the top level (node_id=None) as the final output.
    terminal_node_ids = set()
    if execution.workflow_template and execution.workflow_template.graph:
        graph = execution.workflow_template.graph
        all_from_ids = {e.from_node_id for e in (graph.edges or [])}
        for n in (graph.nodes or []):
            if n.id not in all_from_ids:
                terminal_node_ids.add(n.id)

    # Per-node artifacts
    nodes = node_repo.get_by_execution(execution_id)
    all_artifacts = storage.list_workflow_artifacts(workflow_id)
    for node in nodes:
        prefix = f"{workflow_id}/{node.node_id}/"
        for art in all_artifacts:
            obj_name = art["object_name"]
            if not obj_name.startswith(prefix):
                continue
            filename = obj_name.split("/")[-1]
            if filename == "output.json":
                continue
            url = storage.get_artifact_url(obj_name, expires_hours=24)
            artifact_type = obj_name[len(prefix):].split("/")[0] if "/" in obj_name[len(prefix):] else "unknown"

            # Always include with node's own node_id
            result.append({
                "node_id": node.node_id,
                "filename": filename,
                "artifact_type": artifact_type,
                "url": url,
                "size": art.get("size"),
                "minio_path": obj_name,
            })

            # If this is a terminal node, also promote to top level (node_id=None)
            if node.node_id in terminal_node_ids:
                result.append({
                    "node_id": None,
                    "filename": filename,
                    "artifact_type": artifact_type,
                    "url": url,
                    "size": art.get("size"),
                    "minio_path": obj_name,
                })
    return result


@router.get("/executions/{execution_id}/nodes/{node_id}", response_model=ExecutionNodeModel)
async def get_execution_node(execution_id: str, node_id: str):
    from src.utils.storage import get_storage
    storage = get_storage()

    nodes = node_repo.get_by_execution(execution_id)
    node = next((n for n in nodes if n.node_id == node_id or n.id == node_id), None)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    execution = exec_repo.get(execution_id)
    workflow_id = execution_id if execution else execution_id
    prefix = f"{workflow_id}/{node.node_id}/"
    all_artifacts = storage.list_workflow_artifacts(workflow_id)
    node_artifacts = []
    for art in all_artifacts:
        obj_name = art["object_name"]
        if not obj_name.startswith(prefix):
            continue
        filename = obj_name.split("/")[-1]
        if filename == "output.json":
            continue
        url = storage.get_artifact_url(obj_name, expires_hours=24)
        artifact_type = obj_name[len(prefix):].split("/")[0] if "/" in obj_name[len(prefix):] else "unknown"
        node_artifacts.append({
            "filename": filename,
            "artifact_type": artifact_type,
            "url": url,
            "size": art.get("size"),
            "minio_path": obj_name,
        })

    result = node.model_copy(update={"artifacts": node_artifacts})
    return result


@router.get("/executions/{execution_id}/nodes/{node_id}/logs")
async def get_node_logs(execution_id: str, node_id: str):
    nodes = node_repo.get_by_execution(execution_id)
    node = next((n for n in nodes if n.node_id == node_id or n.id == node_id), None)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    from src.utils.storage import get_storage
    storage = get_storage()

    attempt = 1
    object_name = f"executions/{execution_id}/{attempt}/{node.plugin_id}/node.log"
    url = storage.get_log_url(object_name, expires_hours=24)

    return {"attempt": attempt, "url": url}


@router.post("/executions/{execution_id}/restart")
async def restart_execution(execution_id: str):
    execution = exec_repo.get(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    exec_repo.update_status(execution_id, "pending", error_message="")
    for node in node_repo.get_by_execution(execution_id):
        node_repo.update(str(node.id), status="pending", error_message=None)
    return {"execution_id": execution_id, "status": "pending"}


@router.get("/{workflow_id}", response_model=WorkflowTemplateModel)
async def get_workflow(workflow_id: str):
    wf = repo.get(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


@router.put("/{workflow_id}", response_model=WorkflowTemplateModel)
async def update_workflow(workflow_id: str, req: WorkflowCreateRequest):
    wf = repo.update(workflow_id, name=req.name, description=req.description,
                     graph=req.graph, is_public=req.is_public)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str):
    if not repo.delete(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"ok": True}


@router.post("/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    request: ExecuteWorkflowRequest,
    user_id: Optional[str] = None
):
    from src.db.entity import ExecutionStatus, NodeExecutionStatus
    from datetime import datetime, timezone

    execution_id = str(uuid.uuid4())

    wf = repo.get(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow template not found")

    # Look up workflow name and input file name
    workflow_name = wf.name or ""
    file_name = request.file_path.split("/")[-1] if request.file_path else request.file_id

    node_defs = wf.graph.nodes if hasattr(wf.graph, "nodes") else []

    exec_repo.create({
        "id": execution_id,
        "workflow_template_id": workflow_id,
        "file_id": request.file_id,
        "user_id": user_id,
        "workflow_name": workflow_name,
        "file_name": file_name,
        "language": request.language,
        "status": ExecutionStatus.PENDING,
        "created_at": datetime.now(timezone.utc),
    })

    for node_def in node_defs:
        node_repo.create({
            "id": str(uuid.uuid4()),
            "execution_id": execution_id,
            "node_id": node_def.id,
            "node_template_id": None,
            "plugin_id": node_def.plugin_id,
            "node_name": node_def.name or "",
            "status": NodeExecutionStatus.PENDING,
            "input_data": {},
            "created_at": datetime.now(timezone.utc),
            "progress_percent": 0,
            "progress_message": "Ожидание...",
        })

    return {
        "execution_id": execution_id,
        "status": ExecutionStatus.PENDING,
        "message": "Execution queued — OrchestratorService will pick it up shortly"
    }
