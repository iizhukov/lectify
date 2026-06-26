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
    return []


@router.get("/executions/{execution_id}/nodes/{node_id}", response_model=ExecutionNodeModel)
async def get_execution_node(execution_id: str, node_id: str):
    nodes = node_repo.get_by_execution(execution_id)
    for n in nodes:
        if n.node_id == node_id or n.id == node_id:
            return n
    raise HTTPException(status_code=404, detail="Node not found")


@router.get("/executions/{execution_id}/nodes/{node_id}/logs")
async def get_node_logs(execution_id: str, node_id: str):
    nodes = node_repo.get_by_execution(execution_id)
    node = next((n for n in nodes if n.node_id == node_id or n.id == node_id), None)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    log_manager = NodeLogManager()
    log_type = "node"
    logs = log_manager.get_logs(execution_id, node_id, log_type=log_type)
    if logs is None:
        return ""
    return logs


@router.post("/executions/{execution_id}/restart")
async def restart_execution(execution_id: str):
    execution = exec_repo.get(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    exec_repo.update_status(execution_id, "pending")
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

    node_defs = wf.graph.nodes if hasattr(wf.graph, "nodes") else []

    exec_repo.create({
        "id": execution_id,
        "workflow_template_id": workflow_id,
        "file_id": request.file_id,
        "user_id": user_id,
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
